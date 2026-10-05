from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.alerting.channels import (
    EmailChannel,
    SesChannel,
    SlackChannel,
    build_digest,
    configured_channels,
)
from app.core.settings import Settings

MESSAGES = [
    "Intermarche is undercutting Bio et equitable by 54.0% (0.99 vs 2.15 EUR). Observed 2d ago.",
    "Super U is undercutting Sriracha by 27.5% (3.14 vs 4.33 EUR). Observed 4d ago.",
]


def test_no_channels_when_nothing_is_configured():
    assert configured_channels(Settings()) == []


def test_email_needs_host_sender_and_recipient():
    partial = Settings(smtp_host="smtp.example.com", alert_email_from="a@example.com")
    assert not EmailChannel(partial).is_configured()

    complete = Settings(
        smtp_host="smtp.example.com",
        alert_email_from="a@example.com",
        alert_email_to="b@example.com",
    )
    assert EmailChannel(complete).is_configured()


def test_unconfigured_email_refuses_to_send():
    with patch("app.alerting.channels.smtplib.SMTP") as smtp:
        assert EmailChannel(Settings()).send_batch(MESSAGES) is False
    smtp.assert_not_called()


def test_unconfigured_slack_refuses_to_send():
    with patch("app.alerting.channels.httpx.post") as post:
        assert SlackChannel(None).send_batch(MESSAGES) is False
    post.assert_not_called()


def test_empty_batch_sends_nothing():
    settings = Settings(
        smtp_host="smtp.example.com",
        alert_email_from="a@example.com",
        alert_email_to="b@example.com",
    )
    with patch("app.alerting.channels.smtplib.SMTP") as smtp:
        assert EmailChannel(settings).send_batch([]) is False
    smtp.assert_not_called()


def test_digest_subject_counts_the_alerts():
    digest = build_digest(MESSAGES, generated_at=datetime(2026, 9, 2, tzinfo=UTC))
    assert "2 competitor undercuts" in digest["Subject"]
    assert "02 Sep 2026" in digest["Subject"]


def test_digest_subject_is_singular_for_one_alert():
    digest = build_digest(MESSAGES[:1], generated_at=datetime(2026, 9, 2, tzinfo=UTC))
    assert "1 competitor undercut " in digest["Subject"] + " "


def test_digest_body_contains_every_message_numbered():
    body = build_digest(MESSAGES).get_content()
    assert "1. " + MESSAGES[0] in body
    assert "2. " + MESSAGES[1] in body


def test_digest_explains_the_staleness_policy():
    assert "older than 7 days" in build_digest(MESSAGES).get_content()


@pytest.fixture
def smtp_settings():
    return Settings(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="user",
        smtp_password="pass",
        alert_email_from="alerts@example.com",
        alert_email_to="pricing@example.com, analyst@example.com",
    )


def test_email_sends_one_digest_not_one_per_alert(smtp_settings):
    with patch("app.alerting.channels.smtplib.SMTP") as smtp:
        client = smtp.return_value.__enter__.return_value
        assert EmailChannel(smtp_settings).send_batch(MESSAGES) is True
    assert client.send_message.call_count == 1


def test_email_addresses_every_recipient(smtp_settings):
    with patch("app.alerting.channels.smtplib.SMTP") as smtp:
        client = smtp.return_value.__enter__.return_value
        EmailChannel(smtp_settings).send_batch(MESSAGES)
    sent = client.send_message.call_args.args[0]
    assert "pricing@example.com" in sent["To"]
    assert "analyst@example.com" in sent["To"]
    assert sent["From"] == "alerts@example.com"


def test_email_uses_tls_and_authenticates(smtp_settings):
    with patch("app.alerting.channels.smtplib.SMTP") as smtp:
        client = smtp.return_value.__enter__.return_value
        EmailChannel(smtp_settings).send_batch(MESSAGES)
    client.starttls.assert_called_once()
    client.login.assert_called_once_with("user", "pass")


def test_email_without_credentials_skips_login(smtp_settings):
    anonymous = smtp_settings.model_copy(update={"smtp_username": None, "smtp_password": None})
    with patch("app.alerting.channels.smtplib.SMTP") as smtp:
        client = smtp.return_value.__enter__.return_value
        EmailChannel(anonymous).send_batch(MESSAGES)
    client.login.assert_not_called()


def test_smtp_failure_is_reported_not_raised(smtp_settings):
    with patch("app.alerting.channels.smtplib.SMTP", side_effect=OSError("connection refused")):
        assert EmailChannel(smtp_settings).send_batch(MESSAGES) is False


def test_ses_wins_over_smtp_when_both_configured():
    both = Settings(
        ses_region="ap-south-1",
        smtp_host="smtp.example.com",
        alert_email_from="a@example.com",
        alert_email_to="b@example.com",
    )
    names = [c.name for c in configured_channels(both)]
    assert "ses" in names
    assert "email" not in names


def test_slack_and_email_can_both_be_active():
    settings = Settings(
        slack_webhook_url="https://hooks.slack.example/x",
        smtp_host="smtp.example.com",
        alert_email_from="a@example.com",
        alert_email_to="b@example.com",
    )
    assert sorted(c.name for c in configured_channels(settings)) == ["email", "slack"]


def test_ses_needs_region_sender_and_recipient():
    assert not SesChannel(Settings(ses_region="ap-south-1")).is_configured()
    assert SesChannel(
        Settings(
            ses_region="ap-south-1",
            alert_email_from="a@example.com",
            alert_email_to="b@example.com",
        )
    ).is_configured()


def test_ses_sends_through_boto3():
    settings = Settings(
        ses_region="ap-south-1",
        alert_email_from="a@example.com",
        alert_email_to="b@example.com",
    )
    fake_boto3 = MagicMock()
    with patch.dict("sys.modules", {"boto3": fake_boto3}):
        assert SesChannel(settings).send_batch(MESSAGES) is True
    call = fake_boto3.client.return_value.send_email.call_args.kwargs
    assert call["Source"] == "a@example.com"
    assert call["Destination"]["ToAddresses"] == ["b@example.com"]


def test_dry_run_records_nothing():
    from app.alerting import service

    candidates = [
        {
            "product_id": 1,
            "retailer_id": 1,
            "upc": "123",
            "our_sku": "OWN-1",
            "product_name": "Thing",
            "retailer_name": "Shop",
            "currency": "EUR",
            "our_price": 2.0,
            "competitor_price": 1.0,
            "gap_abs": -1.0,
            "gap_pct": -50.0,
            "severity": "critical",
            "confidence": "fresh",
            "days_stale": 1,
        }
    ]

    session = MagicMock()
    scope = MagicMock()
    scope.__enter__.return_value = session

    with (
        patch.object(service, "session_scope", return_value=scope),
        patch.object(service, "load_candidates", return_value=candidates),
        patch.object(service, "existing_fingerprints", return_value={}),
        patch.object(service, "deliver") as deliver,
    ):
        stats = service.run_alert_cycle(dry_run=True)

    assert stats["created"] == 1
    session.execute.assert_not_called()
    deliver.assert_not_called()
