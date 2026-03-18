"""
Land cover / land use classification – MODIS, Dynamic World, ESA WorldCover,
and Copernicus Global Land Cover for multi-scale LULC analysis.

NOTE: Multiple land cover products are computed independently.
Known discrepancies exist (e.g., Sundarbans: MODIS=Evergreen Broadleaf,
ESA=Mangrove; Haors: MODIS=Wetlands/Croplands, DW=flooded_vegetation).
Cross-product validation is not yet implemented.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Data Loading
# ═══════════════════════════════════════════════════════════════════════════════

def get_modis_landcover(year, region):
    """Get MODIS annual land cover (IGBP classification) for a year."""
    col = (
        ee.ImageCollection(cfg.MODIS_LANDCOVER["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .select(cfg.MODIS_LANDCOVER["band"])
    )
    return col.first().clip(region)


def get_dynamic_world(start_date, end_date, region):
    """Get Dynamic World mode composite (most frequent class per pixel).

    Full-year mode is biased toward monsoon (4-5 months of daily observations).
    For seasonal analysis, consider dry-season (Oct-Mar) mode separately.
    """
    col = (
        ee.ImageCollection(cfg.DYNAMIC_WORLD["collection"])
        .filterDate(start_date, end_date)
        .filterBounds(region)
        .select(cfg.DYNAMIC_WORLD["band"])
    )
    return col.mode().clip(region)


def get_dynamic_world_probabilities(start_date, end_date, region):
    """Get Dynamic World mean class probabilities."""
    col = (
        ee.ImageCollection(cfg.DYNAMIC_WORLD["collection"])
        .filterDate(start_date, end_date)
        .filterBounds(region)
        .select(cfg.DW_CLASSES)
    )
    return col.mean().clip(region)


def get_esa_worldcover(year, region):
    """Get ESA WorldCover (10m resolution) for 2020 or 2021."""
    if str(year) not in cfg.ESA_WORLDCOVER:
        print(f"  WARNING: ESA WorldCover not available for {year}, using 2021 fallback")
        key = "2021"
    else:
        key = str(year)
    return ee.Image(cfg.ESA_WORLDCOVER[key]).select(cfg.ESA_WORLDCOVER["band"]).clip(region)


def get_copernicus_landcover(year, region):
    """Get Copernicus Global Land Cover (100m) for a year (2015-2019)."""
    if year < 2015 or year > 2019:
        print(f"  WARNING: Copernicus LULC only covers 2015-2019, requested {year}")
    col = (
        ee.ImageCollection(cfg.COPERNICUS_LANDCOVER["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .select(cfg.COPERNICUS_LANDCOVER["band"])
    )
    return col.first().clip(region)


# ═══════════════════════════════════════════════════════════════════════════════
# Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def compute_lulc_area_stats(classified_image, region, scale=None, class_values=None,
                            class_names=None):
    """
    Compute area (km2) per land cover class.
    Returns list of {class_value, class_name, area_km2}.
    """
    if scale is None:
        scale = 500
    if class_values is None:
        class_values = list(range(18))  # MODIS IGBP has 17 classes (0-17)
    if class_names is None:
        class_names = [str(v) for v in class_values]

    results = []
    band_name = classified_image.bandNames().getInfo()[0]
    for val, name in zip(class_values, class_names):
        class_mask = classified_image.eq(val)
        area = class_mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=region,
            scale=scale,
            maxPixels=cfg.MAX_PIXELS,
            bestEffort=True,
        )
        results.append({
            "class_value": val,
            "class_name": name,
            "area_km2": ee.Number(area.get(band_name)).divide(1e6),
        })
    return results


def compute_lulc_change(year1, year2, region, source="modis"):
    """
    Compute LULC change between two years.
    Returns change image and transition matrix stats.
    """
    if source == "modis":
        lc1 = get_modis_landcover(year1, region)
        lc2 = get_modis_landcover(year2, region)
        scale = cfg.MODIS_LANDCOVER["scale"]
    elif source == "dynamic_world":
        lc1 = get_dynamic_world(f"{year1}-01-01", f"{year1}-12-31", region)
        lc2 = get_dynamic_world(f"{year2}-01-01", f"{year2}-12-31", region)
        scale = cfg.DYNAMIC_WORLD["scale"]
    else:
        raise ValueError(f"Unknown LULC source: {source}")

    # Change detection: pixels where class changed
    changed = lc1.neq(lc2).rename("lulc_changed")

    # Encode transition: from_class * 100 + to_class
    transition = lc1.multiply(100).add(lc2).rename("transition")
    transition = transition.updateMask(changed)

    return {
        "lc_early": lc1,
        "lc_late": lc2,
        "changed": changed,
        "transition": transition,
        "scale": scale,
    }


def compute_dw_class_timeseries(region, start_year=2015, end_year=2024, step=1):
    """
    Track Dynamic World class proportions over time.
    Returns list of {year, water, trees, grass, crops, built, bare, ...}.
    """
    series = []
    for year in range(start_year, end_year + 1, step):
        try:
            probs = get_dynamic_world_probabilities(
                f"{year}-01-01", f"{year}-12-31", region
            )
            stats = probs.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region,
                scale=300 if cfg.SCOPE == "national" else 100,
                maxPixels=cfg.MAX_PIXELS,
                bestEffort=True,
            )
            entry = {"year": year}
            for cls in cfg.DW_CLASSES:
                entry[cls] = stats.get(cls)
            series.append(entry)
        except Exception as e:
            print(f"  DW timeseries {year} skipped: {e}")
    return series


def compute_modis_lulc_timeseries(region, start_year=2001, end_year=2023, step=2):
    """Track MODIS LULC class areas over time."""
    IGBP_NAMES = [
        "Water Bodies",
        "Evergreen Needleleaf", "Evergreen Broadleaf", "Deciduous Needleleaf",
        "Deciduous Broadleaf", "Mixed Forest", "Closed Shrublands",
        "Open Shrublands", "Woody Savannas", "Savannas", "Grasslands",
        "Permanent Wetlands", "Croplands", "Urban", "Cropland/Natural Mosaic",
        "Snow/Ice", "Barren", "Water",
    ]
    series = []
    for year in range(start_year, end_year + 1, step):
        try:
            lc = get_modis_landcover(year, region)
            stats = compute_lulc_area_stats(
                lc, region,
                scale=cfg.MODIS_LANDCOVER["scale"],
                class_values=list(range(0, 18)),
                class_names=IGBP_NAMES,
            )
            entry = {"year": year}
            for s in stats:
                entry[s["class_name"]] = s["area_km2"]
            series.append(entry)
        except Exception as e:
            print(f"  MODIS LULC {year} skipped: {e}")
    return series


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_land_cover_analysis(region):
    """Full LULC analysis pipeline.

    NOTE: Multiple land cover products are computed independently.
    Known discrepancies exist (e.g., Sundarbans: MODIS=Evergreen Broadleaf,
    ESA=Mangrove; Haors: MODIS=Wetlands/Croplands, DW=flooded_vegetation).
    Cross-product validation is not yet implemented.
    """
    results = {}

    print("\n  Computing MODIS LULC time series (2001–2023)...")
    results["modis_timeseries"] = compute_modis_lulc_timeseries(region)

    print("  Computing Dynamic World class proportions (2015-2024)...")
    results["dw_timeseries"] = compute_dw_class_timeseries(region)

    print("  Loading ESA WorldCover 2021...")
    try:
        results["esa_worldcover"] = get_esa_worldcover(2021, region)
    except Exception as e:
        print(f"    ESA WorldCover skipped: {e}")

    print("  Computing MODIS LULC change 2001–2023...")
    try:
        results["modis_change"] = compute_lulc_change(2001, 2023, region, "modis")
    except Exception as e:
        print(f"    MODIS change skipped: {e}")

    print("  Computing Dynamic World change 2015-2024...")
    try:
        results["dw_change"] = compute_lulc_change(2015, 2024, region, "dynamic_world")
    except Exception as e:
        print(f"    DW change skipped: {e}")

    return results
