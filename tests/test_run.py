from validation.reference import load_hies_division_hcr
from validation.run import validate_indicator


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
    predicted = dict.fromkeys(ref, 5.0)  # constant -> zero variance
    card = validate_indicator(
        "gis_poverty_index", predicted, "2026-05-29T00:00:00Z", str(tmp_path)
    )
    assert card["quality_tier"] == "C"
    assert any("degenerate" in c or "insufficient" in c for c in card["caveats"])


def test_unknown_indicator_raises(tmp_path):
    import pytest
    with pytest.raises(KeyError):
        validate_indicator("nope", {}, "2026-05-29T00:00:00Z", str(tmp_path))


def test_non_continuous_comparison_raises(tmp_path, monkeypatch):
    import pytest

    from validation import registry
    monkeypatch.setitem(
        registry.INDICATORS, "fake_cat",
        {"label": "x", "classification": "measured", "comparison": "categorical",
         "spatial_unit": "grid", "reference": "hies_division_hcr",
         "reference_source": "x", "reference_citation": "x"},
    )
    with pytest.raises(NotImplementedError):
        validate_indicator("fake_cat", {"a": 1}, "2026-05-29T00:00:00Z", str(tmp_path))


def test_partial_join_records_caveat(tmp_path):
    ref = load_hies_division_hcr()
    predicted = {k: v * 2 for k, v in ref.items()}
    predicted["NotADivision"] = 99.0  # one unmatched key
    card = validate_indicator(
        "gis_poverty_index", predicted, "2026-05-29T00:00:00Z", str(tmp_path)
    )
    assert any("did not match" in c for c in card["caveats"])


def test_reference_unit_without_prediction_records_caveat(tmp_path):
    # Regression: the satellite side uses GAUL 2015 (7 divisions) while HIES
    # reports 8, so Mymensingh was scored as a clean join over a partial area.
    ref = load_hies_division_hcr()
    predicted = {k: v * 2 for k, v in ref.items()}
    dropped = predicted.pop("Mymensingh")
    assert dropped is not None
    card = validate_indicator(
        "gis_poverty_index", predicted, "2026-05-29T00:00:00Z", str(tmp_path)
    )
    assert any("Mymensingh" in c and "no prediction" in c for c in card["caveats"])
    assert card["coverage"] == {
        "n_predicted": len(ref) - 1, "n_reference": len(ref), "n_matched": len(ref) - 1
    }


def test_main_cli_writes_card(tmp_path, monkeypatch, capsys):
    import config
    from validation import run as runmod
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path))
    runmod.main([
        "gis_poverty_index",
        "--predicted-csv", "tests/fixtures/poverty_division_pred.csv",
        "--unit-col", "division", "--value-col", "value", "--period", "2022",
    ])
    assert (tmp_path / "validation" / "gis_poverty_index.json").exists()
    assert "gis_poverty_index" in capsys.readouterr().out


def test_static_caveats_merged_into_card(tmp_path, monkeypatch):
    from validation import registry
    monkeypatch.setitem(
        registry.INDICATORS["gis_poverty_index"], "static_caveats", ["known offset note"]
    )
    ref = load_hies_division_hcr()
    predicted = {k: v * 2 for k, v in ref.items()}
    card = validate_indicator(
        "gis_poverty_index", predicted, "2026-05-29T00:00:00Z", str(tmp_path)
    )
    assert "known offset note" in card["caveats"]
