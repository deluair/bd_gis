from validation.run import validate_indicator
from validation.reference import load_hies_division_hcr


def test_perfect_correlation_is_tier_a(tmp_path):
    ref = load_hies_division_hcr()
    predicted = {k: v * 2 for k, v in ref.items()}  # r == 1.0
    card = validate_indicator(
        "gis_poverty_index", predicted, "2026-05-29T00:00:00Z", str(tmp_path), period="2022"
    )
    assert card["quality_tier"] == "A"
    assert card["n"] == len(ref)
    assert (tmp_path / "validation" / "gis_poverty_index.json").exists()


def test_zero_variance_falls_back_to_tier_c(tmp_path):
    ref = load_hies_division_hcr()
    predicted = {k: 5.0 for k in ref}  # constant -> zero variance
    card = validate_indicator(
        "gis_poverty_index", predicted, "2026-05-29T00:00:00Z", str(tmp_path)
    )
    assert card["quality_tier"] == "C"
    assert any("degenerate" in c or "insufficient" in c for c in card["caveats"])


def test_unknown_indicator_raises(tmp_path):
    import pytest
    with pytest.raises(KeyError):
        validate_indicator("nope", {}, "2026-05-29T00:00:00Z", str(tmp_path))
