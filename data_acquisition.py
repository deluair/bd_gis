"""
Data acquisition module – GEE authentication, image collection retrieval,
cloud masking, band harmonization, and composite generation.
"""
import ee
import config as cfg


# ═══════════════════════════════════════════════════════════════════════════════
# GEE Initialization
# ═══════════════════════════════════════════════════════════════════════════════

def init_gee():
    """Authenticate and initialize Google Earth Engine."""
    try:
        ee.Initialize(project=cfg.GEE_PROJECT)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=cfg.GEE_PROJECT)
    print("GEE initialized successfully.")


def get_country_boundary():
    """Return Bangladesh country boundary from FAO GAUL Level 0."""
    return (
        ee.FeatureCollection(cfg.COUNTRY_BOUNDARY_DATASET)
        .filter(ee.Filter.eq("ADM0_NAME", cfg.COUNTRY_NAME))
        .geometry()
    )


def get_division_boundary(division_name):
    """Return a division boundary from FAO GAUL Level 1."""
    return (
        ee.FeatureCollection(cfg.ADMIN_L1)
        .filter(ee.Filter.eq("ADM0_NAME", cfg.COUNTRY_NAME))
        .filter(ee.Filter.eq("ADM1_NAME", division_name))
        .geometry()
    )


def get_division_boundaries_all():
    """Return all division boundaries as a FeatureCollection."""
    return (
        ee.FeatureCollection(cfg.ADMIN_L1)
        .filter(ee.Filter.eq("ADM0_NAME", cfg.COUNTRY_NAME))
    )


def get_study_area():
    """Return ee.Geometry for the active study area based on scope."""
    if cfg.SCOPE == "national":
        return get_country_boundary()
    elif cfg.SCOPE in cfg.DIVISIONS:
        # Try to load division boundary; capitalize first letter
        div_name = cfg.SCOPE.title()
        return get_division_boundary(div_name)
    else:
        b = cfg.STUDY_AREA_BOUNDS
        return ee.Geometry.Rectangle([b["west"], b["south"], b["east"], b["north"]])


# ═══════════════════════════════════════════════════════════════════════════════
# Cloud Masking
# ═══════════════════════════════════════════════════════════════════════════════

def mask_landsat_clouds(image):
    """Mask clouds and cloud shadows using QA_PIXEL for Landsat C2 L2."""
    qa = image.select("qa")
    cloud_bit = 1 << 3
    shadow_bit = 1 << 4
    mask = qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(shadow_bit).eq(0))
    return image.updateMask(mask)


def mask_sentinel2_clouds(image):
    """Mask clouds using QA60 for Sentinel-2."""
    qa = image.select("qa")
    cloud_bit = 1 << 10
    cirrus_bit = 1 << 11
    mask = qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(cirrus_bit).eq(0))
    return image.updateMask(mask)


# ═══════════════════════════════════════════════════════════════════════════════
# Band Harmonization
# ═══════════════════════════════════════════════════════════════════════════════

def _harmonize_landsat(image, sensor_key):
    """Rename bands and apply surface reflectance scaling for a Landsat sensor."""
    band_info = cfg.LANDSAT_BANDS[sensor_key]
    renamed = image.select(band_info["original"], band_info["renamed"])
    # Scale optical bands (not QA)
    optical = renamed.select(["blue", "green", "red", "nir", "swir1", "swir2"])
    scaled = optical.multiply(band_info["scale_factor"]).add(band_info["scale_offset"])
    return scaled.addBands(renamed.select("qa")).copyProperties(image, image.propertyNames())


def _get_landsat_collection(sensor_key, start_date, end_date, region):
    """Load, filter, harmonize, and cloud-mask a single Landsat collection."""
    band_info = cfg.LANDSAT_BANDS[sensor_key]
    col = (
        ee.ImageCollection(band_info["collection"])
        .filterBounds(region)
        .filterDate(start_date, end_date)
    )
    col = col.map(lambda img: _harmonize_landsat(img, sensor_key))
    col = col.map(mask_landsat_clouds)
    return col


