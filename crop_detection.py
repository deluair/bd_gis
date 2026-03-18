"""
Crop detection and agricultural monitoring – multi-season crop type mapping,
rice phenology tracking, crop calendar analysis, yield estimation proxies,
and food security indicators for Bangladesh.

Bangladesh crop calendar:
  - Aman rice (monsoon): Jun–Nov (transplanted Jul, harvested Nov–Dec)
  - Boro rice (dry irrigated): Dec–May (transplanted Jan, harvested Apr–May)
  - Aus rice (pre-monsoon): Mar–Aug (transplanted Apr, harvested Jul–Aug)
  - Wheat: Nov–Mar
  - Jute: Apr–Aug
  - Vegetables/pulses: Oct–Mar (rabi season)
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Spectral Indices for Crop Detection
# ═══════════════════════════════════════════════════════════════════════════════

def compute_lswi(image):
    """Land Surface Water Index = (NIR - SWIR1) / (NIR + SWIR1). High in flooded paddies."""
    return image.normalizedDifference(["nir", "swir1"]).rename("lswi")


def compute_gcvi(image):
    """Green Chlorophyll Vegetation Index = (NIR / Green) - 1. Sensitive to chlorophyll.
    Not used internally; available for external modules and ad-hoc analysis."""
    nir = image.select("nir")
    green = image.select("green")
    return nir.divide(green).subtract(1).rename("gcvi")


def compute_ndvi(image):
    """NDVI = (NIR - Red) / (NIR + Red)."""
    return image.normalizedDifference(["nir", "red"]).rename("ndvi")


def compute_evi(image):
    """Enhanced Vegetation Index.
    Not used internally; available for external modules and ad-hoc analysis."""
    nir = image.select("nir")
    red = image.select("red")
    blue = image.select("blue")
    return nir.subtract(red).multiply(2.5).divide(
        nir.add(red.multiply(6)).subtract(blue.multiply(7.5)).add(1)
    ).rename("evi")


# ═══════════════════════════════════════════════════════════════════════════════
# Rice Detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_rice_paddy(year, season, region):
    """
    Detect rice paddy fields using flooding + greening phenology.
    Rice paddies show: high LSWI (flooded) → high NDVI (vegetated) → low NDVI (harvest).

    season: 'aman' (monsoon rice), 'boro' (dry rice), 'aus' (pre-monsoon rice)
    """
    from data_acquisition import get_landsat_collection, make_composite

    if season == "aman":
        # Transplanting: Jul-Aug (flooded), Peak: Sep-Oct, Harvest: Nov-Dec
        flood_start, flood_end = f"{year}-07-01", f"{year}-08-31"
        peak_start, peak_end = f"{year}-09-01", f"{year}-10-31"
        harvest_start, harvest_end = f"{year}-11-01", f"{year}-12-31"
    elif season == "boro":
        # Transplanting: Jan-Feb (flooded), Peak: Mar-Apr, Harvest: Apr-May
        flood_start, flood_end = f"{year}-01-01", f"{year}-02-28"
        peak_start, peak_end = f"{year}-03-01", f"{year}-04-15"
        harvest_start, harvest_end = f"{year}-04-15", f"{year}-05-31"
    elif season == "aus":
        # Transplanting: Apr-May, Peak: Jun-Jul, Harvest: Jul-Aug
        flood_start, flood_end = f"{year}-04-01", f"{year}-05-31"
        peak_start, peak_end = f"{year}-06-01", f"{year}-07-15"
        harvest_start, harvest_end = f"{year}-07-15", f"{year}-08-31"
    else:
        raise ValueError(f"Unknown rice season: {season}")

    # Get composites for each phase
    # WARNING: Jul-Aug composites during Bangladesh monsoon may have very few
    # cloud-free observations. LSWI-based flood detection on sparse composites
    # is unreliable. Consider using SAR (Sentinel-1) for monsoon water detection.
    try:
        flood_col = get_landsat_collection(flood_start, flood_end, region)
        flood_count = flood_col.size().getInfo()
        if flood_count < 3:
            print(f"  WARNING: Only {flood_count} cloud-free images for {season} flood phase "
                  f"({flood_start} to {flood_end}). Composite may be unreliable.")
        flood_comp = make_composite(flood_col)
    except Exception:
        return None

    try:
        peak_col = get_landsat_collection(peak_start, peak_end, region)
        peak_comp = make_composite(peak_col)
    except Exception:
        return None

    # Flooding phase: high LSWI (> 0) indicates standing water
    lswi_flood = compute_lswi(flood_comp)
    flooded = lswi_flood.gt(0)

    # Peak phase: high NDVI (> 0.4) indicates active vegetation
    ndvi_peak = compute_ndvi(peak_comp)
    vegetated = ndvi_peak.gt(0.4)

    # Rice = flooded during transplanting AND vegetated during peak
    rice = flooded.And(vegetated).rename("rice_paddy")
    return rice


def compute_rice_area(year, season, region, scale=30):
    """Compute rice paddy area in km2."""
    rice = detect_rice_paddy(year, season, region)
    if rice is None:
        return None

    area = rice.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    return {
        "year": year,
        "season": season,
        "rice_area_km2": ee.Number(area.get("rice_paddy")).divide(1e6),
    }


def compute_rice_timeseries(region, season="aman", start_year=2000, end_year=2024, step=2):
    """Track rice area over time for a specific season."""
    series = []
    for year in range(start_year, end_year + 1, step):
        try:
            result = compute_rice_area(year, season, region)
            if result:
                series.append(result)
        except Exception as e:
            print(f"  Rice {season} {year} skipped: {e}")
    return series


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-Crop Classification
# ═══════════════════════════════════════════════════════════════════════════════

def classify_crop_types(year, region):
    """
    Classify major crop types using Dynamic World + seasonal NDVI phenology.
    Returns: rice, other_crops, fallow, and non-agricultural masks.
    """
    from land_cover import get_dynamic_world

    # Get annual Dynamic World for cropland baseline
    dw = get_dynamic_world(f"{year}-01-01", f"{year}-12-31", region)
    cropland = dw.eq(4)  # crops class

    # Detect rice (aman + boro + aus)
    aman_rice = detect_rice_paddy(year, "aman", region)
    boro_rice = detect_rice_paddy(year, "boro", region)
    aus_rice = detect_rice_paddy(year, "aus", region)

    rice_any = ee.Image.constant(0).rename("rice")
    if aman_rice is not None:
        rice_any = rice_any.Or(aman_rice)
    if boro_rice is not None:
        rice_any = rice_any.Or(boro_rice)
    if aus_rice is not None:
        rice_any = rice_any.Or(aus_rice)

    # Other crops = cropland but not rice
    other_crops = cropland.And(rice_any.Not()).rename("other_crops")

    # Classify into:
    # 1=aman, 2=boro, 3=aman+boro, 4=aus, 5=aus+aman, 6=aus+boro, 7=other_crops, 0=non_crop
    classified = ee.Image.constant(0).rename("crop_type")

    has_aman = aman_rice is not None
    has_boro = boro_rice is not None
    has_aus = aus_rice is not None

    if has_aman:
        classified = classified.where(aman_rice, 1)
    if has_boro:
        classified = classified.where(boro_rice, 2)
    if has_aman and has_boro:
        classified = classified.where(aman_rice.And(boro_rice), 3)
    if has_aus:
        classified = classified.where(aus_rice, 4)
    if has_aus and has_aman:
        classified = classified.where(aus_rice.And(aman_rice), 5)
    if has_aus and has_boro:
        classified = classified.where(aus_rice.And(boro_rice), 6)
    classified = classified.where(other_crops, 7)

    return {
        "crop_type": classified,
        "rice": rice_any,
        "cropland": cropland,
        "other_crops": other_crops,
    }


def compute_crop_area_stats(year, region, scale=100):
    """Compute area statistics for each crop type."""
    result = classify_crop_types(year, region)
    if result is None:
        return None

    classified = result["crop_type"]
    classes = {0: "Non-crop", 1: "Aman Rice", 2: "Boro Rice",
               3: "Aman+Boro Rice", 4: "Aus Rice", 5: "Aus+Aman Rice",
               6: "Aus+Boro Rice", 7: "Other Crops"}
    stats = []
    for val, name in classes.items():
        mask = classified.eq(val)
        area = mask.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(), geometry=region,
            scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
        )
        stats.append({
            "class": name,
            "area_km2": ee.Number(area.get("crop_type")).divide(1e6),
        })
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# Crop Health & Yield Proxy
# ═══════════════════════════════════════════════════════════════════════════════

def compute_crop_ndvi_profile(year, region, scale=1000):
    """
    Compute monthly NDVI profile for croplands to track growing season.
    Returns 12-month NDVI values averaged over cropland areas.
    """
    from land_cover import get_esa_worldcover
    try:
        wc = get_esa_worldcover(min(year, 2021), region)  # clamp to available years
        cropland = wc.eq(40)  # ESA WorldCover cropland class
    except Exception:
        cropland = None

    profile = []
    for month in range(1, 13):
        end_month = month + 1 if month < 12 else 1
        end_year = year if month < 12 else year + 1
        try:
            col = (
                ee.ImageCollection(cfg.MODIS_NDVI["collection"])
                .filterDate(f"{year}-{month:02d}-01", f"{end_year}-{end_month:02d}-01")
                .filterBounds(region)
                .select(cfg.MODIS_NDVI["ndvi_band"])
            )
            ndvi = col.mean().multiply(cfg.MODIS_NDVI["scale_factor"]).clip(region)
            if cropland is not None:
                ndvi = ndvi.updateMask(cropland)

            stats = ndvi.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=region,
                scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
            )
            profile.append({
                "month": month,
                "mean_ndvi": stats.get("NDVI"),
            })
        except Exception:
            profile.append({"month": month, "mean_ndvi": None})
    return profile


def compute_yield_proxy(year, season, region, scale=1000):
    """
    Compute crop yield proxy using peak-season integrated NDVI.
    Higher cumulative NDVI during growing season correlates with higher yields.
    """
    if season == "aman":
        start, end = f"{year}-08-01", f"{year}-11-30"
    elif season == "boro":
        start, end = f"{year}-02-01", f"{year}-05-15"
    elif season == "aus":
        start, end = f"{year}-04-01", f"{year}-08-31"
    else:
        start, end = f"{year}-01-01", f"{year}-12-31"

    col = (
        ee.ImageCollection(cfg.MODIS_NDVI["collection"])
        .filterDate(start, end)
        .filterBounds(region)
        .select(cfg.MODIS_NDVI["ndvi_band"])
    )
    # Sum of NDVI values = proxy for cumulative biomass production
    integrated_ndvi = col.sum().multiply(cfg.MODIS_NDVI["scale_factor"]).clip(region)

    stats = integrated_ndvi.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.max(), sharedInputs=True),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    return {
        "year": year,
        "season": season,
        "mean_integrated_ndvi": stats.get("NDVI_mean"),
        "max_integrated_ndvi": stats.get("NDVI_max"),
    }


def compute_crop_stress(year, region, scale=1000):
    """
    Detect crop stress using NDVI anomaly during peak growing season.
    Compares current year to long-term mean (2000-2020).
    """
    # Current year peak NDVI (aman season: Aug-Oct)
    current = (
        ee.ImageCollection(cfg.MODIS_NDVI["collection"])
        .filterDate(f"{year}-08-01", f"{year}-10-31")
        .filterBounds(region)
        .select(cfg.MODIS_NDVI["ndvi_band"])
        .mean()
        .multiply(cfg.MODIS_NDVI["scale_factor"])
        .clip(region)
    )

    # Long-term mean for same period (exclude analysis year to avoid self-inclusion)
    lt_images = []
    baseline_years = [y for y in range(2000, 2021) if y != year]
    for y in baseline_years:
        img = (
            ee.ImageCollection(cfg.MODIS_NDVI["collection"])
            .filterDate(f"{y}-08-01", f"{y}-10-31")
            .filterBounds(region)
            .select(cfg.MODIS_NDVI["ndvi_band"])
            .mean()
        )
        lt_images.append(img)
    lt_mean = ee.ImageCollection(lt_images).mean().multiply(
        cfg.MODIS_NDVI["scale_factor"]
    ).clip(region)

    anomaly = current.subtract(lt_mean).rename("crop_stress")
    # Negative = stress (below normal), positive = above normal
    return anomaly


# ═══════════════════════════════════════════════════════════════════════════════
# Cropping Intensity
# ═══════════════════════════════════════════════════════════════════════════════

def compute_cropping_intensity(year, region, scale=250):
    """
    Estimate cropping intensity (number of harvests per year).
    Uses NDVI peak counting: each NDVI rise-fall cycle = one crop cycle.
    Simplified: count months with NDVI > 0.4 threshold.
    """
    high_ndvi_months = ee.Image.constant(0).rename("intensity")
    for month in range(1, 13):
        end_month = month + 1 if month < 12 else 1
        end_year = year if month < 12 else year + 1
        try:
            ndvi = (
                ee.ImageCollection(cfg.MODIS_NDVI["collection"])
                .filterDate(f"{year}-{month:02d}-01", f"{end_year}-{end_month:02d}-01")
                .filterBounds(region)
                .select(cfg.MODIS_NDVI["ndvi_band"])
                .mean()
                .multiply(cfg.MODIS_NDVI["scale_factor"])
            )
            high_ndvi_months = high_ndvi_months.add(ndvi.gt(0.4).unmask(0))
        except Exception:
            pass

    # Mask to cropland before computing cropping intensity
    try:
        from land_cover import get_esa_worldcover
        cropland_mask = get_esa_worldcover(min(year, 2021), region).eq(40)
        high_ndvi_months = high_ndvi_months.updateMask(cropland_mask)
    except Exception:
        pass  # fallback: no cropland mask

    # Approximate crop cycles: 3-4 months = single crop, 6-8 = double, 9+ = triple
    intensity = (
        ee.Image.constant(0).rename("cropping_intensity")
        .where(high_ndvi_months.gte(3).And(high_ndvi_months.lt(6)), 1)
        .where(high_ndvi_months.gte(6).And(high_ndvi_months.lt(9)), 2)
        .where(high_ndvi_months.gte(9), 3)
    ).clip(region)

    return intensity


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_crop_detection_analysis(region):
    """Full crop detection and agricultural monitoring pipeline."""
    results = {}

    print("\n  Detecting aman rice area time series...")
    results["aman_timeseries"] = compute_rice_timeseries(region, "aman", step=3)

    print("  Detecting boro rice area time series...")
    results["boro_timeseries"] = compute_rice_timeseries(region, "boro", step=3)

    print("  Classifying crop types for 2023...")
    try:
        results["crop_types_2023"] = classify_crop_types(2023, region)
    except Exception as e:
        print(f"    Crop classification skipped: {e}")

    print("  Computing crop area statistics...")
    try:
        results["crop_stats_2023"] = compute_crop_area_stats(2023, region)
    except Exception as e:
        print(f"    Crop stats skipped: {e}")

    print("  Computing monthly NDVI crop profile 2023...")
    try:
        results["ndvi_profile_2023"] = compute_crop_ndvi_profile(2023, region)
    except Exception as e:
        print(f"    NDVI profile skipped: {e}")

    print("  Computing yield proxies...")
    results["yield_proxies"] = []
    for year in [2018, 2020, 2022, 2023]:
        for season in ["aman", "boro"]:
            try:
                results["yield_proxies"].append(compute_yield_proxy(year, season, region))
            except Exception as e:
                print(f"    Yield proxy {year} {season} skipped: {e}")

    print("  Detecting crop stress 2023...")
    try:
        results["crop_stress_2023"] = compute_crop_stress(2023, region)
    except Exception as e:
        print(f"    Crop stress skipped: {e}")

    print("  Computing cropping intensity 2023...")
    try:
        results["cropping_intensity_2023"] = compute_cropping_intensity(2023, region)
    except Exception as e:
        print(f"    Cropping intensity skipped: {e}")

    return results
