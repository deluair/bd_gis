from validation.reference import load_hies_division_hcr, load_csv_reference, LOADERS


def test_hies_division_hcr_returns_eight_divisions():
    d = load_hies_division_hcr()
    assert len(d) == 8
    # Verified against BBS HIES 2022 Final Report (upper poverty line).
    assert d["Barishal"] == 26.9
    assert d["Khulna"] == 14.8


def test_loaders_registry_exposes_hies():
    assert "hies_division_hcr" in LOADERS
    assert LOADERS["hies_division_hcr"] is load_hies_division_hcr


def test_load_csv_reference(tmp_path):
    p = tmp_path / "ref.csv"
    p.write_text("division,value\nDhaka,17.9\nSylhet,17.4\n")
    out = load_csv_reference(str(p), "division", "value")
    assert out == {"Dhaka": 17.9, "Sylhet": 17.4}
