"""
Informal settlement / slum detection – multi-indicator spatial mapping of
slum-like conditions using texture analysis, building density, vegetation
deficit, nightlight patterns, and morphological settlement indicators.

Key indicators for slum identification:
- High built-up density with small building footprints
- Low vegetation cover (NDVI deficit)
- High population density relative to built-up quality
- Low/irregular nighttime light intensity per capita
- Proximity to water bodies, railways, industrial areas
- High LST (lack of green space / dense materials)
"""

# RESOLUTION CAVEAT: Landsat at 30m cannot resolve individual slum structures
# (which require sub-5m imagery). This module detects "dense urban / potentially
# informal settlement" areas as a proxy. Outputs should be labeled as proxy
# indices, not definitive slum maps. See Kuffer et al. 2016 for resolution
# requirements in slum mapping.
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Known Informal Settlement Areas (for calibration)
# ═══════════════════════════════════════════════════════════════════════════════

KNOWN_SLUM_AREAS = {
    "Korail (Dhaka)":         {"lat": 23.79, "lon": 90.41, "radius": 1000},
    "Kamrangirchar (Dhaka)":  {"lat": 23.72, "lon": 90.38, "radius": 1500},
    "Mirpur Slums (Dhaka)":   {"lat": 23.82, "lon": 90.36, "radius": 2000},
    "Mohakhali Slum (Dhaka)": {"lat": 23.78, "lon": 90.40, "radius": 800},
    "Bhashantek (Dhaka)":     {"lat": 23.81, "lon": 90.38, "radius": 1000},
    "Lalbagh Slums (Dhaka)":  {"lat": 23.72, "lon": 90.39, "radius": 1200},
    "Gabtoli Slum (Dhaka)":   {"lat": 23.78, "lon": 90.34, "radius": 1000},
    "Chittagong Port Slums":  {"lat": 22.33, "lon": 91.80, "radius": 1500},
    "Khulna Slums":           {"lat": 22.82, "lon": 89.55, "radius": 1500},
    "Kazir Bazar (Sylhet)":   {"lat": 24.89, "lon": 91.87, "radius": 1000},
    "Padma Embankment (Rajshahi)": {"lat": 24.37, "lon": 88.60, "radius": 1200},
    "Rail-side Slums (Rangpur)":   {"lat": 25.74, "lon": 89.25, "radius": 1000},
}


# ═══════════════════════════════════════════════════════════════════════════════
# Individual Indicators
# ═══════════════════════════════════════════════════════════════════════════════

def compute_building_density(year, region, scale=100):
    """
    High building density indicator from GHSL.
    Slums have very dense, irregular built-up patterns.
    """
    from urbanization import get_ghsl_built
    built = get_ghsl_built(year, region)
    # Neighborhood density using 500m kernel
    density = built.reduceNeighborhood(
        reducer=ee.Reducer.mean(),
        kernel=ee.Kernel.circle(500, "meters"),
    ).rename("building_density")
    return density


def compute_vegetation_deficit(year, region, scale=100):
    """
    Low vegetation = likely informal settlement.
    Uses NDVI from Landsat/Sentinel within urban areas.
    """
    from vegetation import get_modis_ndvi_annual
    ndvi = get_modis_ndvi_annual(year, region)
    # Invert: low NDVI = high deficit (0 to 1 scale)
    deficit = ee.Image.constant(1).subtract(
        ndvi.clamp(0, 0.6).divide(0.6)
    ).rename("veg_deficit")
    return deficit


def compute_texture_heterogeneity(year, region):
    """
    High spatial texture/heterogeneity indicates irregular slum structures.
    Uses GLCM entropy on Sentinel-2 or Landsat imagery.
    """
    from data_acquisition import get_seasonal_composite
    try:
        composite = get_seasonal_composite(year, "dry", "landsat", region)
    except Exception:
        return None

    # Compute texture on NIR band (most contrast)
    nir = composite.select("nir")
    # Scale to integer for GLCM
    nir_int = nir.multiply(10000).toInt()
    glcm = nir_int.glcmTexture(size=3)
    entropy = glcm.select("nir_ent").rename("texture_entropy")
    return entropy


def compute_lst_anomaly(year, region, scale=1000):
    """
    High land surface temperature relative to surroundings = dense built-up.
    Slums often have highest LST due to lack of green space and dense materials.
    """
    from climate import get_lst_annual
    lst = get_lst_annual(year, region, "day")

    # Compute local LST anomaly (deviation from neighborhood mean)
    local_mean = lst.reduceNeighborhood(
        reducer=ee.Reducer.mean(),
        kernel=ee.Kernel.circle(5000, "meters"),
    )
    anomaly = lst.subtract(local_mean).rename("lst_anomaly")
    return anomaly


