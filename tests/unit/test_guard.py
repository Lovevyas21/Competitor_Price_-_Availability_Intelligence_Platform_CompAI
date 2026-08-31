"""The numeric guardrail.

This is the mechanism that stops a fabricated figure reaching a pricing decision, so it
gets tested harder than the code it protects. The regression at the bottom is real: the
first implementation split "1309" into 130 and 9, which reported phantom violations and
would have made the guard cry wolf until someone disabled it.
"""

from __future__ import annotations

import pytest

from app.ai.facts import WeeklyFacts
from app.ai.guard import extract_numbers, validate_brief


# --------------------------------------------------------------------------- #
# number extraction
# --------------------------------------------------------------------------- #
def test_extracts_plain_and_decimal_numbers():
    assert extract_numbers("price 2.85 and 12") == [2.85, 12.0]


def test_long_integers_are_not_split():
    """Regression: `\\d{1,3}(?:,\\d{3})*` matched only 3 digits without a comma."""
    assert extract_numbers("Products tracked: 1309") == [1309.0]


def test_long_integer_with_trailing_letter_is_not_split():
    assert extract_numbers("stale (5885d old)") == [5885.0]


def test_thousands_separators_are_understood():
    assert extract_numbers("total 1,234.56 EUR") == [1234.56]


def test_iso_dates_are_not_read_as_numbers():
    assert extract_numbers("generated 2026-09-01") == []


def test_ordered_list_markers_are_ignored():
    assert extract_numbers("1. first item\n2. second item") == []


def test_negative_numbers_are_captured():
    assert -33.73 in extract_numbers("gap of -33.73%")


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def test_brief_using_only_known_numbers_passes():
    result = validate_brief("Undercut of 33.73% at 1.69 EUR", {33.73, 1.69})
    assert result.ok


def test_invented_number_is_caught():
    """The core case: a plausible figure that no query produced."""
    result = validate_brief("Undercut of 34.00%", {33.73})
    assert not result.ok
    assert 34.0 in result.unsupported


def test_sign_flip_is_accepted_as_the_same_fact():
    """A -33.73% gap is legitimately written as '33.73% below us'."""
    assert validate_brief("33.73% below us", {-33.73}).ok


def test_small_integers_are_not_policed():
    """Prose integers like 'top 5' are not the fabrication risk."""
    assert validate_brief("the top 5 retailers, 3 of them notable", set()).ok


def test_large_integers_are_policed():
    assert not validate_brief("we track 9999 products", {1309}).ok


def test_multiple_violations_are_all_reported():
    result = validate_brief("11.11 and 22.22 and 33.73", {33.73})
    assert sorted(result.unsupported) == [11.11, 22.22]


def test_checked_count_excludes_skipped_small_integers():
    result = validate_brief("5 items at 2.85 each", {2.85})
    assert result.checked == 1


def test_empty_brief_trivially_passes():
    assert validate_brief("", set()).ok


# --------------------------------------------------------------------------- #
# facts -> allowed numbers
# --------------------------------------------------------------------------- #
def _facts(**overrides) -> WeeklyFacts:
    base = {
        "generated_at": "2026-09-01",
        "period_days": 7,
        "totals": {"products_tracked": 1309},
        "top_undercuts": [
            {"product_name": "Beurre 60% M.G.", "gap_pct": -33.73, "competitor_price": 1.69}
        ],
    }
    base.update(overrides)
    return WeeklyFacts(**base)


def test_numeric_fields_are_allowed():
    numbers = _facts().all_numbers()
    assert 1309 in numbers and -33.73 in numbers and 1.69 in numbers


def test_numbers_inside_product_names_are_allowed():
    """Quoting a product called '60% M.G.' must not read as an invented statistic."""
    assert 60.0 in _facts().all_numbers()


def test_booleans_are_not_treated_as_numbers():
    facts = _facts(data_quality={"healthy": True})
    assert 1.0 not in facts.all_numbers() or 1309 in facts.all_numbers()


def test_a_brief_quoting_a_product_name_passes_the_guard():
    facts = _facts()
    assert validate_brief("Beurre 60% M.G. fell to 1.69", facts.all_numbers()).ok


@pytest.mark.parametrize("invented", ["99.99", "1234.56", "45.5"])
def test_assorted_invented_figures_are_rejected(invented):
    assert not validate_brief(f"the gap was {invented}%", _facts().all_numbers()).ok
