"""
Infrastructure and construction analysis – built-up change detection,
road density estimation, economic zone growth, and construction activity
tracking using GHSL, Dynamic World, and spectral indices.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Construction Change Detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_construction_change(year1, year2, region):
    """
    Detect new construction between two years using Dynamic World.
    Construction = transition to 'built' class (class 6).
    """
    from land_cover import get_dynamic_world
    dw1 = get_dynamic_world(f"{year1}-01-01", f"{year1}-12-31", region)
    dw2 = get_dynamic_world(f"{year2}-01-01", f"{year2}-12-31", region)

    # New construction: not built in year1, built in year2
    built_class = 6  # Dynamic World built class
    was_not_built = dw1.neq(built_class)
    is_now_built = dw2.eq(built_class)
    new_construction = was_not_built.And(is_now_built).rename("new_construction")

    # Demolished/cleared: was built, now not
    was_built = dw1.eq(built_class)
    is_not_built = dw2.neq(built_class)
    demolished = was_built.And(is_not_built).rename("demolished")

    return {
        "new_construction": new_construction,
        "demolished": demolished,
        "built_year1": dw1.eq(built_class).rename("built"),
        "built_year2": dw2.eq(built_class).rename("built"),
    }


def compute_construction_area(year1, year2, region, scale=100):
    """Compute area of new construction and demolition."""
    change = detect_construction_change(year1, year2, region)

    new_area = change["new_construction"].multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    demo_area = change["demolished"].multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return {
        "period": f"{year1}-{year2}",
        "new_construction_km2": ee.Number(new_area.get("new_construction")).divide(1e6),
        "demolished_km2": ee.Number(demo_area.get("demolished")).divide(1e6),
    }


def detect_construction_spectral(composite1, composite2, region):
    """
    Detect construction using spectral change (NDBI increase + NDVI decrease).
    Works with Landsat/Sentinel composites.
    """
    from urbanization import compute_ndbi
    from vegetation import compute_ndvi

    ndbi1 = compute_ndbi(composite1)
    ndbi2 = compute_ndbi(composite2)
    ndvi1 = compute_ndvi(composite1)
    ndvi2 = compute_ndvi(composite2)

    # Construction indicator: NDBI increased AND NDVI decreased
    ndbi_increase = ndbi2.subtract(ndbi1).gt(0.1)
    ndvi_decrease = ndvi1.subtract(ndvi2).gt(0.1)
    construction = ndbi_increase.And(ndvi_decrease).rename("construction_spectral")

    return construction


# ═══════════════════════════════════════════════════════════════════════════════
# Economic Zone Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_economic_zone(zone_name, scale=100):
    """
    Analyze built-up growth within a specific economic zone.
    Returns time series of built-up area.
    """
    if zone_name not in cfg.ECONOMIC_ZONES:
        raise ValueError(f"Unknown economic zone: {zone_name}")

    info = cfg.ECONOMIC_ZONES[zone_name]
    center = ee.Geometry.Point([info["lon"], info["lat"]])
    zone_region = center.buffer(info["radius"])

    from urbanization import compute_builtup_timeseries
    return compute_builtup_timeseries(zone_region, scale)


def analyze_all_economic_zones(scale=100):
    """Analyze built-up growth for all economic zones."""
    results = {}
    for zone_name in cfg.ECONOMIC_ZONES:
        print(f"    {zone_name}...")
        try:
            results[zone_name] = analyze_economic_zone(zone_name, scale)
        except Exception as e:
            print(f"      Skipped: {e}")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Road / Infrastructure Density
# ═══════════════════════════════════════════════════════════════════════════════

def estimate_road_density(region, year=2021, scale=100):
    """
    Estimate road/infrastructure density using built-up area and NDBI.
    Higher NDBI with linear features indicates road corridors.
    Uses GHSL built-up surface as a proxy for infrastructure density.
    """
    from urbanization import get_ghsl_built
    built = get_ghsl_built(year, region)

    # Compute built-up density per km2
    density = built.reduceNeighborhood(
        reducer=ee.Reducer.sum(),
        kernel=ee.Kernel.circle(1000, "meters"),
    ).divide(1e6).rename("infrastructure_density_km2")

    return density


def compute_connectivity_index(region, year=2020, scale=1000):
    """
    Compute a simple connectivity/accessibility index based on
    distance to nearest built-up area and nighttime lights.
    High value = well connected, low = remote.
    """
    from urbanization import get_ghsl_built
    from nightlights import get_nightlights

    built = get_ghsl_built(year, region)
    urban_mask = built.gt(100)  # >100m2 built-up

    # Distance to nearest urban pixel (meters)
    distance = urban_mask.fastDistanceTransform().sqrt().multiply(scale).rename("dist_to_urban")

    # Nightlight intensity
    lights = get_nightlights(year, region)
    band_name = lights.bandNames().getInfo()[0]
    light_norm = lights.select(band_name).unitScale(0, 63).clamp(0, 1)

    # Connectivity = inverse distance * light intensity
    dist_norm = distance.unitScale(0, 50000).clamp(0, 1)
    connectivity = ee.Image.constant(1).subtract(dist_norm).multiply(
        light_norm.add(0.1)
    ).clamp(0, 1).rename("connectivity")

    return connectivity


# ═══════════════════════════════════════════════════════════════════════════════
# Construction Activity Monitoring
# ═══════════════════════════════════════════════════════════════════════════════

def compute_construction_timeseries(region, start_year=2016, end_year=2024, scale=100):
    """Track annual new construction area using Dynamic World."""
    series = []
    for year in range(start_year + 1, end_year + 1):
        try:
            stats = compute_construction_area(year - 1, year, region, scale)
            series.append(stats)
        except Exception as e:
            print(f"  Construction {year-1}-{year} skipped: {e}")
    return series


def identify_construction_hotspots(year1, year2, region, scale=100):
    """
    Identify areas with highest construction density.
    Returns construction density (count/km2) and hotspot mask.
    """
    change = detect_construction_change(year1, year2, region)
    construction = change["new_construction"]

    # Kernel density estimation
    density = construction.reduceNeighborhood(
        reducer=ee.Reducer.sum(),
        kernel=ee.Kernel.circle(2000, "meters"),
    ).rename("construction_density")

    # Hotspot: density above 75th percentile
    threshold = density.reduceRegion(
        reducer=ee.Reducer.percentile([75]),
        geometry=region, scale=scale,
        maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    thresh_val = ee.Number(threshold.get("construction_density_p75"))
    hotspots = density.gte(thresh_val).rename("construction_hotspot")

    return {"density": density, "hotspots": hotspots, "threshold": thresh_val}


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_infrastructure_analysis(region):
    """Full infrastructure and construction analysis pipeline."""
    results = {}

    print("\n  Detecting construction change 2018–2024 (Dynamic World)...")
    try:
        results["construction_2018_2024"] = detect_construction_change(2018, 2024, region)
        results["construction_area"] = compute_construction_area(2018, 2024, region)
    except Exception as e:
        print(f"    Construction detection skipped: {e}")

    print("  Computing construction time series (2016–2024)...")
    results["construction_timeseries"] = compute_construction_timeseries(region)

    print("  Identifying construction hotspots...")
    try:
        results["hotspots"] = identify_construction_hotspots(2018, 2024, region)
    except Exception as e:
        print(f"    Hotspot detection skipped: {e}")

    print("  Analyzing economic zone growth...")
    results["economic_zones"] = analyze_all_economic_zones()

    print("  Estimating infrastructure density...")
    try:
        results["infra_density"] = estimate_road_density(region)
    except Exception as e:
        print(f"    Infrastructure density skipped: {e}")

    print("  Computing connectivity index...")
    try:
        results["connectivity"] = compute_connectivity_index(region)
    except Exception as e:
        print(f"    Connectivity index skipped: {e}")

    return results
