# CLAUDE.md: Bangladesh Comprehensive Geospatial Analysis Platform

## Quick Reference

```bash
pip install -r requirements.txt
export GEE_PROJECT=your-cloud-project-id            # required; default is the author's project
python run_pipeline.py --test                       # Quick GEE auth + water test
python run_pipeline.py --full                       # Full water pipeline (original)
python run_pipeline.py --full-extended              # 23-module pipeline (NOT all 28)
python run_pipeline.py --scope sylhet --full        # Scoped to Sylhet
python run_pipeline.py --nightlights                # Single extended module

pip install -r requirements-dev.txt                 # adds pytest + ruff
pytest -q                                           # 26 tests, no GEE credentials needed
ruff check .                                        # config in ruff.toml
```

**Module flags:** `--rivers | --floods | --sar | --changes | --haors | --chars | --groundwater | --nightlights | --urbanization | --vegetation | --landcover | --airquality | --climate | --soil | --crops | --aquaculture | --coastal | --cyclones | --slums | --infrastructure | --transport | --kilns | --poverty | --health | --energy | --alerts | --timelapse`

**Pipeline flags:** `--test | --full | --full-extended | --local`

**Modifiers:** `--scope <national|sylhet|division>` | `--district <name>` | `--alerts-year <year>`

`--full-extended` runs 23 of the 28 GEE modules in three dependency waves. It excludes `--cyclones`, `--aquaculture`, `--chars`, `--timelapse` and `--alerts`; run those individually.

**Ledger:** read `docs/CODEBASE_LEDGER.md` before any audit or data-integrity investigation, and write findings back into it.

## Project Structure

Flat layout: all modules at project root, no `src/` directory.

```
# ── Configuration & Core ──
config.py               # ALL datasets, bounds, rivers, haors, urban centers, thresholds
data_acquisition.py     # GEE auth, Landsat/Sentinel harmonization, cloud masking, compositing
export_utils.py         # GeoTIFF, Shapefile, CSV export helpers
visualization.py        # Interactive maps (geemap/folium) + matplotlib figures
tiling.py               # Tile-based processing for national-scale areas
run_pipeline.py         # Main CLI orchestrator

# ── Water Analysis (original) ──
water_classification.py # NDWI/MNDWI/AWEI + Otsu thresholding + majority voting
river_analysis.py       # Centerline extraction, channel migration, erosion rates
flood_analysis.py       # Monsoon/dry mapping, seasonal inundation, extreme floods
sar_flood.py            # Sentinel-1 VV all-weather flood mapping (-17 dB, conservative)
water_change.py         # Water occurrence, persistence, decade-wise change
haor_analysis.py        # Haor/wetland delineation, area tracking
char_accretion.py       # Char (river island) formation, land accretion
groundwater.py          # GRACE mascon total water storage depletion (ends 2017)

# ── Extended Analysis ──
nightlights.py          # DMSP-OLS (1992-2013) + VIIRS DNB (2014+), electrification
urbanization.py         # GHSL built-up, settlement classification, urban sprawl, NDBI/BUI
vegetation.py           # MODIS NDVI/EVI, Hansen forest change, cropland, agriculture
land_cover.py           # MODIS IGBP, Dynamic World, ESA WorldCover, Copernicus LULC
air_quality.py          # Sentinel-5P NO2/SO2/CO/Aerosol/HCHO, pollution hotspots
climate.py              # CHIRPS rainfall, MODIS LST, UHI effect, drought index
poverty.py              # Multi-indicator poverty proxy (lights + pop + built + NDVI)
infrastructure.py       # Construction change, economic zones, road density, connectivity

# ── Domain-Specific Analysis ──
crop_detection.py       # Rice phenology (aman/boro/aus), multi-crop classification, yield proxy
slum_mapping.py         # Informal settlement detection, multi-indicator slum index, growth tracking
coastal.py              # Shoreline change, mangrove health, LECZ mapping, cyclone impact
soil_analysis.py        # OpenLandMap soil properties, RUSLE erosion risk, salinity, ag suitability
health_risk.py          # Waterlogging, heat stress, mosquito habitat, air pollution, arsenic zones
energy.py               # Solar irradiance, wind potential, biomass, energy access/poverty
cyclone_damage.py       # Pre/post cyclone NDVI loss and flooding
transportation.py       # Connectivity gaps from nightlights + population density
aquaculture.py          # Shrimp/fish pond detection, mangrove-to-pond conversion
brick_kiln.py           # Kiln detection via thermal + spectral signature
change_alerts.py        # Year-over-year anomaly flags across domains
timelapse.py            # Yearly GIF animations (getVideoThumbURL)

# ── Offline path (no GEE) ──
download_local.py       # Fetch satellite products for local computation
local_compute.py        # Analysis over downloaded rasters
local_landcover.py      # LULC classification from downloaded GeoTIFFs

# ── Survey & ground truth (no GEE; input files not in repo) ──
hies_ground_truth.py    # HIES 2022 division poverty headcount (BBS, Dec 2023)
hies_food_nutrition.py  # HIES 2022 food consumption, calories, expenditure
dhs_health.py           # DHS child health/nutrition indicators by division
dhs_wealth.py           # DHS wealth index from household recode (fixed-width .DAT)
ipums_poverty.py        # IPUMS Bangladesh census MPI
ipums_demographics.py   # IPUMS age pyramids, dependency ratios by district
calibrate_poverty.py    # Calibrate satellite poverty index against HIES 2022

# ── Validation ──
validation/registry.py  # Quality-tier thresholds + per-indicator registry
validation/run.py       # validate_indicator orchestrator + CLI
validation/reference.py # Ground-truth loaders (HIES + generic CSV)
validation/calibrate.py # Continuous + categorical agreement statistics
validation/card.py      # Validation card schema, writer, reader
tests/                  # 26 pytest tests over validation/, no GEE credentials needed

# ── Reports ──
generate_report_maps.py # Static publication-quality maps (PNG, 300 DPI)
generate_publication_maps.py # Publication figure set
generate_pdf_report.py  # Automated PDF findings report
generate_chapter_thumbnails.py # GEE thumbnails; writes OUTSIDE this repo (see ledger)
run_divisions.py        # Runs the pipeline once per division

# ── Outputs ──
outputs/                # rivers/ floods/ haors/ changes/ nightlights/ urbanization/
                        # vegetation/ landcover/ airquality/ climate/ poverty/
                        # infrastructure/ crops/ slums/ coastal/ soil/ health/
                        # energy/ report_maps/
```

