"""
Soil analysis – soil properties mapping, erosion risk assessment,
salinity intrusion detection, and agricultural suitability scoring
using OpenLandMap, DEM, rainfall, and vegetation data.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Soil Properties (OpenLandMap)
# ═══════════════════════════════════════════════════════════════════════════════

def get_soil_clay(region, depth="b0"):
    """Get clay content (% weight) at a given depth. Depths: b0, b10, b30, b60, b100, b200."""
    return ee.Image(cfg.OPENLANDMAP_SOIL["clay"]).select(depth).clip(region).rename("clay_pct")


def get_soil_sand(region, depth="b0"):
    """Get sand content (% weight)."""
    return ee.Image(cfg.OPENLANDMAP_SOIL["sand"]).select(depth).clip(region).rename("sand_pct")


def get_soil_organic_carbon(region, depth="b0"):
    """Get soil organic carbon (g/kg)."""
    return ee.Image(cfg.OPENLANDMAP_SOIL["organic_carbon"]).select(depth).clip(region).rename("soc_g_kg")


def get_soil_ph(region, depth="b0"):
    """Get soil pH (pH x 10)."""
    img = ee.Image(cfg.OPENLANDMAP_SOIL["ph"]).select(depth).clip(region)
    return img.divide(10).rename("soil_ph")


def get_soil_properties(region, depth="b0"):
    """Get all soil properties as a multi-band image."""
    clay = get_soil_clay(region, depth)
    sand = get_soil_sand(region, depth)
    soc = get_soil_organic_carbon(region, depth)
    ph = get_soil_ph(region, depth)
    return clay.addBands([sand, soc, ph])


def compute_soil_stats(region, depth="b0", scale=250):
    """Compute regional soil property statistics."""
    props = get_soil_properties(region, depth)
    stats = props.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=region, scale=scale,
        maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# Erosion Risk (RUSLE-inspired)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_slope(region):
    """Compute slope in degrees from SRTM DEM."""
    dem = ee.Image(cfg.SRTM_DEM).select("elevation").clip(region)
    return ee.Terrain.slope(dem).rename("slope_deg")


def compute_erosion_risk(region, year=2023, scale=250):
    """
    Simplified erosion risk index based on RUSLE factors:
    - R (rainfall erosivity): proxy from annual precipitation
    - K (soil erodibility): proxy from clay/sand ratio
    - LS (slope-length): proxy from DEM slope
    - C (cover): proxy from NDVI (low NDVI = high risk)

    Returns 0-1 erosion risk (higher = more risk).
    """
    # R factor proxy: annual rainfall normalized
    from climate import get_chirps_annual
    try:
        precip = get_chirps_annual(year, region)
        r_factor = precip.unitScale(500, 4000).clamp(0, 1).rename("r_factor")
    except Exception:
        r_factor = ee.Image.constant(0.5).rename("r_factor").clip(region)

    # K factor proxy: high clay + low organic carbon = erodible
    try:
        clay = get_soil_clay(region)
        soc = get_soil_organic_carbon(region)
        clay_norm = clay.unitScale(0, 60).clamp(0, 1)
        soc_inv = ee.Image.constant(1).subtract(soc.unitScale(0, 30).clamp(0, 1))
        k_factor = clay_norm.add(soc_inv).divide(2).rename("k_factor")
    except Exception:
        k_factor = ee.Image.constant(0.5).rename("k_factor").clip(region)

    # LS factor proxy: slope
    try:
        slope = compute_slope(region)
        ls_factor = slope.unitScale(0, 30).clamp(0, 1).rename("ls_factor")
    except Exception:
        ls_factor = ee.Image.constant(0.3).rename("ls_factor").clip(region)

    # C factor proxy: inverse NDVI (low vegetation = high erosion)
    from vegetation import get_modis_ndvi_annual
    try:
        ndvi = get_modis_ndvi_annual(year, region)
        c_factor = ee.Image.constant(1).subtract(
            ndvi.clamp(0, 0.8).divide(0.8)
        ).rename("c_factor")
    except Exception:
        c_factor = ee.Image.constant(0.5).rename("c_factor").clip(region)

    # Combined erosion risk
    erosion_risk = (
        r_factor.multiply(0.3)
        .add(k_factor.multiply(0.2))
        .add(ls_factor.multiply(0.25))
        .add(c_factor.multiply(0.25))
        .rename("erosion_risk")
    )
    return erosion_risk


# ═══════════════════════════════════════════════════════════════════════════════
# Salinity Intrusion
# ═══════════════════════════════════════════════════════════════════════════════

def detect_salinity_proxy(year, region, scale=30):
    """
    Detect areas likely affected by salinity using spectral indicators.
    Saline soils show: low NDVI, high brightness, high SWIR reflectance.
    Combined into a Salinity Index (SI) = sqrt(Blue * Red).
    """
    from data_acquisition import get_seasonal_composite
    try:
        composite = get_seasonal_composite(year, "dry", "landsat", region)
    except Exception:
        return None

    blue = composite.select("blue")
    red = composite.select("red")
    # Salinity Index
    si = blue.multiply(red).sqrt().rename("salinity_index")

    # Also use NDVI deficit as indicator
    ndvi = composite.normalizedDifference(["nir", "red"])
    # High SI + low NDVI = likely saline
    saline_proxy = si.multiply(ee.Image.constant(1).subtract(ndvi.clamp(0, 1))).rename("salinity_proxy")
    return saline_proxy


def compute_salinity_risk_zones(region, year=2023, scale=100):
    """
    Map salinity risk zones in coastal Bangladesh.
    Combines: low elevation + high salinity proxy + proximity to coast.
    """
    dem = ee.Image(cfg.SRTM_DEM).select("elevation").clip(region)
    low_elev = dem.lt(5).And(dem.gte(0))

    sal_proxy = detect_salinity_proxy(year, region)
    if sal_proxy is None:
        return None

    # Normalize salinity proxy
    sal_norm = sal_proxy.unitScale(0, 0.3).clamp(0, 1)

    risk = sal_norm.multiply(low_elev.unmask(0)).rename("salinity_risk")
    return risk


# ═══════════════════════════════════════════════════════════════════════════════
# Agricultural Suitability
# ═══════════════════════════════════════════════════════════════════════════════

def compute_ag_suitability(region, year=2023, scale=250):
    """
    Agricultural suitability score (0-1, higher = more suitable).
    Factors: soil quality, slope, flooding risk, rainfall adequacy.
    """
    # Soil quality: high SOC + moderate clay + neutral pH
    try:
        soc = get_soil_organic_carbon(region)
        soc_score = soc.unitScale(0, 20).clamp(0, 1)
        ph = get_soil_ph(region)
        # Optimal pH 5.5-7.5
        ph_score = ee.Image.constant(1).subtract(
            ph.subtract(6.5).abs().divide(2)
        ).clamp(0, 1)
        soil_score = soc_score.add(ph_score).divide(2).rename("soil_score")
    except Exception:
        soil_score = ee.Image.constant(0.5).rename("soil_score").clip(region)

    # Slope: flat is better for rice
    try:
        slope = compute_slope(region)
        slope_score = ee.Image.constant(1).subtract(
            slope.unitScale(0, 15).clamp(0, 1)
        ).rename("slope_score")
    except Exception:
        slope_score = ee.Image.constant(0.7).rename("slope_score").clip(region)

    # Rainfall adequacy
    from climate import get_chirps_annual
    try:
        precip = get_chirps_annual(year, region)
        # Optimal: 1500-3000mm
        rain_score = precip.unitScale(800, 2000).clamp(0, 1).rename("rain_score")
    except Exception:
        rain_score = ee.Image.constant(0.7).rename("rain_score").clip(region)

    suitability = (
        soil_score.multiply(0.4)
        .add(slope_score.multiply(0.3))
        .add(rain_score.multiply(0.3))
        .rename("ag_suitability")
    )
    return suitability


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_soil_analysis(region):
    """Full soil analysis pipeline."""
    results = {}

    print("\n  Computing soil property statistics...")
    try:
        results["soil_stats"] = compute_soil_stats(region)
    except Exception as e:
        print(f"    Soil stats skipped: {e}")

    print("  Computing erosion risk map...")
    try:
        results["erosion_risk"] = compute_erosion_risk(region)
    except Exception as e:
        print(f"    Erosion risk skipped: {e}")

    print("  Detecting salinity proxy (coastal)...")
    try:
        results["salinity_proxy"] = detect_salinity_proxy(2023, region)
    except Exception as e:
        print(f"    Salinity proxy skipped: {e}")

    print("  Mapping salinity risk zones...")
    try:
        results["salinity_risk"] = compute_salinity_risk_zones(region)
    except Exception as e:
        print(f"    Salinity risk skipped: {e}")

    print("  Computing agricultural suitability...")
    try:
        results["ag_suitability"] = compute_ag_suitability(region)
    except Exception as e:
        print(f"    Ag suitability skipped: {e}")

    return results
