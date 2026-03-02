"""
Configuration for Bangladesh Geospatial Analysis Pipeline.
Supports multiple scopes: 'sylhet' (original), 'national' (all Bangladesh),
or a specific division name (e.g., 'dhaka', 'chittagong').
"""
import os

# ── GEE Project ──────────────────────────────────────────────────────────────
GEE_PROJECT = "gen-lang-client-0432004086"

# ── Scope ────────────────────────────────────────────────────────────────────
# "sylhet" | "national" | division name (e.g. "dhaka", "chittagong")
# Can be overridden via CLI --scope or BD_GIS_SCOPE env var
SCOPE = os.environ.get("BD_GIS_SCOPE", "national")

# ── Country & Admin Boundaries ───────────────────────────────────────────────
COUNTRY_NAME = "Bangladesh"
COUNTRY_BOUNDARY_DATASET = "FAO/GAUL/2015/level0"
ADMIN_L1 = "FAO/GAUL/2015/level1"   # divisions
ADMIN_L2 = "FAO/GAUL/2015/level2"   # districts
ADMIN_BOUNDARIES = ADMIN_L2

# ── Divisions ────────────────────────────────────────────────────────────────
DIVISIONS = {
    "barishal":   {"center_lat": 22.70, "center_lon": 90.37},
    "chattogram": {"center_lat": 22.33, "center_lon": 91.83},
    "dhaka":      {"center_lat": 23.81, "center_lon": 90.41},
    "khulna":     {"center_lat": 22.82, "center_lon": 89.53},
    "mymensingh": {"center_lat": 24.75, "center_lon": 90.40},
    "rajshahi":   {"center_lat": 24.37, "center_lon": 88.60},
    "rangpur":    {"center_lat": 25.74, "center_lon": 89.25},
    "sylhet":     {"center_lat": 24.90, "center_lon": 91.87},
}

# ── Study Area Bounds ────────────────────────────────────────────────────────
SYLHET_BOUNDS = {
    "west": 90.5, "south": 24.0, "east": 92.2, "north": 25.2,
}
NATIONAL_BOUNDS = {
    "west": 88.0, "south": 20.5, "east": 92.7, "north": 26.7,
}

# Active bounds (resolved by scope)
STUDY_AREA_BOUNDS = SYLHET_BOUNDS if SCOPE == "sylhet" else NATIONAL_BOUNDS

# ── Districts ────────────────────────────────────────────────────────────────
SYLHET_DISTRICTS = ["Sunamganj", "Habiganj", "Moulvibazar", "Kishoreganj", "Netrokona"]
# None = load all from GAUL dynamically
DISTRICTS = SYLHET_DISTRICTS if SCOPE == "sylhet" else None

# ── Wetlands / Haors ────────────────────────────────────────────────────────
SYLHET_HAORS = {
    "Tanguar Haor":   {"lat": 25.10, "lon": 91.07, "radius": 10000},
    "Hakaluki Haor":  {"lat": 24.62, "lon": 92.05, "radius": 12000},
    "Hail Haor":      {"lat": 24.45, "lon": 91.80, "radius": 8000},
    "Shanir Haor":    {"lat": 24.95, "lon": 91.35, "radius": 6000},
    "Dekar Haor":     {"lat": 25.05, "lon": 90.95, "radius": 7000},
}

NATIONAL_WETLANDS = {
    # ── Sylhet division haors ──
    "Tanguar Haor":       {"lat": 25.10, "lon": 91.07, "radius": 10000},
    "Hakaluki Haor":      {"lat": 24.62, "lon": 92.05, "radius": 12000},
    "Hail Haor":          {"lat": 24.45, "lon": 91.80, "radius": 8000},
    "Shanir Haor":        {"lat": 24.95, "lon": 91.35, "radius": 6000},
    "Dekar Haor":         {"lat": 25.05, "lon": 90.95, "radius": 7000},
    # ── Rajshahi / northwest ──
    "Chalan Beel":        {"lat": 24.35, "lon": 89.15, "radius": 15000},
    "Barind Tract Beels": {"lat": 24.80, "lon": 88.65, "radius": 10000},
    # ── Dhaka / central ──
    "Arial Beel":         {"lat": 23.45, "lon": 90.25, "radius": 10000},
    "Beel Dakatia":       {"lat": 23.12, "lon": 90.20, "radius": 8000},
    "Meghna Floodplain":  {"lat": 23.60, "lon": 90.65, "radius": 12000},
    "Padma Char":         {"lat": 23.80, "lon": 89.70, "radius": 10000},
    # ── Mymensingh ──
    "Mohanganj Haor":     {"lat": 24.88, "lon": 90.68, "radius": 8000},
    # ── Rangpur / north ──
    "Teesta Floodplain":  {"lat": 25.80, "lon": 89.60, "radius": 12000},
    "Bangali River Wetlands": {"lat": 25.45, "lon": 89.10, "radius": 8000},
    # ── Khulna / southwest ──
    "Sundarbans East":    {"lat": 21.95, "lon": 89.75, "radius": 25000},
    "Sundarbans West":    {"lat": 21.80, "lon": 89.30, "radius": 25000},
    # ── Barishal / coastal ──
    "Nijhum Dwip":        {"lat": 22.04, "lon": 90.98, "radius": 10000},
    # ── Chittagong / southeast ──
    "Sonadia Island":     {"lat": 21.47, "lon": 91.85, "radius": 8000},
    "Teknaf Wetlands":    {"lat": 20.85, "lon": 92.28, "radius": 8000},
}

HAORS = SYLHET_HAORS if SCOPE == "sylhet" else NATIONAL_WETLANDS

