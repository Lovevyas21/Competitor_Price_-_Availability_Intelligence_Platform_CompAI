import pytest

from app.ai.matching import (
    AUTO_MATCH_THRESHOLD,
    EMBEDDING_DIM,
    REVIEW_THRESHOLD,
    build_text,
)


def test_combines_title_brand_and_category():
    assert build_text("Nutella", "Ferrero", "spreads") == "Nutella | Ferrero | spreads"


def test_missing_fields_dropped():
    assert build_text("Nutella", None, None) == "Nutella"


def test_blank_and_whitespace_fields_are_dropped():
    assert build_text("Nutella", "   ", "") == "Nutella"


def test_values_are_trimmed():
    assert build_text("  Nutella  ", " Ferrero ", None) == "Nutella | Ferrero"


def test_entirely_empty_input_yields_empty_string():
    assert build_text(None, None, None) == ""
    assert build_text("", "  ", None) == ""


def test_brand_and_category_in_text():
    a = build_text("Baguette", "Leclerc", "bread")
    b = build_text("Baguette", "Intermarche", "bread")
    assert a != b


def test_thresholds_match_the_build_document():
    assert AUTO_MATCH_THRESHOLD == 0.92
    assert REVIEW_THRESHOLD == 0.80


def test_review_band_sits_below_auto_match():
    assert REVIEW_THRESHOLD < AUTO_MATCH_THRESHOLD


def test_embedding_dim_matches_the_schema_column():
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
        (0.92, "auto"),
        (0.919, "review"),
        (0.85, "review"),
        (0.80, "review"),
        (0.799, "reject"),
        (0.50, "reject"),
    ],
)
def test_similarity_lands_in_the_expected_band(similarity, expected):
    assert band(similarity) == expected
