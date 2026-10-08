from unittest.mock import patch

import httpx
import pytest

from app.alerting.channels import SlackChannel
from app.alerting.service import _fingerprint, format_message, is_material_gap


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


def test_same_undercut_has_a_stable_fingerprint():
    assert _fingerprint(row()) == _fingerprint(row())


def test_deeper_cut_new_alert():
    assert _fingerprint(row()) != _fingerprint(row(competitor_price="2.49"))


def test_different_retailers_are_different_alerts():
    assert _fingerprint(row()) != _fingerprint(row(retailer_name="Intermarche"))


def test_different_products_are_different_alerts():
    assert _fingerprint(row()) != _fingerprint(row(upc="0000000000001"))


def test_currency_changes_fingerprint():
    assert _fingerprint(row()) != _fingerprint(row(currency="SEK"))


def test_fingerprint_single_line():
    assert "\n" not in _fingerprint(row())


def test_message_states_who_what_and_how_much():
    message = format_message(row())
    assert "E.Leclerc" in message
    assert "Nutella" in message
    assert "20.3%" in message
    assert "2.99" in message and "3.75" in message


def test_message_percentage():
    assert "-20.3%" not in format_message(row())


def test_message_surfaces_evidence_age():
    assert "2d ago" in format_message(row(days_stale=2))


SLACK = SlackChannel("http://hook")


def test_successful_post_reports_success():
    with patch("app.alerting.channels.httpx.post") as post:
        post.return_value = httpx.Response(200, request=httpx.Request("POST", "http://x"))
        assert SLACK.send_batch(["hello"]) is True


def test_delivery_failure_is_reported_not_raised():
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
    with patch("app.alerting.channels.httpx.post") as post:
        post.return_value = httpx.Response(200, request=httpx.Request("POST", "http://x"))
        SLACK.send_batch(["one", "two", "three"])
    assert post.call_count == 3


def test_one_failed_post_fails_the_batch():
    with patch("app.alerting.channels.httpx.post") as post:
        post.side_effect = [
            httpx.Response(200, request=httpx.Request("POST", "http://x")),
            httpx.ConnectError("down"),
        ]
        assert SLACK.send_batch(["one", "two"]) is False


@pytest.mark.parametrize(
    ("gap", "expected"),
    [("-0.9", False), ("-1.99", False), ("-2.0", True), ("-20.3", True)],
)
def test_material_gap(gap, expected):
    assert is_material_gap(gap) is expected