def get_landsat_collection(start_date, end_date, region=None):
    """
    Get merged, harmonized, cloud-masked Landsat collection spanning
    all available sensors (L5, L7, L8, L9) for the date range.
    """
    if region is None:
        region = get_study_area()

    start_year = int(start_date[:4])
    end_year = int(end_date[:4])

    collections = []
    # L5: 1984–2012
    if start_year <= 2012:
        l5_end = min(end_date, "2012-12-31")
        collections.append(_get_landsat_collection("L5", start_date, l5_end, region))
    # L7: 1999–2024 (SLC-off from 2003 but still useful for composites)
    if start_year <= 2024 and end_year >= 1999:
        l7_start = max(start_date, "1999-01-01")
        collections.append(_get_landsat_collection("L7", l7_start, end_date, region))
    # L8: 2013–present
    if end_year >= 2013:
        l8_start = max(start_date, "2013-04-01")
        collections.append(_get_landsat_collection("L8", l8_start, end_date, region))
    # L9: 2021–present
    if end_year >= 2021:
        l9_start = max(start_date, "2021-10-01")
        collections.append(_get_landsat_collection("L9", l9_start, end_date, region))

    if not collections:
        raise ValueError(f"No Landsat data available for {start_date} – {end_date}")

    merged = collections[0]
    for c in collections[1:]:
        merged = merged.merge(c)
    return merged


def get_sentinel2_collection(start_date, end_date, region=None):
    """Get cloud-masked, harmonized Sentinel-2 SR collection."""
    if region is None:
        region = get_study_area()

    s2_info = cfg.SENTINEL2_BANDS
    col = (
        ee.ImageCollection(s2_info["collection"])
        .filterBounds(region)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30))
    )

    def _harmonize_s2(image):
        renamed = image.select(s2_info["original"], s2_info["renamed"])
        optical = renamed.select(["blue", "green", "red", "nir", "swir1", "swir2"])
        scaled = optical.multiply(s2_info["scale_factor"])
        return scaled.addBands(renamed.select("qa")).copyProperties(image, image.propertyNames())

    col = col.map(_harmonize_s2)
    col = col.map(mask_sentinel2_clouds)
    return col


# ═══════════════════════════════════════════════════════════════════════════════
# Compositing
# ═══════════════════════════════════════════════════════════════════════════════

def make_composite(collection, method="median"):
    """Create a composite image from a collection."""
    optical_bands = ["blue", "green", "red", "nir", "swir1", "swir2"]
    col = collection.select(optical_bands)
    if method == "median":
        return col.median()
    elif method == "mean":
        return col.mean()
    elif method == "min":
        return col.min()
    elif method == "max":
        return col.max()
    else:
        raise ValueError(f"Unknown compositing method: {method}")


def get_seasonal_dates(year, season):
    """
    Return (start_date, end_date) strings for a season in a given year.
    Dry season (Dec-Feb) spans two calendar years.
    """
    if season == "dry":
        # Dec of previous year to Feb of current year
        return f"{year - 1}-12-01", f"{year}-02-28"
    elif season == "monsoon":
        return f"{year}-07-01", f"{year}-09-30"
    else:
        raise ValueError(f"Unknown season: {season}")


def get_seasonal_composite(year, season, sensor="landsat", region=None):
    """
    Generate a median composite for a given year and season.
    sensor: 'landsat' or 'sentinel2'
    """
    start_date, end_date = get_seasonal_dates(year, season)
    if sensor == "landsat":
        col = get_landsat_collection(start_date, end_date, region)
    elif sensor == "sentinel2":
        col = get_sentinel2_collection(start_date, end_date, region)
    else:
        raise ValueError(f"Unknown sensor: {sensor}")
    return make_composite(col)


# ═══════════════════════════════════════════════════════════════════════════════
# Auxiliary Datasets
# ═══════════════════════════════════════════════════════════════════════════════

def get_jrc_water():
    """Load JRC Global Surface Water dataset."""
    return ee.Image(cfg.JRC_WATER)


def get_jrc_monthly():
    """Load JRC Monthly Water History."""
    return ee.ImageCollection(cfg.JRC_MONTHLY)


def get_srtm_dem():
    """Load SRTM DEM."""
    return ee.Image(cfg.SRTM_DEM).select("elevation")


def get_admin_boundaries(country_name="Bangladesh"):
    """Load administrative boundaries (upazila level)."""
    return (
        ee.FeatureCollection(cfg.ADMIN_BOUNDARIES)
        .filter(ee.Filter.eq("ADM0_NAME", country_name))
    )


def get_district_boundaries(district_names=None):
    """Load district-level boundaries for specified districts."""
    if district_names is None:
        district_names = cfg.DISTRICTS
    admin = get_admin_boundaries()
    if district_names is None:
        # National scope: return all districts
        return admin
    return admin.filter(ee.Filter.inList("ADM1_NAME", district_names))
