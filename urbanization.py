"""
Urbanization analysis – built-up area tracking, urban sprawl detection,
settlement classification using GHSL, Dynamic World, and Landsat-derived indices.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Data Loading
# ═══════════════════════════════════════════════════════════════════════════════

def get_ghsl_built(year, region):
    """
    Get GHSL built-up surface area for a specific epoch.
    Available epochs: 1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025, 2030.
    """
    # Snap to nearest available epoch
    epochs = [1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025, 2030]
    epoch = min(epochs, key=lambda x: abs(x - year))
    image_id = f"JRC/GHSL/P2023A/GHS_BUILT_S/{epoch}"
    return ee.Image(image_id).select(cfg.GHSL_BUILT["band"]).clip(region)


def get_ghsl_smod(year, region):
    """
    Get GHSL Settlement Model (degree of urbanization).
    Classes: 10=water, 11=very_low, 12=low, 13=rural, 21=suburban,
             22=semi_dense_urban, 23=dense_urban, 30=urban_centre.
    """
    epochs = [1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025, 2030]
    epoch = min(epochs, key=lambda x: abs(x - year))
    image_id = f"JRC/GHSL/P2023A/GHS_SMOD/{epoch}"
    return ee.Image(image_id).select(cfg.GHSL_SMOD["band"]).clip(region)


def get_ghsl_pop(year, region):
    """Get GHSL population grid for a specific epoch."""
    epochs = [1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025, 2030]
    epoch = min(epochs, key=lambda x: abs(x - year))
    image_id = f"JRC/GHSL/P2023A/GHS_POP/{epoch}"
    return ee.Image(image_id).select(cfg.GHSL_POP["band"]).clip(region)


def compute_ndbi(image):
    """Normalized Difference Built-Up Index = (SWIR1 - NIR) / (SWIR1 + NIR)."""
    return image.normalizedDifference(["swir1", "nir"]).rename("ndbi")


def compute_ui(image):
    """Urban Index = (SWIR2 - NIR) / (SWIR2 + NIR)."""
    return image.normalizedDifference(["swir2", "nir"]).rename("ui")


def compute_bui(image):
    """Built-Up Index = NDBI - NDVI (positive = built-up dominant)."""
    ndbi = compute_ndbi(image)
    ndvi = image.normalizedDifference(["nir", "red"]).rename("ndvi")
    return ndbi.subtract(ndvi).rename("bui")


# ═══════════════════════════════════════════════════════════════════════════════
# Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def compute_builtup_area(year, region, scale=300 if cfg.SCOPE == "national" else 100):
    """Compute total built-up area (km2) from GHSL for a year."""
    built = get_ghsl_built(year, region)
    # GHSL built_surface is in m2 per pixel; sum and convert to km2
    stats = built.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    return {
        "year": year,
        "built_area_km2": ee.Number(stats.get(cfg.GHSL_BUILT["band"])).divide(1e6),
    }


def compute_builtup_timeseries(region, scale=100):
    """Track built-up area growth over GHSL epochs."""
    epochs = [1975, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020]
    series = []
    for year in epochs:
        try:
            stats = compute_builtup_area(year, region, scale)
            series.append(stats)
        except Exception as e:
            print(f"  Built-up {year} skipped: {e}")
    return series


def compute_urbanization_rate(year1, year2, region, scale=300 if cfg.SCOPE == "national" else 100):
    """Compute annual urbanization rate between two epochs."""
    built1 = get_ghsl_built(year1, region)
    built2 = get_ghsl_built(year2, region)

    diff = built2.subtract(built1).rename("built_change")

    sum1 = built1.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    sum2 = built2.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )

    band = cfg.GHSL_BUILT["band"]
    total_change = ee.Number(sum2.get(band)).subtract(ee.Number(sum1.get(band)))
    years = year2 - year1
    annual_rate = total_change.divide(1e6).divide(years)

    return {
        "period": f"{year1}-{year2}",
        "change_image": diff,
        "total_change_km2": total_change.divide(1e6),
        "annual_rate_km2": annual_rate,
    }


def classify_urban_expansion(year1, year2, region):
    """
    Map areas of urban expansion between two GHSL epochs.
    Returns: new_urban mask (built in year2 but not in year1).
    """
    built1 = get_ghsl_built(year1, region)
    built2 = get_ghsl_built(year2, region)

    # Consider pixels with > 0 m2 built-up as urban
    urban1 = built1.gt(0)
    urban2 = built2.gt(0)
    new_urban = urban2.And(urban1.Not()).rename("new_urban")
    lost_urban = urban1.And(urban2.Not()).rename("lost_urban")

    return {"new_urban": new_urban, "lost_urban": lost_urban}


def compute_settlement_classification(year, region, scale=1000):
    """
    Classify region into settlement types using GHSL SMOD.
    Returns area per settlement class.
    """
    smod = get_ghsl_smod(year, region)
    classes = {
        10: "Water", 11: "Very Low Density", 12: "Low Density Rural",
        13: "Rural Cluster", 21: "Suburban", 22: "Semi-Dense Urban",
        23: "Dense Urban", 30: "Urban Centre",
    }
    results = []
    for val, name in classes.items():
        mask = smod.eq(val)
        area = mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(), geometry=region,
            scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
        )
        results.append({
            "class_value": val,
            "class_name": name,
            "area_km2": ee.Number(area.get(cfg.GHSL_SMOD["band"])).divide(1e6),
        })
    return results


def compute_urban_center_growth(city_name, scale=100):
    """Track built-up area growth for a specific urban center."""
    if city_name not in cfg.URBAN_CENTERS:
        raise ValueError(f"Unknown city: {city_name}")
    info = cfg.URBAN_CENTERS[city_name]
    center = ee.Geometry.Point([info["lon"], info["lat"]])
    city_region = center.buffer(info["radius"])

    return compute_builtup_timeseries(city_region, scale)


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_urbanization_analysis(region):
    """Full urbanization analysis pipeline."""
    results = {}

    print("\n  Computing built-up area time series (GHSL 1975–2020)...")
    results["builtup_timeseries"] = compute_builtup_timeseries(region)

    print("  Computing urbanization rates by period...")
    rate_periods = [(1985, 2000), (2000, 2010), (2010, 2020)]
    results["urbanization_rates"] = []
    for y1, y2 in rate_periods:
        try:
            rate = compute_urbanization_rate(y1, y2, region)
            results["urbanization_rates"].append(rate)
        except Exception as e:
            print(f"    Rate {y1}-{y2} skipped: {e}")

    print("  Mapping urban expansion 1990–2020...")
    try:
        results["expansion_1990_2020"] = classify_urban_expansion(1990, 2020, region)
    except Exception as e:
        print(f"    Expansion mapping skipped: {e}")

    print("  Computing settlement classification 2020...")
    try:
        results["settlement_2020"] = compute_settlement_classification(2020, region)
    except Exception as e:
        print(f"    Settlement classification skipped: {e}")

    print("  Computing urban center growth...")
    results["city_growth"] = {}
    for city in cfg.URBAN_CENTERS:
        try:
            results["city_growth"][city] = compute_urban_center_growth(city)
        except Exception as e:
            print(f"    {city} growth skipped: {e}")

    return results
