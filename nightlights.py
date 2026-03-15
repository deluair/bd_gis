"""
Nighttime lights analysis – DMSP-OLS (1992–2013) and VIIRS DNB (2014–present)
for tracking electrification, economic activity, and urbanization patterns.
"""
import ee
import config as cfg

# Sensor-specific "lit" thresholds for electrification classification.
# DMSP-OLS: digital number 0-63, typical lit threshold is DN > 3.
# VIIRS DNB: radiance in nW/cm2/sr, typical lit threshold is > 0.5.
DMSP_LIT_THRESHOLD = 3.0
VIIRS_LIT_THRESHOLD = 0.5


def _sensor_for_year(year):
    """Return sensor name for a given year."""
    return "DMSP-OLS" if year <= 2013 else "VIIRS-DNB"


def _lit_threshold_for_year(year):
    """Return sensor-appropriate lit threshold for a given year."""
    return DMSP_LIT_THRESHOLD if year <= 2013 else VIIRS_LIT_THRESHOLD


# ═══════════════════════════════════════════════════════════════════════════════
# Data Loading
# ═══════════════════════════════════════════════════════════════════════════════

def get_dmsp_annual(year, region):
    """Get DMSP-OLS stable lights composite for a given year."""
    col = (
        ee.ImageCollection(cfg.DMSP_OLS["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
    )
    return col.select(cfg.DMSP_OLS["band"]).median().clip(region)


def get_viirs_annual(year, region):
    """Get VIIRS DNB annual average radiance for a given year."""
    col = (
        ee.ImageCollection(cfg.VIIRS_DNB["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
    )
    return col.select(cfg.VIIRS_DNB["band"]).median().clip(region)


def get_nightlights(year, region):
    """Get nighttime lights for any year, auto-selecting DMSP or VIIRS."""
    if year <= 2013:
        return get_dmsp_annual(year, region)
    else:
        return get_viirs_annual(year, region)


# ═══════════════════════════════════════════════════════════════════════════════
# Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def compute_light_stats(year, region, scale=1000):
    """Compute mean, max, and total light intensity for a year."""
    lights = get_nightlights(year, region)
    band_name = cfg.DMSP_OLS["band"] if year <= 2013 else cfg.VIIRS_DNB["band"]

    stats = lights.reduceRegion(
        reducer=ee.Reducer.mean().combine(
            ee.Reducer.max(), sharedInputs=True
        ).combine(
            ee.Reducer.sum(), sharedInputs=True
        ),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    return {
        "year": year,
        "sensor": _sensor_for_year(year),
        "mean_radiance": stats.get(f"{band_name}_mean"),
        "max_radiance": stats.get(f"{band_name}_max"),
        "sum_radiance": stats.get(f"{band_name}_sum"),
    }


def compute_light_time_series(start_year, end_year, region, step=1, scale=1000):
    """Build a time series of light intensity statistics."""
    series = []
    for year in range(start_year, end_year + 1, step):
        try:
            stats = compute_light_stats(year, region, scale)
            series.append(stats)
        except Exception as e:
            print(f"  Nightlights {year} skipped: {e}")
    return series


def compute_light_change(year1, year2, region):
    """Compute absolute and relative change in nighttime lights."""
    lights1 = get_nightlights(year1, region)
    lights2 = get_nightlights(year2, region)
    diff = lights2.subtract(lights1).rename("light_change")
    # Relative change (avoid divide-by-zero)
    relative = diff.divide(lights1.max(ee.Image.constant(0.01))).rename("light_change_pct")
    return diff.addBands(relative)


def classify_electrification(year, region, threshold=None):
    """
    Binary electrification map: lit (radiance > threshold) vs unlit.
    If threshold is None, uses sensor-appropriate default:
      DMSP-OLS (<=2013): DN > 3.0
      VIIRS-DNB (2014+): radiance > 0.5 nW/cm2/sr
    Returns {mask, lit_area_km2, year, sensor}.
    """
    if threshold is None:
        threshold = _lit_threshold_for_year(year)
    lights = get_nightlights(year, region)
    band_name = cfg.DMSP_OLS["band"] if year <= 2013 else cfg.VIIRS_DNB["band"]
    lit = lights.select(band_name).gt(threshold).rename("electrified")

    lit_area = lit.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=1000,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    return {
        "mask": lit,
        "lit_area_km2": ee.Number(lit_area.get("electrified")).divide(1e6),
        "year": year,
        "sensor": _sensor_for_year(year),
    }


def compute_light_per_capita(year, region, scale=1000):
    """
    Light intensity per capita using WorldPop population data.
    Only available for years with WorldPop data (2000–2020).
    """
    lights = get_nightlights(year, region)
    pop_year = min(max(year, 2000), 2020)
    pop = (
        ee.ImageCollection(cfg.WORLDPOP["collection"])
        .filterDate(f"{pop_year}-01-01", f"{pop_year}-12-31")
        .filterBounds(region)
        .select(cfg.WORLDPOP["band"])
        .median()
        .clip(region)
    )
    # Avoid division by zero
    pop_safe = pop.max(ee.Image.constant(1))
    band_name = cfg.DMSP_OLS["band"] if year <= 2013 else cfg.VIIRS_DNB["band"]
    per_capita = lights.select(band_name).divide(pop_safe).rename("light_per_capita")
    return per_capita


def compute_urban_center_lights(year, region=None, scale=500):
    """Compute light stats for each major urban center."""
    results = []
    for city, info in cfg.URBAN_CENTERS.items():
        point = ee.Geometry.Point([info["lon"], info["lat"]])
        city_region = point.buffer(info["radius"])
        try:
            stats = compute_light_stats(year, city_region, scale)
            stats["city"] = city
            results.append(stats)
        except Exception as e:
            print(f"  {city} lights skipped: {e}")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_nightlights_analysis(region, start_year=1992, end_year=2024, step=2):
    """
    Full nighttime lights analysis pipeline.
    Returns dict with time_series, change maps, electrification data, and city stats.
    """
    print("\n  Computing nighttime lights time series...")
    time_series = compute_light_time_series(start_year, end_year, region, step)

    print("  Computing light change maps...")
    changes = {}
    change_pairs = [(1992, 2013), (2014, 2024)]
    for y1, y2 in change_pairs:
        if y1 >= start_year and y2 <= end_year:
            try:
                changes[f"{y1}_to_{y2}"] = compute_light_change(y1, y2, region)
            except Exception as e:
                print(f"    Change {y1}-{y2} skipped: {e}")

    print("  Computing electrification status...")
    electrification = {}
    for year in [2000, 2010, 2020, 2024]:
        if start_year <= year <= end_year:
            try:
                electrification[year] = classify_electrification(year, region)
            except Exception as e:
                print(f"    Electrification {year} skipped: {e}")

    print("  Computing urban center light stats...")
    city_stats = {}
    for year in [2000, 2010, 2020, 2024]:
        if start_year <= year <= end_year:
            try:
                city_stats[year] = compute_urban_center_lights(year)
            except Exception as e:
                print(f"    City stats {year} skipped: {e}")

    return {
        "time_series": time_series,
        "changes": changes,
        "electrification": electrification,
        "city_stats": city_stats,
    }
