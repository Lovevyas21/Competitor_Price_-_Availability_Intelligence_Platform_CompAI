"""Matching: the text that gets embedded, and the threshold policy.

The banding rules are the part with real consequences -- a threshold set wrong either
floods the review queue or silently auto-approves wrong pairs -- so they are pinned here
rather than left implicit in SQL.
"""

from __future__ import annotations

import pytest

from app.ai.matching import (
    AUTO_MATCH_THRESHOLD,
    EMBEDDING_DIM,
    REVIEW_THRESHOLD,
    build_text,
)


# --------------------------------------------------------------------------- #
# embedded text
# --------------------------------------------------------------------------- #
def test_combines_title_brand_and_category():
    assert build_text("Nutella", "Ferrero", "spreads") == "Nutella | Ferrero | spreads"


def test_missing_fields_are_dropped_not_rendered_as_none():
    assert build_text("Nutella", None, None) == "Nutella"


def test_blank_and_whitespace_fields_are_dropped():
    assert build_text("Nutella", "   ", "") == "Nutella"


def test_values_are_trimmed():
    assert build_text("  Nutella  ", " Ferrero ", None) == "Nutella | Ferrero"


def test_entirely_empty_input_yields_empty_string():
    """Callers use this to skip products with nothing to embed."""
    assert build_text(None, None, None) == ""
    assert build_text("", "  ", None) == ""


def test_brand_and_category_add_discriminating_context():
    """Two 'Baguette' products differ only by their context fields."""
    a = build_text("Baguette", "Leclerc", "bread")
    b = build_text("Baguette", "Intermarche", "bread")
    assert a != b


# --------------------------------------------------------------------------- #
# threshold policy
# --------------------------------------------------------------------------- #
def test_thresholds_match_the_build_document():
    assert AUTO_MATCH_THRESHOLD == 0.92
    assert REVIEW_THRESHOLD == 0.80


def test_review_band_sits_below_auto_match():
    assert REVIEW_THRESHOLD < AUTO_MATCH_THRESHOLD


def test_embedding_dim_matches_the_schema_column():
    """product_versions.embedding is vector(384); a mismatch fails only at insert time."""
    assert EMBEDDING_DIM == 384


def band(similarity: float) -> str:
    if similarity >= AUTO_MATCH_THRESHOLD:
        return "auto"
    if similarity >= REVIEW_THRESHOLD:
        return "review"
    return "reject"


@pytest.mark.parametrize(
    "similarity,expected",
    [
        (1.00, "auto"),
        (0.95, "auto"),
        (0.92, "auto"),  # boundary is inclusive
        (0.919, "review"),
        (0.85, "review"),
        (0.80, "review"),  # boundary is inclusive
        (0.799, "reject"),
        (0.50, "reject"),
    ],
)
def test_similarity_lands_in_the_expected_band(similarity, expected):
    assert band(similarity) == expected