## Satellite Data Sources (all in config.py)

| Dataset | Config Key | Period | Resolution | Used By |
|---------|-----------|--------|------------|---------|
| Landsat 5/7/8/9 | `LANDSAT_BANDS` | 1985-2025 | 30m | water, vegetation, infrastructure |
| Sentinel-2 | `SENTINEL2_BANDS` | 2015-2025 | 10m | water, vegetation |
| JRC Surface Water | `JRC_WATER` | 1984-2021 | 30m | validation |
| SRTM / ALOS DEM | `SRTM_DEM`, `ALOS_DEM` | static | 30m | elevation context |
| DMSP-OLS | `DMSP_OLS` | 1992-2013 | 1km | nightlights (historic) |
| VIIRS DNB | `VIIRS_DNB` | 2014-2025 | 500m | nightlights (modern) |
| MODIS Land Cover | `MODIS_LANDCOVER` | 2001-2023 | 500m | land cover |
| Dynamic World | `DYNAMIC_WORLD` | 2015-2025 | 10m | land cover, construction |
| ESA WorldCover | `ESA_WORLDCOVER` | 2020-2021 | 10m | land cover, cropland |
| MODIS NDVI/EVI | `MODIS_NDVI` | 2000-2025 | 1km | vegetation |
| Hansen Forest | `GLOBAL_FOREST_CHANGE` | 2000-2023 | 30m | forest loss/gain |
| Sentinel-5P | `SENTINEL5P` | 2018-2025 | 1.1km | air quality |
| MODIS LST | `MODIS_LST` | 2000-2025 | 1km | temperature, UHI |
| CHIRPS | `CHIRPS` | 1981-2025 | 5.5km | rainfall |
| ERA5 Land | `ERA5_LAND` | 1950-2025 | 11km | climate reanalysis |
| WorldPop | `WORLDPOP` | 2000-2020 | 100m | population density |
| GHSL Built | `GHSL_BUILT` | 1975-2030 | 100m | urbanization |
| GHSL SMOD | `GHSL_SMOD` | 1975-2030 | 1km | settlement classification |
| OpenLandMap Soil | `OPENLANDMAP_SOIL` | static | 250m | soil properties |

