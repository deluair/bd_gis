"""
Transportation and connectivity gap analysis -- nightlights + population density
to identify areas with low road access relative to economic and population need.

Datasets:
- VIIRS DNB nightlights (proxy for economic activity)
- WorldPop population density
- GHSL SMOD settlement classification (urban/peri-urban/rural)
- GHSL Built-Up Surface (infrastructure density proxy)
- FAO GAUL admin boundaries (divisions for per-division scoring)
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Settlement Classification
# ═══════════════════════════════════════════════════════════════════════════════

def compute_settlement_density(year, region):
    """
    Classify settlement type from GHSL SMOD: urban / peri-urban / rural / very-low.

    GHSL SMOD class codes:
        10  = water body
        11  = very low density rural
        12  = low density rural
        13  = rural cluster
        21  = suburban / peri-urban
        22  = semi-dense urban
        23  = dense urban
        30  = urban centre

    Returns a dict of ee.Image masks and area estimates per class.
    """
    smod_year = _snap_smod_year(year)
    smod = (
        ee.ImageCollection(cfg.GHSL_SMOD["collection"])
        .filter(ee.Filter.calendarRange(smod_year, smod_year, "year"))
        .first()
        .select(cfg.GHSL_SMOD["band"])
        .clip(region)
    )

    urban = smod.gte(22).rename("urban")                      # 22, 23, 30
    peri_urban = smod.eq(21).rename("peri_urban")             # 21
    rural_cluster = smod.eq(13).rename("rural_cluster")       # 13
    low_density = smod.lte(12).And(smod.gte(11)).rename("low_density_rural")  # 11, 12

    scale = cfg.GHSL_SMOD["scale"]

    def _area_km2(mask):
        return mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=region,
            scale=scale,
            maxPixels=cfg.MAX_PIXELS,
            bestEffort=True,
        )

    return {
        "year": smod_year,
        "smod": smod,
        "urban_mask": urban,
        "peri_urban_mask": peri_urban,
        "rural_cluster_mask": rural_cluster,
        "low_density_mask": low_density,
        "urban_area_km2": ee.Number(_area_km2(urban).values().get(0)).divide(1e6),
        "peri_urban_area_km2": ee.Number(_area_km2(peri_urban).values().get(0)).divide(1e6),
        "rural_cluster_area_km2": ee.Number(_area_km2(rural_cluster).values().get(0)).divide(1e6),
        "low_density_area_km2": ee.Number(_area_km2(low_density).values().get(0)).divide(1e6),
    }


def _snap_smod_year(year):
    """GHSL SMOD is available in 5-year epochs: 1975, 1980, ..., 2020, 2025."""
    epochs = [1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025]
    return min(epochs, key=lambda e: abs(e - year))


# ═══════════════════════════════════════════════════════════════════════════════
# Accessibility Index
# ═══════════════════════════════════════════════════════════════════════════════

def compute_accessibility_index(region, year=2020, scale=1000):
    """
    Accessibility index = nightlights * population_density / (dist_to_urban + epsilon).

    High value = area with significant population and economic activity that is
    relatively close to an urban centre -- a baseline for what connectivity
    should look like.  Low value in a densely populated area = connectivity gap.

    Returns an ee.Image (0--1 normalised).
    """
    # Nightlights
    lights = _get_viirs(year, region)
    light_norm = lights.unitScale(0, 50).clamp(0, 1)

    # Population density (WorldPop, capped at 2020)
    pop = _get_worldpop(year, region)
    pop_norm = pop.unitScale(0, 5000).clamp(0, 1)

    # Distance to nearest urban pixel from GHSL SMOD
    smod_year = _snap_smod_year(year)
    smod = (
        ee.ImageCollection(cfg.GHSL_SMOD["collection"])
        .filter(ee.Filter.calendarRange(smod_year, smod_year, "year"))
        .first()
        .select(cfg.GHSL_SMOD["band"])
        .clip(region)
    )
    urban_mask = smod.gte(22)
    dist_to_urban = (
        urban_mask.fastDistanceTransform()
        .sqrt()
        .multiply(scale)   # pixels to meters
        .rename("dist_to_urban_m")
    )
    dist_norm = dist_to_urban.unitScale(0, 100000).clamp(0, 1)
    proximity = ee.Image.constant(1).subtract(dist_norm)  # 1 = near urban, 0 = far

    # Index: weighted combination
    accessibility = (
        light_norm.multiply(0.4)
        .add(pop_norm.multiply(0.4))
        .add(proximity.multiply(0.2))
        .clamp(0, 1)
        .rename("accessibility_index")
    )
    return accessibility


# ═══════════════════════════════════════════════════════════════════════════════
# Underserved Area Detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_underserved_areas(region, year=2020, scale=1000):
    """
    Identify underserved areas: high population density + low nightlights.

    These are pixels where people live but economic activity / electrification
    is low -- a strong signal for lack of road / infrastructure access.

    Returns:
        underserved_mask  -- binary mask (1 = underserved)
        underserved_index -- continuous score 0--1 (higher = more underserved)
        population_at_risk -- estimated population in underserved areas
    """
    lights = _get_viirs(year, region)
    light_norm = lights.unitScale(0, 50).clamp(0, 1)
    darkness = ee.Image.constant(1).subtract(light_norm)  # high = dark

    pop = _get_worldpop(year, region)
    pop_norm = pop.unitScale(0, 5000).clamp(0, 1)

    # Underserved score = population need * darkness
    underserved_index = pop_norm.multiply(darkness).clamp(0, 1).rename("underserved_index")

    # Threshold at 60th percentile within region
    threshold = underserved_index.reduceRegion(
        reducer=ee.Reducer.percentile([60]),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    thresh_val = ee.Number(threshold.get("underserved_index_p60"))
    underserved_mask = underserved_index.gte(thresh_val).rename("underserved")

    # Population at risk (sum of population in underserved pixels)
    pop_at_risk = pop.updateMask(underserved_mask).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )

    return {
        "underserved_index": underserved_index,
        "underserved_mask": underserved_mask,
        "threshold": thresh_val,
        "population_at_risk": ee.Number(pop_at_risk.get("population")),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Connectivity Gap per Division
# ═══════════════════════════════════════════════════════════════════════════════

def compute_connectivity_gap(region, year=2020, scale=1000):
    """
    Per-division connectivity gap score.

    Gap score = mean(underserved_index) within each division.
    Divisions with high gap scores are priority targets for road investment.

    Returns an ee.FeatureCollection with division-level gap scores.
    """
    underserved = detect_underserved_areas(region, year, scale)
    gap_img = underserved["underserved_index"]

    divisions = (
        ee.FeatureCollection(cfg.ADMIN_L1)
        .filter(ee.Filter.eq("ADM0_NAME", cfg.COUNTRY_NAME))
    )

    gap_fc = gap_img.reduceRegions(
        collection=divisions,
        reducer=ee.Reducer.mean().combine(
            ee.Reducer.percentile([75]), sharedInputs=True
        ),
        scale=scale,
        crs="EPSG:4326",
    )
    return gap_fc


# ═══════════════════════════════════════════════════════════════════════════════
# Market Access
# ═══════════════════════════════════════════════════════════════════════════════

def compute_market_access(region, year=2020, scale=1000):
    """
    Market access proxy using nightlights gradient magnitude.

    Strong nightlights gradients near populated areas indicate sharp transitions
    between lit (accessible) and dark (inaccessible) zones -- i.e., the edge of
    road/market reach.  Areas with high population but low gradient magnitude
    are isolated from markets.

    Returns:
        gradient_magnitude  -- ee.Image, rate of change in nightlights
        market_access_index -- ee.Image, 0--1 (higher = better access)
    """
    lights = _get_viirs(year, region)
    light_smooth = lights.focal_mean(radius=3000, kernelType="gaussian", units="meters")

    # Sobel gradient (approximated with finite differences via convolveKernel)
    dx = ee.Kernel.fixed(3, 3, [
        [-1, 0, 1],
        [-2, 0, 2],
        [-1, 0, 1],
    ], -1, -1)
    dy = ee.Kernel.fixed(3, 3, [
        [1,  2,  1],
        [0,  0,  0],
        [-1, -2, -1],
    ], -1, -1)
    gx = light_smooth.convolve(dx)
    gy = light_smooth.convolve(dy)
    gradient_magnitude = (
        gx.multiply(gx).add(gy.multiply(gy)).sqrt()
        .rename("light_gradient")
    )

    # Market access: inverse distance to bright pixels (nightlights > threshold)
    bright_mask = lights.gt(5)
    dist_to_market = (
        bright_mask.fastDistanceTransform()
        .sqrt()
        .multiply(scale)
        .rename("dist_to_market_m")
    )
    market_access_index = (
        dist_to_market.unitScale(0, 80000).clamp(0, 1)
        .multiply(-1).add(1)   # invert: near = high access
        .rename("market_access_index")
    )

    return {
        "gradient_magnitude": gradient_magnitude,
        "market_access_index": market_access_index,
        "dist_to_market": dist_to_market,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Full Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_transportation_analysis(region):
    """Full transportation and connectivity gap analysis pipeline."""
    results = {}

    print("\n  Computing settlement density (GHSL SMOD 2020)...")
    try:
        results["settlement_2020"] = compute_settlement_density(2020, region)
    except Exception as e:
        print(f"    Settlement density skipped: {e}")

    print("  Computing accessibility index...")
    try:
        results["accessibility"] = compute_accessibility_index(region)
    except Exception as e:
        print(f"    Accessibility index skipped: {e}")

    print("  Detecting underserved areas...")
    try:
        results["underserved"] = detect_underserved_areas(region)
    except Exception as e:
        print(f"    Underserved detection skipped: {e}")

    print("  Computing per-division connectivity gap scores...")
    try:
        results["connectivity_gap_fc"] = compute_connectivity_gap(region)
    except Exception as e:
        print(f"    Connectivity gap skipped: {e}")

    print("  Computing market access proxy...")
    try:
        results["market_access"] = compute_market_access(region)
    except Exception as e:
        print(f"    Market access skipped: {e}")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Internal Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _get_viirs(year, region):
    """Annual median VIIRS DNB radiance, clipped to region."""
    viirs_year = min(max(year, cfg.VIIRS_DNB["years"][0]), cfg.VIIRS_DNB["years"][1])
    return (
        ee.ImageCollection(cfg.VIIRS_DNB["collection"])
        .filterDate(f"{viirs_year}-01-01", f"{viirs_year}-12-31")
        .filterBounds(region)
        .select(cfg.VIIRS_DNB["band"])
        .median()
        .clip(region)
        .rename("avg_rad")
    )


def _get_worldpop(year, region):
    """WorldPop population density, clamped to available years 2000--2020."""
    pop_year = min(max(year, cfg.WORLDPOP["years"][0]), cfg.WORLDPOP["years"][1])
    return (
        ee.ImageCollection(cfg.WORLDPOP["collection"])
        .filterDate(f"{pop_year}-01-01", f"{pop_year}-12-31")
        .filterBounds(region)
        .select(cfg.WORLDPOP["band"])
        .median()
        .clip(region)
        .rename("population")
    )
