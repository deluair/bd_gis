"""
Groundwater depletion analysis using GRACE satellite gravity data.

GRACE measures total water storage (TWS) anomalies monthly (2002-2017).
Decomposition: TWS = groundwater + soil moisture + surface water + snow/ice
For Bangladesh (no snow): GWS anomaly = TWS - soil moisture - surface water
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# GRACE Total Water Storage
# ═══════════════════════════════════════════════════════════════════════════════

def get_grace_tws(year, region):
    """
    Get GRACE total water storage anomaly for a given year (annual mean).

    Returns an image in cm equivalent water height.
    MASCON_CRI band 'lwe_thickness' is already in cm.
    """
    col = (
        ee.ImageCollection(cfg.GRACE_MASCON["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
        .select(cfg.GRACE_MASCON["band"])
    )
    count = col.size()
    # Return mean annual TWS anomaly; rename for clarity
    annual_mean = col.mean().clip(region).rename("tws_anomaly_cm")
    return annual_mean, count


def compute_tws_timeseries(region, scale=25000):
    """
    Compute annual mean TWS anomaly time series 2002-2017.

    GRACE MASCON data covers 2002-04 through 2017-06 (with gaps).
    Returns list of dicts: {year, mean_tws_cm, min_tws_cm, max_tws_cm, n_months}
    """
    series = []
    start_year = cfg.GRACE_MASCON["years"][0]
    end_year = cfg.GRACE_MASCON["years"][1]

    for year in range(start_year, end_year + 1):
        try:
            img, count = get_grace_tws(year, region)
            n_months = count.getInfo()
            if n_months == 0:
                continue
            stats = img.reduceRegion(
                reducer=ee.Reducer.mean().combine(
                    ee.Reducer.min(), sharedInputs=True
                ).combine(
                    ee.Reducer.max(), sharedInputs=True
                ),
                geometry=region,
                scale=scale,
                maxPixels=cfg.MAX_PIXELS,
                bestEffort=True,
            )
            series.append({
                "year": year,
                "mean_tws_cm": stats.get("tws_anomaly_cm_mean"),
                "min_tws_cm": stats.get("tws_anomaly_cm_min"),
                "max_tws_cm": stats.get("tws_anomaly_cm_max"),
                "n_months": n_months,
            })
        except Exception as e:
            print(f"  GRACE TWS {year} skipped: {e}")
    return series


# ═══════════════════════════════════════════════════════════════════════════════
# TWS Trend Map (per-pixel linear trend)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_tws_trend_map(region):
    """
    Compute per-pixel linear trend in TWS over the GRACE period (2002-2017).

    Uses ee.Reducer.linearFit() on a time series of monthly images.
    Positive slope = water storage gaining; negative = losing (depletion).
    Returns image with bands: 'scale' (slope in cm/month), 'offset'.
    """
    start_year = cfg.GRACE_MASCON["years"][0]
    end_year = cfg.GRACE_MASCON["years"][1]

    col = (
        ee.ImageCollection(cfg.GRACE_MASCON["collection"])
        .filterDate(f"{start_year}-01-01", f"{end_year}-12-31")
        .filterBounds(region)
        .select(cfg.GRACE_MASCON["band"])
    )

    # Add time band (months since first image) for linearFit
    def add_time(image):
        t = image.date().difference(
            ee.Date(f"{start_year}-01-01"), "month"
        )
        return image.addBands(
            ee.Image.constant(t).rename("time").toFloat()
        )

    col_with_time = col.map(add_time)

    # linearFit: dependent=tws_anomaly_cm, independent=time
    trend = col_with_time.select(["time", cfg.GRACE_MASCON["band"]]).reduce(
        ee.Reducer.linearFit()
    ).clip(region)

    # Rename for clarity: 'scale' is slope (cm/month), 'offset' is intercept
    return trend.rename(["tws_slope_cm_per_month", "tws_intercept"])


# ═══════════════════════════════════════════════════════════════════════════════
# GLDAS Soil Moisture
# ═══════════════════════════════════════════════════════════════════════════════

def _get_gldas_soil_moisture(year, region):
    """
    Get annual mean soil moisture column from GLDAS NOAH (mm).

    GLDAS provides 4 soil moisture layers (0-10cm, 10-40cm, 40-100cm,
    100-200cm). Sum them and convert to cm equivalent water height.
    Units: kg/m2, which is numerically equal to mm of water.
    """
    bands = cfg.GLDAS_NOAH["soil_moisture_bands"]
    col = (
        ee.ImageCollection(cfg.GLDAS_NOAH["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
        .select(bands)
    )
    # Sum soil moisture layers per image, then take annual mean
    def sum_layers(img):
        total = img.select(bands[0])
        for b in bands[1:]:
            total = total.add(img.select(b))
        # Convert mm to cm
        return total.divide(10).rename("soil_moisture_cm")

    annual_sm = col.map(sum_layers).mean().clip(region)
    return annual_sm


def _get_surface_water_thickness(year, region):
    """
    Approximate surface water storage anomaly from JRC monthly water
    history (presence/absence) and a nominal depth assumption (50 cm).

    This is a rough decomposition; the dominant signal in Bangladesh
    is groundwater and soil moisture.
    """
    jrc_monthly = (
        ee.ImageCollection(cfg.JRC_MONTHLY)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
    )
    # Fraction of months with surface water = water frequency proxy
    def to_water(img):
        return img.select("water").gte(1).rename("water_frac")

    freq = jrc_monthly.map(to_water).mean().clip(region)
    # Assumed 50 cm mean depth for open water cells
    sw_cm = freq.multiply(50).rename("surface_water_cm")
    return sw_cm


# ═══════════════════════════════════════════════════════════════════════════════
# Groundwater Storage Anomaly
# ═══════════════════════════════════════════════════════════════════════════════

def compute_groundwater_anomaly(region, scale=25000):
    """
    Estimate groundwater storage anomaly by TWS decomposition.

    GWS = TWS_anomaly - soil_moisture_anomaly - surface_water_anomaly

    Because GRACE reports anomalies relative to 2004-2009 mean, we compute
    soil moisture and surface water anomalies the same way (subtract their
    2004-2009 mean) before differencing.

    Returns list of dicts: {year, tws_cm, sm_cm, sw_cm, gws_cm}
    """
    ref_start = cfg.GRACE_MASCON["ref_period"][0]
    ref_end = cfg.GRACE_MASCON["ref_period"][1]
    start_year = cfg.GRACE_MASCON["years"][0]
    end_year = cfg.GRACE_MASCON["years"][1]

    # Reference period means for anomaly computation
    sm_ref_images = []
    for y in range(ref_start, ref_end + 1):
        try:
            sm_ref_images.append(_get_gldas_soil_moisture(y, region))
        except Exception:
            pass

    sm_ref_mean = (
        ee.ImageCollection(sm_ref_images).mean() if sm_ref_images
        else ee.Image.constant(0).rename("soil_moisture_cm")
    )

    results = []
    for year in range(start_year, end_year + 1):
        try:
            tws_img, count = get_grace_tws(year, region)
            if count.getInfo() == 0:
                continue

            sm_img = _get_gldas_soil_moisture(year, region)
            sm_anomaly = sm_img.subtract(sm_ref_mean).rename("sm_anomaly_cm")

            sw_img = _get_surface_water_thickness(year, region)

            # GWS = TWS - SM_anomaly - SW (SW is already small, no ref needed)
            gws = tws_img.subtract(sm_anomaly).subtract(sw_img).rename("gws_anomaly_cm")

            stats = (
                tws_img.addBands(sm_anomaly)
                .addBands(sw_img)
                .addBands(gws)
                .reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=region,
                    scale=scale,
                    maxPixels=cfg.MAX_PIXELS,
                    bestEffort=True,
                )
            )
            results.append({
                "year": year,
                "tws_cm": stats.get("tws_anomaly_cm"),
                "sm_cm": stats.get("sm_anomaly_cm"),
                "sw_cm": stats.get("surface_water_cm"),
                "gws_cm": stats.get("gws_anomaly_cm"),
            })
        except Exception as e:
            print(f"  GWS anomaly {year} skipped: {e}")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Depletion Hotspots
# ═══════════════════════════════════════════════════════════════════════════════

def identify_depletion_hotspots(region, depletion_threshold=-2.0):
    """
    Identify areas with significant negative TWS trend.

    Threshold: pixels where the TWS slope < depletion_threshold cm/month
    are flagged as depletion hotspots. Default -2.0 cm/month is a strong
    signal; adjust for sensitivity.

    Returns:
        hotspot_mask: binary image (1 = depleting)
        trend_map: full per-pixel slope image
        hotspot_stats: dict of area and mean depletion rate per known hotspot
    """
    trend_map = compute_tws_trend_map(region)
    slope = trend_map.select("tws_slope_cm_per_month")

    hotspot_mask = slope.lt(depletion_threshold).rename("depletion_hotspot")

    hotspot_stats = {}
    for name, info in cfg.GROUNDWATER_HOTSPOTS.items():
        try:
            center = ee.Geometry.Point([info["lon"], info["lat"]])
            hotspot_region = center.buffer(info["radius"])

            local_stats = slope.clip(hotspot_region).reduceRegion(
                reducer=ee.Reducer.mean().combine(
                    ee.Reducer.min(), sharedInputs=True
                ),
                geometry=hotspot_region,
                scale=25000,
                maxPixels=cfg.MAX_PIXELS,
                bestEffort=True,
            )

            hotspot_area = (
                hotspot_mask.clip(hotspot_region)
                .multiply(ee.Image.pixelArea())
                .reduceRegion(
                    reducer=ee.Reducer.sum(),
                    geometry=hotspot_region,
                    scale=25000,
                    maxPixels=cfg.MAX_PIXELS,
                    bestEffort=True,
                )
            )

            hotspot_stats[name] = {
                "mean_slope_cm_per_month": local_stats.get("tws_slope_cm_per_month_mean"),
                "min_slope_cm_per_month": local_stats.get("tws_slope_cm_per_month_min"),
                "depleting_area_m2": hotspot_area.get("depletion_hotspot"),
                "lat": info["lat"],
                "lon": info["lon"],
            }
        except Exception as e:
            print(f"  Hotspot {name} skipped: {e}")

    return {
        "hotspot_mask": hotspot_mask,
        "trend_map": trend_map,
        "hotspot_stats": hotspot_stats,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_groundwater_analysis(region):
    """Full groundwater depletion analysis pipeline."""
    results = {}

    print("\n  Computing GRACE TWS time series (2002-2017)...")
    results["tws_timeseries"] = compute_tws_timeseries(region)

    print("  Computing TWS trend map (per-pixel linear trend)...")
    try:
        results["tws_trend_map"] = compute_tws_trend_map(region)
    except Exception as e:
        print(f"    TWS trend map skipped: {e}")
        results["tws_trend_map"] = None

    print("  Decomposing TWS into groundwater storage anomaly...")
    results["groundwater_anomaly"] = compute_groundwater_anomaly(region)

    print("  Identifying depletion hotspots...")
    try:
        results["depletion_hotspots"] = identify_depletion_hotspots(region)
    except Exception as e:
        print(f"    Depletion hotspots skipped: {e}")
        results["depletion_hotspots"] = None

    return results
