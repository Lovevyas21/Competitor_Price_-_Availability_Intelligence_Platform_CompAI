"""Alerting: fingerprinting, message formatting, and delivery failure handling.

The fingerprint is the important bit. Alerting runs every 6 hours; an undercut that
persists for a week is one piece of news, not 28. But a competitor cutting *further* is
genuinely new, so the price has to be part of the identity.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.alerting.channels import SlackChannel
from app.alerting.service import _fingerprint, format_message


def row(**overrides):
    base = {
        "retailer_name": "E.Leclerc",
        "upc": "3017620422003",
        "currency": "EUR",
        "competitor_price": "2.99",
        "our_price": "3.75",
        "product_name": "Nutella",
        "gap_pct": "-20.3",
        "days_stale": 2,
    }
    base.update(overrides)
    return base


# fingerprinting / dedupe identity
def test_same_undercut_has_a_stable_fingerprint():
    assert _fingerprint(row()) == _fingerprint(row())


def test_a_deeper_cut_is_a_different_alert():
    """A competitor dropping further is new information and should notify again."""
    assert _fingerprint(row()) != _fingerprint(row(competitor_price="2.49"))


def test_different_retailers_are_different_alerts():
    assert _fingerprint(row()) != _fingerprint(row(retailer_name="Intermarche"))


def test_different_products_are_different_alerts():
    assert _fingerprint(row()) != _fingerprint(row(upc="0000000000001"))


def test_same_number_in_a_different_currency_is_a_different_alert():
    assert _fingerprint(row()) != _fingerprint(row(currency="SEK"))


def test_fingerprint_has_no_newline_so_it_survives_message_encoding():
    """The fingerprint is appended after a newline marker; one inside would break parsing."""
    assert "\n" not in _fingerprint(row())


# message
def test_message_states_who_what_and_how_much():
    message = format_message(row())
    assert "E.Leclerc" in message
    assert "Nutella" in message
    assert "20.3%" in message
    assert "2.99" in message and "3.75" in message


def test_message_reports_the_percentage_as_a_magnitude():
    """gap_pct is negative for an undercut; '-20.3%' below us reads as a double negative."""
    assert "-20.3%" not in format_message(row())


def test_message_surfaces_evidence_age():
    assert "2d ago" in format_message(row(days_stale=2))


# Slack delivery
#
# Slack posting moved from service.py into SlackChannel when email was added; these
# assertions follow it rather than being deleted, since the behaviour still matters.
SLACK = SlackChannel("http://hook")


def test_successful_post_reports_success():
    with patch("app.alerting.channels.httpx.post") as post:
        post.return_value = httpx.Response(200, request=httpx.Request("POST", "http://x"))
        assert SLACK.send_batch(["hello"]) is True


def test_delivery_failure_is_reported_not_raised():
    """A webhook outage must not kill the alert cycle -- the send is retried next cycle."""
    with patch("app.alerting.channels.httpx.post", side_effect=httpx.ConnectError("down")):
        assert SLACK.send_batch(["hello"]) is False


def test_http_error_status_is_treated_as_failure():
    with patch("app.alerting.channels.httpx.post") as post:
        post.return_value = httpx.Response(500, request=httpx.Request("POST", "http://x"))
        assert SLACK.send_batch(["hello"]) is False


@pytest.mark.parametrize("status_code", [200, 201, 204])
def test_any_2xx_counts_as_delivered(status_code):
    with patch("app.alerting.channels.httpx.post") as post:
        post.return_value = httpx.Response(status_code, request=httpx.Request("POST", "http://x"))
        assert SLACK.send_batch(["hello"]) is True


def test_slack_posts_one_message_per_alert():
    """Chat reads better as separate messages; email is the one that digests."""
    with patch("app.alerting.channels.httpx.post") as post:
        post.return_value = httpx.Response(200, request=httpx.Request("POST", "http://x"))
        SLACK.send_batch(["one", "two", "three"])
    assert post.call_count == 3


def test_one_failed_post_fails_the_batch():
    """Partial delivery is not delivery: sent_at must stay null so it retries."""
    with patch("app.alerting.channels.httpx.post") as post:
        post.side_effect = [
            httpx.Response(200, request=httpx.Request("POST", "http://x")),
            httpx.ConnectError("down"),
        ]
        assert SLACK.send_batch(["one", "two"]) is False
