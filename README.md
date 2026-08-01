# Bangladesh Geospatial Analysis Platform

[![CI](https://github.com/deluair/bd_gis/actions/workflows/ci.yml/badge.svg)](https://github.com/deluair/bd_gis/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Satellite-based geospatial analysis of Bangladesh built on Google Earth Engine, covering water and flooding, river morphology, urbanisation, land cover, air quality, climate, agriculture, coastal change, and a set of socio-economic proxies. Analyses run at national scope, per division, or per district, over records reaching back to 1975.

The platform ships 28 Earth Engine analysis modules behind a single CLI, two more that run offline on downloaded rasters, and a validation subsystem that scores selected indicators against independent ground truth and assigns each one a quality tier.

## Honest scope

Not every output carries the same evidential weight, and the distinction matters more than the module count:

- **Measured.** Quantities read more or less directly off the sensor: water extent, built-up area, NDVI, land surface temperature, pollutant column densities, nighttime radiance.
- **Proxy.** Composite indices with no direct satellite observable behind them: the poverty index, slum index, health risk index, energy potential, erosion susceptibility. These are weighted combinations of measured layers. They are useful for ranking and screening, not for reporting levels.
- **Literature-based.** Arsenic hotspots, cyclone landfall points, and known slum locations are digitised from published sources, not detected from imagery.

Only indicators listed in `validation/registry.py` have been scored against independent reference data. Everything else is uncalibrated. See [Validation](#validation).

## Setup

Requires Python 3.10 or newer and a Google Cloud project with the Earth Engine API enabled.

```bash
git clone https://github.com/deluair/bd_gis.git
cd bd_gis
pip install -r requirements.txt
```

Earth Engine authentication, needed once per machine:

```bash
# 1. Register a Cloud project for Earth Engine at
#    https://code.earthengine.google.com/register
# 2. Authenticate:
earthengine authenticate
# 3. Point the pipeline at your project:
export GEE_PROJECT=your-cloud-project-id
```

`GEE_PROJECT` defaults to the original author's project, which you will not have access to, so setting it is effectively required. Scope can also be preset with `BD_GIS_SCOPE`.

## Quick start

```bash
python run_pipeline.py                              # default: quick water test
python run_pipeline.py --scope sylhet --test        # fastest scope, good smoke test
python run_pipeline.py --nightlights                # a single module
python run_pipeline.py --scope sylhet --floods      # a single module, scoped
python run_pipeline.py --district Comilla --poverty # single district
python run_pipeline.py --full                       # water modules
python run_pipeline.py --full-extended              # 23-module pipeline
```

Start with `--scope sylhet`. National-scope runs cover roughly 148,000 km2 and can take hours.

## Scope

| Scope | Coverage |
|-------|----------|
| `national` (default) | All 8 divisions |
| `sylhet` | Sylhet division haor wetlands, the original study area |
| `<division>` | Any single division, for example `dhaka`, `chittagong` |
| `--district <name>` | Any single district, for example `Comilla` |

National scope switches water thresholding from Otsu to fixed thresholds, because Otsu times out at that extent.

Reference geography carried in `config.py`: 16 rivers, 19 wetlands and haors, 10 urban centres, 7 economic zones, 14 coastal districts, 8 extreme flood years (1987, 1988, 1998, 2004, 2007, 2017, 2020, 2022), 9 known slum areas, 8 arsenic hotspots, and 8 cyclone landfall points.

## Analysis modules

### Water and hydrology

| Flag | Module | What it does |
|------|--------|--------------|
| `--test`, `--full` | `water_classification.py` | NDWI, MNDWI and AWEI with Otsu thresholding and majority voting |
| `--rivers` | `river_analysis.py` | Centreline extraction, channel migration, bank erosion and abandonment |
| `--floods` | `flood_analysis.py` | Monsoon and dry season extent, seasonal inundation, extreme flood years |
| `--sar` | `sar_flood.py` | Sentinel-1 SAR flood mapping, cloud-penetrating, all-weather |
| `--changes` | `water_change.py` | Water occurrence, persistence, decade-wise change |
| `--haors` | `haor_analysis.py` | Haor and wetland delineation and area tracking |
| `--chars` | `char_accretion.py` | Char (river island) formation and land accretion |
| `--groundwater` | `groundwater.py` | Groundwater storage depletion from GRACE gravity data |

### Land, climate and atmosphere

| Flag | Module | What it does |
|------|--------|--------------|
| `--nightlights` | `nightlights.py` | DMSP-OLS (1992–2013) and VIIRS DNB (2014+), electrification proxy |
| `--urbanization` | `urbanization.py` | GHSL built-up growth, settlement class, urban sprawl, NDBI |
| `--vegetation` | `vegetation.py` | MODIS NDVI and EVI trends, Hansen forest loss and gain |
| `--landcover` | `land_cover.py` | MODIS IGBP, Dynamic World, ESA WorldCover, Copernicus LULC |
| `--airquality` | `air_quality.py` | Sentinel-5P NO2, SO2, CO, aerosol index, HCHO |
| `--climate` | `climate.py` | CHIRPS rainfall, MODIS LST, urban heat island, drought index |
| `--soil` | `soil_analysis.py` | OpenLandMap soil properties, erosion susceptibility, salinity proxy |

### Agriculture, coast and settlement

| Flag | Module | What it does |
|------|--------|--------------|
| `--crops` | `crop_detection.py` | Rice phenology (aman, boro, aus), crop classification, yield proxy |
| `--aquaculture` | `aquaculture.py` | Shrimp and fish pond detection, mangrove-to-pond conversion |
| `--coastal` | `coastal.py` | Shoreline change, mangrove health, low elevation coastal zone |
| `--cyclones` | `cyclone_damage.py` | Pre and post cyclone vegetation loss and flooding |
| `--slums` | `slum_mapping.py` | Informal settlement index and growth tracking |
| `--infrastructure` | `infrastructure.py` | Construction change, economic zones, built-up density |
| `--transport` | `transportation.py` | Connectivity gaps from nightlights and population density |
| `--kilns` | `brick_kiln.py` | Brick kiln detection via thermal and spectral signature |

### Socio-economic proxies

| Flag | Module | What it does |
|------|--------|--------------|
| `--poverty` | `poverty.py` | Composite index: nightlight deficit, built-up deficit, population-light gap, vegetation stress |
| `--health` | `health_risk.py` | Composite index: waterlogging, heat stress, exposure, pollution, arsenic zones |
| `--energy` | `energy.py` | Solar irradiance, wind potential, biomass proxy, energy access |

### Cross-cutting

| Flag | Module | What it does |
|------|--------|--------------|
| `--alerts` | `change_alerts.py` | Year-over-year anomaly flags across domains, `--alerts-year` selects the year |
| `--timelapse` | `timelapse.py` | Yearly GIF animations for urban, NDVI, water and nightlights |
| `--local` | `local_compute.py`, `local_landcover.py` | Runs on locally downloaded rasters with no Earth Engine calls |

`--full-extended` runs 23 of these in three dependency-ordered parallel waves. It does **not** include cyclones, aquaculture, chars, timelapse or alerts; run those individually.

### Supporting code

| File | Role |
|------|------|
| `config.py` | Every dataset ID, boundary, threshold and reference location |
| `data_acquisition.py` | Earth Engine init, sensor harmonisation, cloud masking, compositing |
| `export_utils.py` | GeoTIFF, shapefile and CSV export |
| `visualization.py` | Interactive geemap and folium maps, matplotlib figures |
| `tiling.py` | Tiled processing for national-scale reductions |
| `run_pipeline.py` | CLI orchestrator |
| `run_divisions.py` | Runs the pipeline once per division |
| `download_local.py` | Fetches satellite products for offline computation |
| `generate_report_maps.py`, `generate_publication_maps.py` | Static 300 DPI figures |
| `generate_pdf_report.py` | Assembles the findings PDF |

### Survey and ground truth

These parse household survey and census microdata and do not call Earth Engine. Input files are not distributed with the repository.

| File | Source |
|------|--------|
| `hies_ground_truth.py` | HIES 2022 division poverty headcount (BBS Final Report, December 2023) |
| `hies_food_nutrition.py` | HIES 2022 food consumption, calories, expenditure |
| `dhs_health.py`, `dhs_wealth.py` | DHS child health, nutrition, and household wealth index |
| `ipums_poverty.py`, `ipums_demographics.py` | IPUMS International Bangladesh census, MPI and demographics |
| `calibrate_poverty.py` | Calibrates the satellite poverty index against HIES 2022 |

## Validation

`validation/` scores an indicator's per-unit output against independent reference data and writes a JSON validation card recording the statistics, the reference citation, and any caveats.

Quality tiers, from `validation/registry.py`:

| Tier | Continuous (Pearson r) | Categorical (overall accuracy) | Meaning |
|------|------------------------|-------------------------------|---------|
| A | r ≥ 0.80 | ≥ 0.85 | Validated against independent reference |
| B | r ≥ 0.50 | ≥ 0.70 | Calibrated, usable with stated error |
| C | below 0.50 | below 0.70 | Weak or uncalibrated |

Registered indicators:

| Indicator | Class | Reference |
|-----------|-------|-----------|
| Optical (Landsat) monsoon water extent, by division | measured | JRC Global Surface Water v1.4 Monthly History (Pekel et al. 2016) |
| Sentinel-1 SAR monsoon water extent, by division | measured | JRC Global Surface Water v1.4 Monthly History (Pekel et al. 2016) |
| Satellite poverty proxy | proxy | HIES 2022 division headcount ratio (BBS) |

The registry records a standing caveat on the optical comparison: JRC is itself Landsat-derived, so agreement there is partly circular and is not a fully independent validation. The SAR comparison is genuinely cross-sensor.

```bash
python -m validation.run gis_poverty_index \
  --predicted-csv outputs/poverty/poverty_by_division.csv \
  --unit-col division --value-col poverty_index
```

A test guard (`tests/test_coverage.py`) requires every registered indicator to have an implemented reference loader.

## Data sources

| Dataset | Earth Engine ID | Period | Resolution |
|---------|-----------------|--------|------------|
| Landsat 5/7/8/9 C2 L2 | `LANDSAT/LT05,LE07,LC08,LC09/C02/T1_L2` | 1985–2025 | 30 m |
| Sentinel-1 GRD | `COPERNICUS/S1_GRD` | 2014–2025 | 10 m |
| Sentinel-2 SR | `COPERNICUS/S2_SR_HARMONIZED` | 2015–2025 | 10 m |
| Sentinel-5P (NO2, SO2, CO, aerosol, HCHO) | `COPERNICUS/S5P/OFFL/L3_*` | 2018–2025 | 1.1 km |
| JRC Global Surface Water | `JRC/GSW1_4/GlobalSurfaceWater`, `/MonthlyHistory` | 1984–2021 | 30 m |
| Dynamic World | `GOOGLE/DYNAMICWORLD/V1` | 2015–2025 | 10 m |
| ESA WorldCover | `ESA/WorldCover/v100/2020`, `v200/2021` | 2020–2021 | 10 m |
| Copernicus Global Land Cover | `COPERNICUS/Landcover/100m/Prj/Global/V3` | 2015–2019 | 100 m |
| MODIS land cover / NDVI / LST | `MODIS/061/MCD12Q1`, `MOD13A2`, `MOD11A2` | 2000–2025 | 500 m, 1 km |
| GHSL built, population, settlement | `JRC/GHSL/P2023A/GHS_BUILT_S`, `GHS_POP`, `GHS_SMOD` | 1975–2030 | 100 m, 1 km |
| WorldPop | `WorldPop/GP/100m/pop` | 2000–2020 | 100 m |
| GPW v4.11 population density | `CIESIN/GPWv411/...` | 2015 | 1 km |
| CHIRPS daily precipitation | `UCSB-CHG/CHIRPS/DAILY` | 1981–2025 | 5.5 km |
| ERA5-Land monthly | `ECMWF/ERA5_LAND/MONTHLY_AGGR` | 1950–2025 | 11 km |
| GLDAS Noah | `NASA/GLDAS/V021/NOAH/G025/T3H` | 2000–2025 | 25 km |
| GRACE mascon | `NASA/GRACE/MASS_GRIDS/MASCON_CRI` | 2002–2017 | 0.5 deg |
| SRTM / ALOS AW3D30 DEM | `USGS/SRTMGL1_003`, `JAXA/ALOS/AW3D30/V3_2` | static | 30 m |
| OpenLandMap soils (clay, sand, SOC, pH) | `OpenLandMap/SOL/...` | static | 250 m |
| Mangroves | `LANDSAT/MANGROVE_FORESTS`, `projects/global-mangrove-watch/gmw-v3` | 2000, v3 | 30 m |

## Outputs

Everything lands in `outputs/`, which is gitignored. One subdirectory per domain (`rivers/`, `floods/`, `haors/`, `changes/`, `nightlights/`, `urbanization/`, `vegetation/`, `landcover/`, `airquality/`, `climate/`, `poverty/`, `infrastructure/`, `crops/`, `slums/`, `coastal/`, `soil/`, `health/`, `energy/`, `report_maps/`), holding CSV time series, GeoTIFFs, interactive HTML maps, and 300 DPI PNG figures.

## Key methodologies

**Water detection.** NDWI, MNDWI and AWEI combined by majority vote, with Otsu auto-thresholding at sub-national scope and fixed thresholds nationally.

**SAR flood detection.** Sentinel-1 VV backscatter below a conservative -17 dB threshold. The threshold biases toward under-detection.

**Urban heat island.** Urban core MODIS LST minus surrounding rural ring LST, with QA masking applied first, since LST fill values otherwise corrupt every statistic.

**Rice phenology.** Monsoon flooding (LSWI > 0) followed by NDVI greening (> 0.4), intersected with a cropland mask, per season: aman (Jul–Nov), boro (Dec–May), aus (Mar–Aug).

**Erosion susceptibility.** RUSLE-shaped combination of rainfall erosivity, soil erodibility, slope and vegetation cover. The output is a relative index, not a quantitative soil loss rate.

**Composite indices.** Poverty, slum, health risk and energy indices are normalised weighted sums of their inputs. Weights are heuristic and labelled as such in the source.

## Known limitations

- DMSP-OLS digital numbers (0–63) and VIIRS radiance are not comparable across the 2013/2014 boundary. `compute_light_change` raises rather than silently comparing them.
- GHSL epochs are 5-year; a request for 2017 snaps to 2015 or 2020, and the snap is logged.
- WorldPop ends at 2020, Sentinel-5P starts late 2018, Dynamic World starts 2015, GRACE mascon ends 2017.
- Slum mapping at 30 m Landsat resolution is a proxy, not identification of specific settlements.
- Arsenic zones are literature-based buffers, not satellite-derived.
- The pollutant stack mixes incomparable units and is a relative index only.
- `estimate_buildup_density` measures built-up area, not road length.
- FAO GAUL administrative boundaries do not exactly match official Bangladesh boundaries.
- Timeouts use `signal.SIGALRM`, which is Unix and macOS only.
- The largest braided rivers (Padma, Jamuna, Meghna, Brahmaputra) can return zero erosion because their channels exceed the analysis buffer width.

## Development

```bash
pip install -r requirements-dev.txt
pytest -q          # 26 tests, no Earth Engine credentials required
ruff check .
```

CI runs ruff, the test suite on Python 3.11 and 3.12, and an install-and-import check that imports every module against a clean `requirements.txt`.

The layout is deliberately flat: analysis modules live at the repository root and import `config as cfg`. See `CLAUDE.md` for conventions and `docs/CODEBASE_LEDGER.md` for architecture truths, known quirks, and open issues.

## Citation

```bibtex
@software{hossen_bd_gis,
  author  = {Hossen, Md Deluair},
  title   = {Bangladesh Geospatial Analysis Platform},
  url     = {https://github.com/deluair/bd_gis},
  license = {MIT}
}
```

Cite the underlying datasets separately. Each carries its own attribution requirements, and the Earth Engine catalogue entry for each collection states them.

## License

MIT, see [LICENSE](LICENSE). The license covers this source code only, not the satellite datasets it reads or any survey microdata you supply.