def compute_population_density_indicator(year, region):
    """High population density relative to built-up area."""
    from poverty import get_population_density
    from urbanization import get_ghsl_built
    pop = get_population_density(year, region)
    built = get_ghsl_built(year, region)

    # pop = WorldPop people per 100m pixel (typically 0-250 in Dhaka)
    # built = GHSL m2 of built surface per 100m pixel (typically 0-10000)
    # Ratio = people per m2 of built surface (typically 0-0.1)
    # Normalization should use range appropriate to these units
    built_safe = built.max(ee.Image.constant(1))
    overcrowding = pop.divide(built_safe).unitScale(0, 0.1).clamp(0, 1).rename("overcrowding")
    return overcrowding


def compute_light_irregularity(year, region):
    """
    Low nighttime light per built-up area = poor infrastructure quality.
    Slums may have electricity but lower/irregular intensity.
    """
    from nightlights import get_nightlights, _sensor_scale_range
    from urbanization import get_ghsl_built

    lights = get_nightlights(year, region)
    built = get_ghsl_built(year, region)

    band_name = lights.bandNames().getInfo()[0]
    lo, hi = _sensor_scale_range(year)
    light_norm = lights.select(band_name).unitScale(lo, hi).clamp(0, 1)

    built_norm = built.unitScale(0, 10000).clamp(0, 1)
    built_safe = built_norm.max(ee.Image.constant(0.01))

    # Low light-to-built ratio = poor infrastructure
    light_deficit = ee.Image.constant(1).subtract(
        light_norm.divide(built_safe).clamp(0, 1)
    ).rename("light_deficit")
    return light_deficit


# ═══════════════════════════════════════════════════════════════════════════════
# Composite Slum Index
# ═══════════════════════════════════════════════════════════════════════════════

def compute_slum_index(year, region, scale=100):
    """
    Composite slum probability index (0–1, higher = more slum-like).

    Combines multiple indicators:
    1. High building density
    2. Low vegetation (NDVI deficit)
    3. High population overcrowding
    4. High land surface temperature
    5. Low light-to-built ratio

    Only applicable within urban/peri-urban areas.
    """
    indicators = []
    weights = []
    included_indicators = []

    # 1. Building density (normalized to 0-1)
    try:
        density = compute_building_density(year, region)
        density_norm = density.unitScale(0, 5000).clamp(0, 1).rename("density_norm")
        indicators.append(density_norm)
        included_indicators.append("building_density")
        weights.append(0.25)
    except Exception as e:
        print(f"  WARNING: building_density failed ({e}), excluded from composite")

    # 2. Vegetation deficit
    try:
        veg_def = compute_vegetation_deficit(year, region)
        indicators.append(veg_def)
        included_indicators.append("vegetation_deficit")
        weights.append(0.20)
    except Exception as e:
        print(f"  WARNING: vegetation_deficit failed ({e}), excluded from composite")

    # 3. Population overcrowding
    try:
        overcrowding = compute_population_density_indicator(year, region)
        indicators.append(overcrowding)
        included_indicators.append("overcrowding")
        weights.append(0.25)
    except Exception as e:
        print(f"  WARNING: overcrowding failed ({e}), excluded from composite")

    # 4. LST anomaly (high temp = slum-like)
    try:
        lst_anom = compute_lst_anomaly(year, region)
        lst_norm = lst_anom.unitScale(-5, 5).clamp(0, 1).rename("lst_norm")
        indicators.append(lst_norm)
        included_indicators.append("lst_anomaly")
        weights.append(0.15)
    except Exception as e:
        print(f"  WARNING: lst_anomaly failed ({e}), excluded from composite")

    # 5. Light infrastructure deficit
    try:
        light_def = compute_light_irregularity(year, region)
        indicators.append(light_def)
        included_indicators.append("light_deficit")
        weights.append(0.15)
    except Exception as e:
        print(f"  WARNING: light_deficit failed ({e}), excluded from composite")

    # NOTE: compute_texture_heterogeneity() is available but not included in
    # the composite due to Landsat 30m resolution limitations for texture-based
    # slum detection. Include when Sentinel-2 10m composites are used.

    if not indicators:
        return None

    # Weighted combination
    total_weight = sum(weights)
    slum_index = ee.Image.constant(0).rename("slum_index")
    for indicator, weight in zip(indicators, weights):
        slum_index = slum_index.add(indicator.multiply(weight / total_weight))

    # Mask to urban areas only (GHSL SMOD >= 21 = suburban or denser)
    try:
        from urbanization import get_ghsl_smod
        smod = get_ghsl_smod(year, region)
        urban_mask = smod.gte(21)
        slum_index = slum_index.updateMask(urban_mask)
    except Exception:
        pass

    print(f"  Slum index indicators included: {included_indicators}")
    slum_index = slum_index.set("indicators_included", included_indicators)
    return slum_index


