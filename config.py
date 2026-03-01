"""
Configuration for Sylhet Haor Wetlands Geospatial Analysis Pipeline.
"""
import os

# ── GEE Project ──────────────────────────────────────────────────────────────
GEE_PROJECT = "gen-lang-client-0432004086"

# ── Study Area ───────────────────────────────────────────────────────────────
STUDY_AREA_BOUNDS = {
    "west": 90.5,
    "south": 24.0,
    "east": 92.2,
    "north": 25.2,
}

# Districts of interest
DISTRICTS = ["Sunamganj", "Habiganj", "Moulvibazar", "Kishoreganj", "Netrokona"]

# Major haor approximate centroids (lat, lon) and search radii (meters)
HAORS = {
    "Tanguar Haor": {"lat": 25.10, "lon": 91.07, "radius": 10000},
    "Hakaluki Haor": {"lat": 24.62, "lon": 92.05, "radius": 12000},
    "Hail Haor": {"lat": 24.45, "lon": 91.80, "radius": 8000},
    "Shanir Haor": {"lat": 24.95, "lon": 91.35, "radius": 6000},
    "Dekar Haor": {"lat": 25.05, "lon": 90.95, "radius": 7000},
}

# River corridors – approximate centerline points and buffer width (meters)
RIVERS = {
    "Surma": {
        "points": [
            (24.89, 91.87), (24.88, 91.60), (24.85, 91.40),
            (24.83, 91.20), (24.80, 91.00),
        ],
        "buffer_m": 5000,
    },
    "Kushiyara": {
        "points": [
            (24.60, 92.10), (24.55, 91.90), (24.50, 91.70),
            (24.48, 91.50), (24.45, 91.30),
        ],
        "buffer_m": 5000,
    },
    "Kalni": {
        "points": [(24.95, 90.85), (24.90, 90.75), (24.85, 90.65)],
        "buffer_m": 3000,
    },
    "Kangsha": {
        "points": [(25.00, 90.70), (24.95, 90.60), (24.90, 90.50)],
        "buffer_m": 3000,
    },
}

# ── Date Ranges ──────────────────────────────────────────────────────────────
ANALYSIS_START_YEAR = 1985
ANALYSIS_END_YEAR = 2025

# Decades for river channel migration analysis
DECADES = [1985, 1995, 2005, 2015, 2025]

# Extreme flood years for detailed analysis
EXTREME_FLOOD_YEARS = [1998, 2004, 2017, 2022]

# Seasons (month ranges, inclusive)
DRY_SEASON = (12, 2)    # December–February
MONSOON_SEASON = (7, 9)  # July–September

# ── Landsat Band Mappings ────────────────────────────────────────────────────
# Harmonized band names: blue, green, red, nir, swir1, swir2, qa
LANDSAT_BANDS = {
    "L5": {
        "original": ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7", "QA_PIXEL"],
        "renamed":  ["blue",  "green", "red",   "nir",   "swir1", "swir2", "qa"],
        "collection": "LANDSAT/LT05/C02/T1_L2",
        "scale_factor": 0.0000275,
        "scale_offset": -0.2,
    },
    "L7": {
        "original": ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7", "QA_PIXEL"],
        "renamed":  ["blue",  "green", "red",   "nir",   "swir1", "swir2", "qa"],
        "collection": "LANDSAT/LE07/C02/T1_L2",
        "scale_factor": 0.0000275,
        "scale_offset": -0.2,
    },
    "L8": {
        "original": ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7", "QA_PIXEL"],
        "renamed":  ["blue",  "green", "red",   "nir",   "swir1", "swir2", "qa"],
        "collection": "LANDSAT/LC08/C02/T1_L2",
        "scale_factor": 0.0000275,
        "scale_offset": -0.2,
    },
    "L9": {
        "original": ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7", "QA_PIXEL"],
        "renamed":  ["blue",  "green", "red",   "nir",   "swir1", "swir2", "qa"],
        "collection": "LANDSAT/LC09/C02/T1_L2",
        "scale_factor": 0.0000275,
        "scale_offset": -0.2,
    },
}

SENTINEL2_BANDS = {
    "original": ["B2", "B3", "B4", "B8", "B11", "B12", "QA60"],
    "renamed":  ["blue", "green", "red", "nir", "swir1", "swir2", "qa"],
    "collection": "COPERNICUS/S2_SR_HARMONIZED",
    "scale_factor": 0.0001,
}

# ── Water Index Thresholds ───────────────────────────────────────────────────
# Used as fallback when Otsu fails; normally Otsu computes per-scene thresholds
DEFAULT_NDWI_THRESHOLD = 0.0
DEFAULT_MNDWI_THRESHOLD = 0.0
DEFAULT_AWEI_THRESHOLD = 0.0

# Water occurrence categories (fraction of time classified as water)
PERMANENT_WATER_MIN = 0.75   # >75% = permanent
SEASONAL_WATER_MIN = 0.25    # 25-75% = seasonal
# <25% = rare/ephemeral

# ── Export Settings ──────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
EXPORT_SCALE = 30         # meters per pixel for Landsat exports
EXPORT_CRS = "EPSG:4326"  # WGS84
MAX_PIXELS = 1e10

# ── GEE Auxiliary Datasets ───────────────────────────────────────────────────
JRC_WATER = "JRC/GSW1_4/GlobalSurfaceWater"
JRC_MONTHLY = "JRC/GSW1_4/MonthlyHistory"
SRTM_DEM = "USGS/SRTMGL1_003"
ADMIN_BOUNDARIES = "FAO/GAUL/2015/level2"  # upazila-level for Bangladesh

# Haor elevation threshold – haors are depressions typically below this (meters)
HAOR_MAX_ELEVATION = 20
