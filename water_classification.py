"""
Water classification module – spectral water indices, Otsu auto-thresholding,
and majority-voting ensemble classifier.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# Water Indices
# ═══════════════════════════════════════════════════════════════════════════════

def compute_ndwi(image):
    """NDWI = (Green - NIR) / (Green + NIR)"""
    return image.normalizedDifference(["green", "nir"]).rename("ndwi")


def compute_mndwi(image):
    """MNDWI = (Green - SWIR1) / (Green + SWIR1)"""
    return image.normalizedDifference(["green", "swir1"]).rename("mndwi")


def compute_awei(image):
    """
    AWEI (non-shadow) = 4*(Green - SWIR1) - (0.25*NIR + 2.75*SWIR2)
    Good for distinguishing water from built-up/shadow areas.
    """
    green = image.select("green")
    nir = image.select("nir")
    swir1 = image.select("swir1")
    swir2 = image.select("swir2")
    awei = (
        green.subtract(swir1).multiply(4)
        .subtract(nir.multiply(0.25).add(swir2.multiply(2.75)))
    )
    return awei.rename("awei")


def compute_water_indices(image):
    """Add NDWI, MNDWI, and AWEI bands to the image."""
    ndwi = compute_ndwi(image)
    mndwi = compute_mndwi(image)
    awei = compute_awei(image)
    return image.addBands([ndwi, mndwi, awei])


# ═══════════════════════════════════════════════════════════════════════════════
# Otsu Thresholding
# ═══════════════════════════════════════════════════════════════════════════════

def otsu_threshold(image, band_name, region, scale=30):
    """
    Compute Otsu's optimal threshold for a single-band image over a region.
    Uses GEE server-side histogram computation.
    Returns an ee.Number threshold.
    """
    histogram = image.select(band_name).reduceRegion(
        reducer=ee.Reducer.histogram(255, 2).combine("mean", sharedInputs=True),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )

    hist = ee.Dictionary(histogram.get(band_name + "_histogram"))
    counts = ee.Array(hist.get("histogram"))
    means = ee.Array(hist.get("bucketMeans"))

    total = counts.reduce(ee.Reducer.sum(), [0]).get([0])
    sum_all = counts.multiply(means).reduce(ee.Reducer.sum(), [0]).get([0])
    mean_all = ee.Number(sum_all).divide(total)

    size = means.length().get([0])
    indices = ee.List.sequence(0, ee.Number(size).subtract(1))

    def _compute_variance(index):
        index = ee.Number(index).int()
        aCounts = counts.slice(0, 0, index)
        aCount = aCounts.reduce(ee.Reducer.sum(), [0]).get([0])
        aMeans = means.slice(0, 0, index)
        aSum = aCounts.multiply(aMeans).reduce(ee.Reducer.sum(), [0]).get([0])
        aMean = ee.Number(ee.Algorithms.If(
            ee.Number(aCount).eq(0), 0,
            ee.Number(aSum).divide(aCount)
        ))
        bCount = ee.Number(total).subtract(aCount)
        bMean = ee.Number(ee.Algorithms.If(
            bCount.eq(0), 0,
            ee.Number(sum_all).subtract(aSum).divide(bCount)
        ))
        return (
            ee.Number(aCount).multiply(aMean.subtract(mean_all).pow(2))
            .add(bCount.multiply(bMean.subtract(mean_all).pow(2)))
        )

    bss = indices.map(_compute_variance)
    return means.sort(ee.Array(bss)).get([-1])


def otsu_threshold_safe(image, band_name, region, scale=30, default=0.0):
    """
    Otsu threshold with fallback to a default value if computation fails.
    """
    try:
        threshold = otsu_threshold(image, band_name, region, scale)
        return ee.Number(ee.Algorithms.If(
            ee.Algorithms.IsEqual(threshold, None),
            default,
            threshold
        ))
    except Exception:
        return ee.Number(default)


# ═══════════════════════════════════════════════════════════════════════════════
# Water Classification
# ═══════════════════════════════════════════════════════════════════════════════

def classify_water_fixed(image, ndwi_thresh=None, mndwi_thresh=None, awei_thresh=None):
    """
    Classify water using fixed thresholds and majority voting.
    A pixel is classified as water if at least 2 of 3 indices agree.
    """
    if ndwi_thresh is None:
        ndwi_thresh = cfg.DEFAULT_NDWI_THRESHOLD
    if mndwi_thresh is None:
        mndwi_thresh = cfg.DEFAULT_MNDWI_THRESHOLD
    if awei_thresh is None:
        awei_thresh = cfg.DEFAULT_AWEI_THRESHOLD

    img = compute_water_indices(image)
    ndwi_water = img.select("ndwi").gte(ndwi_thresh).rename("ndwi_water")
    mndwi_water = img.select("mndwi").gte(mndwi_thresh).rename("mndwi_water")
    awei_water = img.select("awei").gte(awei_thresh).rename("awei_water")

    # Majority voting: water if 2+ indices agree
    votes = ndwi_water.add(mndwi_water).add(awei_water)
    water_mask = votes.gte(2).rename("water")
    return water_mask


def classify_water_otsu(image, region, scale=30):
    """
    Classify water using Otsu auto-thresholding per index + majority voting.
    """
    img = compute_water_indices(image)

    ndwi_thresh = otsu_threshold_safe(img, "ndwi", region, scale, cfg.DEFAULT_NDWI_THRESHOLD)
    mndwi_thresh = otsu_threshold_safe(img, "mndwi", region, scale, cfg.DEFAULT_MNDWI_THRESHOLD)
    awei_thresh = otsu_threshold_safe(img, "awei", region, scale, cfg.DEFAULT_AWEI_THRESHOLD)

    ndwi_water = img.select("ndwi").gte(ndwi_thresh)
    mndwi_water = img.select("mndwi").gte(mndwi_thresh)
    awei_water = img.select("awei").gte(awei_thresh)

    votes = ndwi_water.add(mndwi_water).add(awei_water)
    water_mask = votes.gte(2).rename("water")
    return water_mask


def classify_water(image, region=None, scale=30, method=None):
    """
    Main entry point for water classification.
    method: 'otsu', 'fixed', or None (auto-select based on cfg.DEFAULT_THRESHOLD_METHOD)
    """
    if method is None:
        method = cfg.DEFAULT_THRESHOLD_METHOD
    if method == "otsu" and region is not None:
        return classify_water_otsu(image, region, scale)
    else:
        return classify_water_fixed(image)


def compute_water_area(water_mask, region, scale=30):
    """Compute total water area in square kilometers within a region."""
    pixel_area = water_mask.multiply(ee.Image.pixelArea())
    area = pixel_area.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=region,
        scale=scale,
        maxPixels=cfg.MAX_PIXELS,
        bestEffort=True,
    )
    return ee.Number(area.get("water")).divide(1e6)  # m² to km²
