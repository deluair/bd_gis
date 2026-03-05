"""
Health risk proxy mapping – spatial disease risk estimation using
waterlogging, temperature extremes, population density, sanitation
proxies, and environmental hazard indicators.

Key health risks in Bangladesh:
- Waterborne diseases (cholera, diarrhea): linked to flooding, poor sanitation
- Dengue/malaria: linked to stagnant water + warm temperature
- Heat stress: linked to urban heat islands, high LST
- Respiratory: linked to air pollution (brick kilns, traffic)
- Arsenic exposure: linked to groundwater in specific geological zones
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Arsenic Risk Zones
# ═══════════════════════════════════════════════════════════════════════════════

# Known high-arsenic groundwater zones in Bangladesh
ARSENIC_HOTSPOTS = {
    "Chandpur":    {"lat": 23.23, "lon": 90.65, "radius": 20000},
    "Comilla":     {"lat": 23.46, "lon": 91.18, "radius": 20000},
    "Munshiganj":  {"lat": 23.54, "lon": 90.53, "radius": 15000},
    "Gopalganj":   {"lat": 23.01, "lon": 89.82, "radius": 15000},
    "Faridpur":    {"lat": 23.60, "lon": 89.84, "radius": 15000},
    "Madaripur":   {"lat": 23.16, "lon": 90.19, "radius": 15000},
    "Satkhira":    {"lat": 22.72, "lon": 89.07, "radius": 15000},
    "Jessore":     {"lat": 23.17, "lon": 89.21, "radius": 15000},
}


# ═══════════════════════════════════════════════════════════════════════════════
# Individual Risk Indicators
# ═══════════════════════════════════════════════════════════════════════════════

def compute_waterlogging_risk(year, region, scale=1000):
    """
    Waterlogging risk proxy: monsoon water extent relative to dry season.
    Higher ratio = more waterlogging = higher disease risk.
    """
    from data_acquisition import get_seasonal_composite
    from water_classification import classify_water, compute_water_area

    try:
        dry_comp = get_seasonal_composite(year, "dry", "landsat", region)
        monsoon_comp = get_seasonal_composite(year, "monsoon", "landsat", region)
        dry_water = classify_water(dry_comp, region=region)
        monsoon_water = classify_water(monsoon_comp, region=region)

        # Waterlogged = monsoon water but NOT permanent water
        waterlogged = monsoon_water.And(dry_water.Not()).rename("waterlogged")
        return waterlogged
    except Exception:
        return None


def compute_heat_stress(year, region, scale=1000):
    """
    Heat stress risk: number of extreme heat days (LST > 40C).
    Uses MODIS LST 8-day composites.
    """
    col = (
        ee.ImageCollection(cfg.MODIS_LST["collection"])
        .filterDate(f"{year}-03-01", f"{year}-10-31")
        .filterBounds(region)
        .select(cfg.MODIS_LST["day_band"])
    )

    def to_celsius(img):
        return img.multiply(cfg.MODIS_LST["scale_factor"]).add(cfg.MODIS_LST["kelvin_offset"])

    celsius_col = col.map(to_celsius)
    extreme_heat = celsius_col.map(lambda img: img.gt(40)).sum().rename("extreme_heat_days")
    return extreme_heat.clip(region)


def compute_mosquito_habitat(year, region):
    """
    Mosquito breeding habitat proxy: stagnant water + warm temperature.
    Uses LSWI (standing water) + LST (warm enough for breeding > 20C).
    """
    from data_acquisition import get_seasonal_composite
    try:
        composite = get_seasonal_composite(year, "monsoon", "landsat", region)
    except Exception:
        return None

    from crop_detection import compute_lswi
    lswi = compute_lswi(composite)
    # Standing water: LSWI > 0
    standing_water = lswi.gt(0).rename("standing_water")

    # Temperature suitable for mosquitoes (> 20C) — assumed true during monsoon
    # Use vegetation proxy: flooded vegetation = ideal habitat
    from land_cover import get_dynamic_world
    try:
        dw = get_dynamic_world(f"{year}-07-01", f"{year}-09-30", region)
        flooded_veg = dw.eq(3)  # flooded_vegetation class
        habitat = standing_water.Or(flooded_veg).rename("mosquito_habitat")
    except Exception:
        habitat = standing_water

    return habitat


def compute_air_pollution_risk(year, region, scale=5000):
    """
    Respiratory health risk from air pollution.
    Uses Sentinel-5P NO2 + Aerosol Index as proxies.
    """
    if year < 2019:
        return None

    from air_quality import get_no2, get_aerosol_index
    try:
        # Dry season (worst air quality: Nov-Mar)
        no2 = get_no2(f"{year}-11-01", f"{year + 1}-03-31", region)
        aer = get_aerosol_index(f"{year}-11-01", f"{year + 1}-03-31", region)

        # Normalize and combine
        no2_band = no2.bandNames().getInfo()[0]
        aer_band = aer.bandNames().getInfo()[0]
        no2_norm = no2.select(no2_band).unitScale(0, 0.0002).clamp(0, 1).rename("no2_risk")
        aer_norm = aer.select(aer_band).unitScale(-1, 3).clamp(0, 1).rename("aer_risk")

        pollution_risk = no2_norm.add(aer_norm).divide(2).rename("pollution_risk")
        return pollution_risk
    except Exception:
        return None


def map_arsenic_zones(region):
    """
    Map known arsenic-contaminated groundwater zones.
    Returns risk zones based on known hotspot locations.
    """
    zones = ee.Image.constant(0).rename("arsenic_risk").clip(region).toFloat()
    for name, info in ARSENIC_HOTSPOTS.items():
        center = ee.Geometry.Point([info["lon"], info["lat"]])
        hotspot = center.buffer(info["radius"])
        hotspot_mask = ee.Image.constant(1).clip(hotspot).unmask(0)
        zones = zones.max(hotspot_mask)
    return zones.rename("arsenic_risk")


# ═══════════════════════════════════════════════════════════════════════════════
# Composite Health Risk Index
# ═══════════════════════════════════════════════════════════════════════════════

def compute_health_risk_index(year, region, scale=1000):
    """
    Composite health risk index (0-1, higher = higher risk).

    Combines:
    1. Waterlogging risk (waterborne disease proxy)
    2. Heat stress (heat-related illness)
    3. Population density (exposure factor)
    4. Air pollution (respiratory risk)
    5. Vegetation deficit (environmental quality)
    """
    indicators = []
    weights = []

    # 1. Waterlogging
    waterlog = compute_waterlogging_risk(year, region)
    if waterlog is not None:
        indicators.append(waterlog.toFloat().rename("waterlog_risk"))
        weights.append(0.25)

    # 2. Heat stress
    try:
        heat = compute_heat_stress(year, region)
        heat_norm = heat.unitScale(0, 30).clamp(0, 1).rename("heat_risk")
        indicators.append(heat_norm)
        weights.append(0.20)
    except Exception:
        pass

    # 3. Population density (higher pop = higher exposure)
    try:
        from poverty import get_population_density
        pop = get_population_density(year, region)
        pop_norm = pop.unitScale(0, 10000).clamp(0, 1).rename("pop_risk")
        indicators.append(pop_norm)
        weights.append(0.20)
    except Exception:
        pass

    # 4. Air pollution (if available)
    pollution = compute_air_pollution_risk(year, region)
    if pollution is not None:
        indicators.append(pollution)
        weights.append(0.20)

    # 5. Vegetation deficit (environmental degradation)
    try:
        from vegetation import get_modis_ndvi_annual
        ndvi = get_modis_ndvi_annual(year, region)
        veg_risk = ee.Image.constant(1).subtract(
            ndvi.clamp(0, 0.6).divide(0.6)
        ).rename("veg_risk")
        indicators.append(veg_risk)
        weights.append(0.15)
    except Exception:
        pass

    if not indicators:
        return None

    total_weight = sum(weights)
    risk_index = ee.Image.constant(0).rename("health_risk")
    for ind, w in zip(indicators, weights):
        risk_index = risk_index.add(ind.multiply(w / total_weight))

    return risk_index


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_health_risk_analysis(region):
    """Full health risk analysis pipeline."""
    results = {}

    print("\n  Computing waterlogging risk 2023...")
    try:
        results["waterlogging"] = compute_waterlogging_risk(2023, region)
    except Exception as e:
        print(f"    Waterlogging skipped: {e}")

    print("  Computing heat stress 2023...")
    try:
        results["heat_stress"] = compute_heat_stress(2023, region)
    except Exception as e:
        print(f"    Heat stress skipped: {e}")

    print("  Mapping mosquito habitat 2023...")
    try:
        results["mosquito_habitat"] = compute_mosquito_habitat(2023, region)
    except Exception as e:
        print(f"    Mosquito habitat skipped: {e}")

    print("  Computing air pollution risk...")
    try:
        results["air_pollution_risk"] = compute_air_pollution_risk(2023, region)
    except Exception as e:
        print(f"    Air pollution risk skipped: {e}")

    print("  Mapping arsenic risk zones...")
    try:
        results["arsenic_zones"] = map_arsenic_zones(region)
    except Exception as e:
        print(f"    Arsenic zones skipped: {e}")

    print("  Computing composite health risk index...")
    try:
        results["health_risk_2023"] = compute_health_risk_index(2023, region)
    except Exception as e:
        print(f"    Health risk index skipped: {e}")

    print("  Computing health risk time series...")
    results["health_risk_timeseries"] = []
    for year in [2005, 2010, 2015, 2020, 2023]:
        try:
            idx = compute_health_risk_index(year, region)
            if idx is not None:
                stats = idx.reduceRegion(
                    reducer=ee.Reducer.mean(), geometry=region,
                    scale=1000, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
                )
                results["health_risk_timeseries"].append({
                    "year": year,
                    "mean_health_risk": stats.get("health_risk"),
                })
        except Exception as e:
            print(f"    Health risk {year} skipped: {e}")

    return results
