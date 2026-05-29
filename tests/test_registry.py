import pytest
from validation.registry import assign_tier, TIER_THRESHOLDS, INDICATORS


def test_continuous_tiers_at_boundaries():
    assert assign_tier("continuous", 0.85) == "A"
    assert assign_tier("continuous", 0.80) == "A"
    assert assign_tier("continuous", 0.79) == "B"
    assert assign_tier("continuous", 0.50) == "B"
    assert assign_tier("continuous", 0.20) == "C"


def test_categorical_tiers_at_boundaries():
    assert assign_tier("categorical", 0.85) == "A"
    assert assign_tier("categorical", 0.70) == "B"
    assert assign_tier("categorical", 0.69) == "C"


def test_unknown_comparison_raises():
    with pytest.raises(ValueError):
        assign_tier("bogus", 0.9)


def test_indicators_have_required_fields():
    required = {"label", "classification", "comparison", "spatial_unit",
                "reference", "reference_source", "reference_citation"}
    for ind, cfg in INDICATORS.items():
        assert required <= set(cfg), f"{ind} missing fields"
        assert cfg["classification"] in ("measured", "proxy")
        assert cfg["comparison"] in TIER_THRESHOLDS
