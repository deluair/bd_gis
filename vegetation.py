"""
Vegetation and agriculture analysis – NDVI/EVI time series, crop mapping,
forest change detection using MODIS, Landsat, and Hansen Global Forest Change.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Vegetation Indices
# ═══════════════════════════════════════════════════════════════════════════════

def compute_ndvi(image):
    """NDVI = (NIR - Red) / (NIR + Red)."""
    return image.normalizedDifference(["nir", "red"]).rename("ndvi")


def compute_evi(image):
    """EVI = 2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)."""
    nir = image.select("nir")
    red = image.select("red")
    blue = image.select("blue")
    evi = nir.subtract(red).multiply(2.5).divide(
        nir.add(red.multiply(6)).subtract(blue.multiply(7.5)).add(1)
    )
    return evi.rename("evi")


def compute_savi(image, L=0.5):
    """Soil Adjusted Vegetation Index = (NIR - Red) * (1 + L) / (NIR + Red + L)."""
    nir = image.select("nir")
    red = image.select("red")
    savi = nir.subtract(red).multiply(1 + L).divide(nir.add(red).add(L))
    return savi.rename("savi")


# ═══════════════════════════════════════════════════════════════════════════════
# MODIS Vegetation
# ═══════════════════════════════════════════════════════════════════════════════

def _mask_modis_vi_quality(img):
    """Mask MODIS vegetation index pixels with poor quality (SummaryQA > 1)."""
    qa = img.select("SummaryQA")
    return img.updateMask(qa.lte(1))  # 0=good, 1=marginal, 2-3=bad


def get_modis_ndvi_annual(year, region):
    """Get MODIS annual max NDVI composite."""
    col = (
        ee.ImageCollection(cfg.MODIS_NDVI["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
        .map(_mask_modis_vi_quality)
        .select(cfg.MODIS_NDVI["ndvi_band"])
    )
    return col.max().multiply(cfg.MODIS_NDVI["scale_factor"]).clip(region).rename("ndvi")


def get_modis_evi_annual(year, region):
    """Get MODIS annual max EVI composite."""
    col = (
        ee.ImageCollection(cfg.MODIS_NDVI["collection"])
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filterBounds(region)
        .map(_mask_modis_vi_quality)
        .select(cfg.MODIS_NDVI["evi_band"])
    )
    return col.max().multiply(cfg.MODIS_NDVI["scale_factor"]).clip(region).rename("evi")


def compute_modis_ndvi_timeseries(region, start_year=2000, end_year=2024, step=1):
    """Compute annual mean/max NDVI from MODIS over time."""
    series = []
    for year in range(start_year, end_year + 1, step):
        try:
            col = (
                ee.ImageCollection(cfg.MODIS_NDVI["collection"])
                .filterDate(f"{year}-01-01", f"{year}-12-31")
                .filterBounds(region)
                .map(_mask_modis_vi_quality)
                .select(cfg.MODIS_NDVI["ndvi_band"])
            )
            ndvi_band = cfg.MODIS_NDVI["ndvi_band"]
            scaled = col.map(lambda img: img.multiply(cfg.MODIS_NDVI["scale_factor"]))
            annual_mean = scaled.mean().clip(region)
            annual_max = scaled.max().clip(region)

            stats_mean = annual_mean.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region, scale=1000,
                maxPixels=cfg.MAX_PIXELS, bestEffort=True,
            )
            stats_max = annual_max.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region, scale=1000,
                maxPixels=cfg.MAX_PIXELS, bestEffort=True,
            )
            series.append({
                "year": year,
                "mean_ndvi": stats_mean.get(ndvi_band),
                "max_ndvi": stats_max.get(ndvi_band),
            })
        except Exception as e:
            print(f"  NDVI {year} skipped: {e}")
    return series


def compute_seasonal_ndvi(year, region, scale=1000):
    """Compute seasonal NDVI stats (pre-monsoon, monsoon, post-monsoon, winter)."""
    seasons = {
        "pre_monsoon": (f"{year}-03-01", f"{year}-05-31"),
        "monsoon": (f"{year}-06-01", f"{year}-09-30"),
        "post_monsoon": (f"{year}-10-01", f"{year}-11-30"),
        "winter": (f"{year}-12-01", f"{year + 1}-03-01"),
    }
    ndvi_band = cfg.MODIS_NDVI["ndvi_band"]
    results = {"year": year}
    for season, (start, end) in seasons.items():
        try:
            col = (
                ee.ImageCollection(cfg.MODIS_NDVI["collection"])
                .filterDate(start, end)
                .filterBounds(region)
                .map(_mask_modis_vi_quality)
                .select(cfg.MODIS_NDVI["ndvi_band"])
            )
            mean_img = col.mean().multiply(cfg.MODIS_NDVI["scale_factor"]).clip(region)
            stats = mean_img.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region, scale=scale,
                maxPixels=cfg.MAX_PIXELS, bestEffort=True,
            )
            results[f"{season}_ndvi"] = stats.get(ndvi_band)
        except Exception as e:
            results[f"{season}_ndvi"] = None
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Forest Change (Hansen)
# ═══════════════════════════════════════════════════════════════════════════════

def get_forest_cover_2000(region):
    """Get Hansen tree cover in 2000 (percent)."""
    gfc = ee.Image(cfg.GLOBAL_FOREST_CHANGE["image"])
    return gfc.select("treecover2000").clip(region)


def get_forest_loss(region):
    """Get cumulative forest loss mask."""
    gfc = ee.Image(cfg.GLOBAL_FOREST_CHANGE["image"])
    return gfc.select("loss").clip(region)


def get_forest_gain(region):
    """Get cumulative forest gain mask."""
    gfc = ee.Image(cfg.GLOBAL_FOREST_CHANGE["image"])
    return gfc.select("gain").clip(region)


def get_forest_loss_year(region):
    """Get year of forest loss (0 = no loss, 1-23 = year since 2000)."""
    gfc = ee.Image(cfg.GLOBAL_FOREST_CHANGE["image"])
    return gfc.select("lossyear").clip(region)


def compute_forest_stats(region, tree_threshold=30, scale=None):
    """
    Compute forest cover stats: initial cover, loss, gain, net change.
    tree_threshold: minimum canopy cover % to consider as forest.
    """
    # Hansen default is 30% (IPCC/FAO international standard).
    # Bangladesh Forest Department uses 10% (national reporting convention).
    # Using 30% for international comparability; adjust for national statistics.
    if scale is None:
        scale = 300 if cfg.SCOPE == "national" else 30
    gfc = ee.Image(cfg.GLOBAL_FOREST_CHANGE["image"]).clip(region)
    tree2000 = gfc.select("treecover2000")
    loss = gfc.select("loss")
    gain = gfc.select("gain")

    forest2000 = tree2000.gte(tree_threshold)

    # Areas in km2
    forest_area = forest2000.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    loss_area = loss.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )
    gain_area = gain.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region,
        scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
    )

    return {
        "forest_2000_km2": ee.Number(forest_area.get("treecover2000")).divide(1e6),
        "forest_loss_km2": ee.Number(loss_area.get("loss")).divide(1e6),
        "forest_gain_km2": ee.Number(gain_area.get("gain")).divide(1e6),
    }


def compute_forest_loss_by_year(region, tree_threshold=30, scale=None):
    """Compute annual forest loss area from Hansen loss year band."""
    if scale is None:
        scale = 300 if cfg.SCOPE == "national" else 30
    gfc = ee.Image(cfg.GLOBAL_FOREST_CHANGE["image"]).clip(region)
    lossyear = gfc.select("lossyear")
    tree2000 = gfc.select("treecover2000").gte(tree_threshold)

    # Hansen GFC lossyear: 1 = 2001, 23 = 2023
    max_loss_year = cfg.GLOBAL_FOREST_CHANGE.get("max_loss_year", 23)
    results = []
    for yr in range(1, max_loss_year + 1):
        yr_loss = lossyear.eq(yr).And(tree2000)
        area = yr_loss.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(), geometry=region,
            scale=scale, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
        )
        results.append({
            "year": 2000 + yr,
            "loss_km2": ee.Number(area.get("lossyear")).divide(1e6),
        })
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Agriculture
# ═══════════════════════════════════════════════════════════════════════════════

def detect_cropland(region, year=2021):
    """
    Extract cropland areas from ESA WorldCover (class 40 = Cropland).
    Returns binary cropland mask.
    """
    from land_cover import get_esa_worldcover
    wc = get_esa_worldcover(year, region)
    return wc.eq(40).rename("cropland")


def compute_crop_health_index(composite, region):
    """
    Compute crop health using NDVI deviation from long-term mean.
    Uses a single year's composite vs MODIS long-term average.
    """
    # WARNING: Cross-sensor NDVI comparison (input composite vs MODIS baseline).
    # Spectral response differences introduce systematic bias.
    # Use MODIS composites for both current and baseline for valid anomaly detection.
    ndvi = compute_ndvi(composite)

    # Long-term NDVI mean (2000-2020 from MODIS)
    lt_ndvi = (
        ee.ImageCollection(cfg.MODIS_NDVI["collection"])
        .filterDate("2000-01-01", "2020-12-31")
        .filterBounds(region)
        .select(cfg.MODIS_NDVI["ndvi_band"])
        .mean()
        .multiply(cfg.MODIS_NDVI["scale_factor"])
        .clip(region)
        .rename("ndvi")
    )

    # Anomaly
    anomaly = ndvi.subtract(lt_ndvi).rename("ndvi_anomaly")
    return anomaly


# ═══════════════════════════════════════════════════════════════════════════════
# Full Analysis Runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_vegetation_analysis(region):
    """Full vegetation and agriculture analysis pipeline."""
    results = {}

    print("\n  Computing MODIS NDVI time series (2000–2024)...")
    results["ndvi_timeseries"] = compute_modis_ndvi_timeseries(region, step=2)

    print("  Computing seasonal NDVI for recent years...")
    results["seasonal_ndvi"] = []
    for year in [2005, 2010, 2015, 2020, 2023]:
        try:
            results["seasonal_ndvi"].append(compute_seasonal_ndvi(year, region))
        except Exception as e:
            print(f"    Seasonal NDVI {year} skipped: {e}")

    print("  Computing forest cover statistics (Hansen)...")
    try:
        results["forest_stats"] = compute_forest_stats(region)
    except Exception as e:
        print(f"    Forest stats skipped: {e}")

    print("  Computing annual forest loss (2001–2023)...")
    try:
        results["forest_loss_annual"] = compute_forest_loss_by_year(region)
    except Exception as e:
        print(f"    Forest loss annual skipped: {e}")

    print("  Detecting cropland extent (ESA WorldCover 2021)...")
    try:
        cropland = detect_cropland(region)
        crop_area = cropland.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(), geometry=region,
            scale=300 if cfg.SCOPE == "national" else 100, maxPixels=cfg.MAX_PIXELS, bestEffort=True,
        )
        results["cropland_area_km2"] = ee.Number(crop_area.get("cropland")).divide(1e6)
        results["cropland_mask"] = cropland
    except Exception as e:
        print(f"    Cropland detection skipped: {e}")

    return results