## Critical Domain Knowledge

### Scoping System
- `config.py` manages scope-dependent globals via `set_scope(scope)`
- Scopes: `national` (default), `sylhet`, or any division name
- **National scope uses `fixed` thresholds**: Otsu times out on 148k km2

### GEE Patterns
- All computation runs server-side via `ee.*`: operations are lazy
- `_resolve_ee()` in `run_pipeline.py` converts ee objects to Python with SIGALRM timeout
- Always use `bestEffort=True` and `maxPixels=cfg.MAX_PIXELS` on `reduceRegion()`
- National-scale reductions: `scale=300-1000`; sub-national: `scale=30-100`
- National water occurrence uses tiled processing via `tiling.py`
- GEE project: `cfg.GEE_PROJECT`, from the `GEE_PROJECT` env var, defaulting to `gen-lang-client-0432004086` (the author's project). Never hardcode it in a module.

### Geographic Reference Points
- **Urban centers** (`cfg.URBAN_CENTERS`): 10 cities with lat/lon/radius for focused analysis
- **Economic zones** (`cfg.ECONOMIC_ZONES`): 7 EPZs for industrial growth tracking
- **Rivers** (`cfg.RIVERS`): 16 rivers with centerline points and buffer widths
- **Wetlands** (`cfg.HAORS`): 19 haors/wetlands with center coords and radius

### Module Interaction Pattern
- `poverty.py` depends on: `nightlights.py`, `urbanization.py`, `vegetation.py`
- `infrastructure.py` depends on: `land_cover.py`, `urbanization.py`, `nightlights.py`, `vegetation.py`
- `slum_mapping.py` depends on: `urbanization.py`, `nightlights.py`, `vegetation.py`, `poverty.py`, `climate.py`
- `health_risk.py` depends on: `water_classification.py`, `air_quality.py`, `poverty.py`, `vegetation.py`, `land_cover.py`
- `crop_detection.py` depends on: `data_acquisition.py`, `vegetation.py`, `land_cover.py`
- `coastal.py` depends on: `water_classification.py`, `vegetation.py`, `land_cover.py`
- `energy.py` depends on: `vegetation.py`, `nightlights.py`, `poverty.py`, `land_cover.py`
- `soil_analysis.py` depends on: `vegetation.py`, `climate.py`
- `climate.py` is standalone (CHIRPS + MODIS LST)
- `air_quality.py` is standalone (Sentinel-5P only)
- All modules depend on: `config.py`, `data_acquisition.py`, `export_utils.py`

### Geographic Reference Data in Modules
- `slum_mapping.py`: `KNOWN_SLUM_AREAS`: 9 known slum locations (Dhaka, Chittagong, Khulna)
- `coastal.py`: `COASTAL_DISTRICTS`, `COASTAL_BOUNDS`, `CYCLONE_LANDFALL_POINTS` (8 cyclones)
- `health_risk.py`: `ARSENIC_HOTSPOTS`: 8 known high-arsenic groundwater zones
- `energy.py`: `SOLAR_RADIATION` config for ERA5 shortwave radiation

## Code Style & Conventions

- Python 3, flat layout, `import config as cfg` everywhere
- ALL dataset IDs and parameters live in `config.py`: never hardcode in modules
- Each analysis module has a `run_<name>_analysis(region)` entry point
- `run_pipeline.py` handles: GEE init, output dirs, ee.Number resolution, CSV export
- Error handling: try/except per feature, print failure message, continue pipeline
- Timeouts: `signal.SIGALRM`: 300s for getInfo, 600s per river
- Export filenames: lowercase, underscores, include year/period
- Maps: interactive `.html`, static `.png` at 300 DPI

## Common Pitfalls

- **Do NOT call `.getInfo()` on large images without `bestEffort=True`**
- **Do NOT use `otsu` at national scope**: computation timeouts
- **SIGALRM only works on Unix/macOS**: not Windows
- **ee.Image operations are lazy**: errors appear at `.getInfo()` / export time
- **DMSP and VIIRS have different radiance scales**: do not directly compare raw values across the 2013/2014 boundary
- **Dynamic World starts 2015**: no construction detection before that
- **GHSL epochs are 5-year intervals**: requesting 2017 snaps to 2015 or 2020
- **WorldPop ends at 2020**: poverty analysis clamps to available years
- **Sentinel-5P starts late 2018**: no air quality data before that
- **Rice phenology detection requires correct season dates**: aman (Jul-Nov), boro (Dec-May), aus (Mar-Aug)
- **GLCM texture (slum_mapping)** requires integer input: multiply reflectance by 10000 first
- **Coastal analysis uses its own `COASTAL_BOUNDS`**: not the full national extent
- **OpenLandMap soil is static**: no temporal analysis possible, depth bands: b0/b10/b30/b60/b100/b200
- **Arsenic/cyclone/slum locations are hardcoded**: update module constants when adding new zones
- **ERA5 wind uses u/v components**: wind speed = sqrt(u² + v²), not a direct band
- **DMSP DN (0-63) and VIIRS nW/cm2/sr require `_sensor_scale_range()`**: `compute_light_change` raises ValueError for cross-sensor comparisons
- **GHSL epoch snapping is logged**: both years snapping to same epoch triggers warning
- **OpenLandMap soil is static**: `climate_year` only affects CHIRPS/MODIS in soil_analysis
- **Slum mapping at 30m Landsat is a proxy**, not definitive identification
- **Arsenic zones are literature-based buffers**, not satellite-derived
- **`compute_pollutant_stack` (was `compute_aqi_composite`)** mixes incomparable units, result is relative index
- **`estimate_buildup_density` (was `estimate_road_density`)** measures built-up area, not roads
- **`channel_abandonment` / `bank_erosion` (was `eroded` / `accreted`)** in river_analysis
- **MODIS LST requires QA masking (`_mask_lst_quality`)**: fill values corrupt all LST stats
- **All S5P pollutants now QA-filtered**: NO2 >= 0.75, others >= 0.5
- **Water occurrence uses dry-season composites (Nov-Feb)**, not full-year
- **Crop detection includes aus rice (class 4-6)** alongside aman/boro
- **Erosion risk output is `erosion_susceptibility` index**, NOT quantitative RUSLE
- **Salinity output is `salinity_proxy`**, NOT EC measurement

## Config Changes

- `SOLAR_RADIATION` moved from energy.py to config.py
- `GMW_MANGROVE` added to config.py
- `GLOBAL_FOREST_CHANGE["max_loss_year"]` added
- `HAOR_MAX_ELEVATION` lowered from 20 to 12
- `NATIONAL_WETLANDS` entries now have `"type"` field
- Water index threshold citations added to config.py

## Renamed Functions/Params

| Old | New | Module |
|-----|-----|--------|
| `estimate_road_density` | `estimate_buildup_density` | infrastructure.py |
| `compute_aqi_composite` | `compute_pollutant_stack` | air_quality.py |
| `compute_erosion_risk(year=)` | `compute_erosion_risk(climate_year=)` | soil_analysis.py |
| `compute_ag_suitability(year=)` | `compute_ag_suitability(climate_year=)` | soil_analysis.py |

## When Modifying This Codebase

1. Read the target file AND `config.py` before making changes
2. New datasets: add config entry to `config.py`, create/update analysis module, add CLI flag to `run_pipeline.py`
3. New analysis module: follow the `run_<name>_analysis(region)` pattern, return dict of results
4. Preserve error handling: try/except per feature, print, continue
5. Keep GEE operations server-side, minimize `.getInfo()` calls
6. Test with `--scope sylhet` first (fastest), then national
7. Do not restructure into packages: flat layout is intentional
8. New geographic features: add to config dicts with lat, lon, radius/buffer_m
