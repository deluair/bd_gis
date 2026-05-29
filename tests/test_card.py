import pytest
from validation.card import build_card, write_card, read_card


def _sample():
    return build_card(
        indicator_id="gis_poverty_index", label="Satellite poverty proxy",
        classification="proxy", quality_tier="C",
        reference_source="HIES 2022 (BBS)", reference_citation="BBS 2023",
        spatial_unit="division", period="2022", comparison="continuous",
        n=8, stats={"pearson_r": 0.20, "mae": 5.0, "rmse": 6.0, "bias": -1.0, "n": 8},
        caveats=["weak proxy"], generated_at="2026-05-29T00:00:00Z",
    )


def test_build_card_has_all_fields():
    c = _sample()
    expected = {"indicator_id", "label", "classification", "quality_tier",
                "reference_source", "reference_citation", "spatial_unit", "period",
                "comparison", "n", "stats", "caveats", "generated_at", "generated_by"}
    assert set(c) == expected
    assert c["generated_by"] == "validation.run"


def test_build_card_rejects_bad_classification():
    with pytest.raises(ValueError):
        build_card("x", "x", "guess", "C", "s", "c", "division", "2022",
                   "continuous", 8, {}, [], "2026-05-29T00:00:00Z")


def test_build_card_rejects_bad_tier():
    with pytest.raises(ValueError):
        build_card("x", "x", "proxy", "Z", "s", "c", "division", "2022",
                   "continuous", 8, {}, [], "2026-05-29T00:00:00Z")


def test_write_then_read_round_trips(tmp_path):
    c = _sample()
    path = write_card(c, str(tmp_path))
    assert path.endswith("validation/gis_poverty_index.json")
    assert read_card("gis_poverty_index", str(tmp_path)) == c