def classify_slum_risk(slum_index):
    """
    Classify slum index into risk levels.
    1=Low, 2=Moderate, 3=High, 4=Very High risk.
    """
    classified = (
        ee.Image.constant(0).rename("slum_risk")
        .where(slum_index.lt(0.3), 1)
        .where(slum_index.gte(0.3).And(slum_index.lt(0.5)), 2)
        .where(slum_index.gte(0.5).And(slum_index.lt(0.7)), 3)
        .where(slum_index.gte(0.7), 4)
    )
    return classified.toInt()


# ═══════════════════════════════════════════════════════════════════════════════
# Slum Area Estimation
# ═══════════════════════════════════════════════════════════════════════════════

def estimate_slum_area(year, region, threshold=0.6, scale=100):
    """Estimate total area classified as slum-like (above threshold)."""
    slum_index = compute_slum_index(year, region)
    if slum_index is None:
        return None

    slum_mask = slum_index.gt(threshold).rename("slum")
    area = slum_mask.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "year": year,
        "slum_area_km2": ee.Number(area.get("slum")).divide(1e6),
        "threshold": threshold,
    }


def analyze_known_slum_areas(year, scale=30):
    """Compute slum index statistics for known informal settlement areas."""
    results = []
    for name, info in KNOWN_SLUM_AREAS.items():
        center = ee.Geometry.Point([info["lon"], info["lat"]])
        area = center.buffer(info["radius"])
        try:
            slum_index = compute_slum_index(year, area)
            if slum_index is None:
                continue
            stats = slum_index.reduceRegion(
                reducer=ee.Reducer.mean().combine(
                    ee.Reducer.max(), sharedInputs=True
                ),
                geometry=area, scale=scale,
                maxPixels=cfg.MAX_PIXELS, bestEffort=True,
            )
            results.append({
                "area": name,
                "mean_slum_index": stats.get("slum_index_mean"),
                "max_slum_index": stats.get("slum_index_max"),
            })
        except Exception as e:
            print(f"    {name} skipped: {e}")
    return results


def compute_slum_growth(year1, year2, region, threshold=0.6, scale=100):
    """Track slum expansion between two years."""
    idx1 = compute_slum_index(year1, region)
    idx2 = compute_slum_index(year2, region)
    if idx1 is None or idx2 is None:
        return None

    slum1 = idx1.gt(threshold)
    slum2 = idx2.gt(threshold)

    new_slum = slum2.And(slum1.Not()).rename("new_slum")
    cleared_slum = slum1.And(slum2.Not()).rename("cleared_slum")

    new_area = new_slum.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    cleared_area = cleared_slum.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "period": f"{year1}-{year2}",
        "new_slum_km2": ee.Number(new_area.get("new_slum")).divide(1e6),
        "cleared_slum_km2": ee.Number(cleared_area.get("cleared_slum")).divide(1e6),
        "new_slum_mask": new_slum,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_slum_analysis(region):
    """Full slum/informal settlement analysis pipeline."""
    results = {}

    print("\n  Computing slum probability index 2020...")
    try:
        results["slum_index_2020"] = compute_slum_index(2020, region)
        results["slum_risk_2020"] = classify_slum_risk(results["slum_index_2020"])
    except Exception as e:
        print(f"    Slum index skipped: {e}")

    print("  Estimating slum area...")
    try:
        results["slum_area_2020"] = estimate_slum_area(2020, region)
    except Exception as e:
        print(f"    Slum area skipped: {e}")

    print("  Analyzing known slum areas...")
    try:
        results["known_slums"] = analyze_known_slum_areas(2020)
    except Exception as e:
        print(f"    Known slum analysis skipped: {e}")

    print("  Computing slum growth 2010–2020...")
    try:
        results["slum_growth"] = compute_slum_growth(2010, 2020, region)
    except Exception as e:
        print(f"    Slum growth skipped: {e}")

    print("  Computing slum area time series...")
    results["slum_timeseries"] = []
    for year in [2005, 2010, 2015, 2020]:
        try:
            sa = estimate_slum_area(year, region)
            if sa:
                results["slum_timeseries"].append(sa)
        except Exception as e:
            print(f"    Slum area {year} skipped: {e}")

    return results