# ── Rivers ───────────────────────────────────────────────────────────────────
SYLHET_RIVERS = {
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

NATIONAL_RIVERS = {
    # ── Sylhet rivers ──
    **SYLHET_RIVERS,
    # ── Major national rivers ──
    "Padma": {
        "points": [
            (24.07, 89.00), (23.80, 89.50), (23.55, 90.00),
            (23.45, 90.40), (23.20, 90.60),
        ],
        "buffer_m": 8000,
    },
    "Jamuna": {
        "points": [
            (25.40, 89.70), (25.00, 89.80), (24.50, 89.85),
            (24.10, 89.90), (23.80, 89.75),
        ],
        "buffer_m": 10000,
    },
    "Meghna": {
        "points": [
            (24.20, 91.15), (23.80, 90.80), (23.40, 90.65),
            (23.00, 90.60), (22.50, 90.85),
        ],
        "buffer_m": 8000,
    },
    "Brahmaputra": {
        "points": [
            (25.80, 89.80), (25.50, 89.70), (25.20, 89.75),
        ],
        "buffer_m": 10000,
    },
    "Teesta": {
        "points": [
            (26.10, 88.85), (25.80, 89.00), (25.50, 89.30),
            (25.30, 89.55),
        ],
        "buffer_m": 5000,
    },
    "Ganges": {
        "points": [
            (24.60, 88.20), (24.40, 88.50), (24.20, 88.80),
            (24.07, 89.00),
        ],
        "buffer_m": 8000,
    },
    "Karnaphuli": {
        "points": [
            (22.40, 91.85), (22.35, 91.75), (22.30, 91.65),
        ],
        "buffer_m": 5000,
    },
    "Gorai": {
        "points": [
            (23.70, 89.50), (23.40, 89.60), (23.00, 89.55),
        ],
        "buffer_m": 5000,
    },
    "Arial Khan": {
        "points": [
            (23.20, 90.30), (23.00, 90.25), (22.70, 90.20),
        ],
        "buffer_m": 5000,
    },
    "Dharla": {
        "points": [
            (25.85, 89.30), (25.65, 89.35), (25.50, 89.40),
        ],
        "buffer_m": 4000,
    },
    "Sangu": {
        "points": [
            (22.20, 92.10), (22.00, 92.00), (21.80, 91.95),
        ],
        "buffer_m": 4000,
    },
    "Matamuhuri": {
        "points": [
            (21.70, 92.20), (21.50, 92.15), (21.30, 92.10),
        ],
        "buffer_m": 4000,
    },
}

RIVERS = SYLHET_RIVERS if SCOPE == "sylhet" else NATIONAL_RIVERS

# ── Date Ranges ──────────────────────────────────────────────────────────────
ANALYSIS_START_YEAR = 1985
ANALYSIS_END_YEAR = 2025

DECADES = [1985, 1995, 2005, 2015, 2025]

EXTREME_FLOOD_YEARS = [1987, 1988, 1998, 2004, 2007, 2017, 2020, 2022]

# Seasons (month ranges, inclusive)
DRY_SEASON = (12, 2)     # December–February
MONSOON_SEASON = (7, 9)   # July–September

# ── Landsat Band Mappings ────────────────────────────────────────────────────
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
DEFAULT_NDWI_THRESHOLD = 0.0
DEFAULT_MNDWI_THRESHOLD = 0.0
DEFAULT_AWEI_THRESHOLD = 0.0

# Thresholding strategy: national scope uses fixed (Otsu timeouts on 148k km2)
DEFAULT_THRESHOLD_METHOD = "fixed" if SCOPE == "national" else "otsu"

# Water occurrence categories
PERMANENT_WATER_MIN = 0.75
SEASONAL_WATER_MIN = 0.25

# ── Export Settings ──────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
EXPORT_SCALE = 30
EXPORT_CRS = "EPSG:4326"
MAX_PIXELS = 1e12 if SCOPE == "national" else 1e10

# ── GEE Auxiliary Datasets ───────────────────────────────────────────────────
JRC_WATER = "JRC/GSW1_4/GlobalSurfaceWater"
JRC_MONTHLY = "JRC/GSW1_4/MonthlyHistory"
SRTM_DEM = "USGS/SRTMGL1_003"

# Haor elevation threshold
HAOR_MAX_ELEVATION = 20


# ── Scope Helper ─────────────────────────────────────────────────────────────
def set_scope(scope):
    """Reconfigure all scope-dependent globals. Called from run_pipeline.py."""
    global SCOPE, STUDY_AREA_BOUNDS, DISTRICTS, HAORS, RIVERS
    global MAX_PIXELS, DEFAULT_THRESHOLD_METHOD
    SCOPE = scope
    STUDY_AREA_BOUNDS = SYLHET_BOUNDS if scope == "sylhet" else NATIONAL_BOUNDS
    DISTRICTS = SYLHET_DISTRICTS if scope == "sylhet" else None
    HAORS = SYLHET_HAORS if scope == "sylhet" else NATIONAL_WETLANDS
    RIVERS = SYLHET_RIVERS if scope == "sylhet" else NATIONAL_RIVERS
    MAX_PIXELS = 1e12 if scope != "sylhet" else 1e10
    DEFAULT_THRESHOLD_METHOD = "fixed" if scope == "national" else "otsu"


def scope_label():
    """Human-readable label for the current scope."""
    if SCOPE == "sylhet":
        return "Sylhet Haor Wetlands"
    elif SCOPE == "national":
        return "Bangladesh"
    else:
        return f"{SCOPE.title()} Division, Bangladesh"
