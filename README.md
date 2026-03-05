# Bangladesh Comprehensive Geospatial Analysis Platform

A multi-domain satellite-based geospatial analysis platform for Bangladesh, covering water resources, urbanization, poverty, nighttime lights, vegetation, air quality, climate, land cover, infrastructure, crop detection, slum mapping, coastal dynamics, soil analysis, health risk, and renewable energy — all powered by Google Earth Engine across 20+ satellite datasets spanning 1975–2025.

## Analysis Domains

| Domain | Module | Key Datasets | Period |
|--------|--------|-------------|--------|
| Water Detection | `water_classification.py` | Landsat 5/7/8/9, Sentinel-2 | 1985–2025 |
| River Migration | `river_analysis.py` | Landsat, JRC Water | 1985–2025 |
| Flood Mapping | `flood_analysis.py` | Landsat, Sentinel-2 | 1985–2025 |
| Water Change | `water_change.py` | Landsat, JRC Water | 1985–2025 |
| Wetland/Haor | `haor_analysis.py` | Landsat, SRTM DEM | 1985–2025 |
| Nighttime Lights | `nightlights.py` | DMSP-OLS, VIIRS DNB | 1992–2025 |
| Urbanization | `urbanization.py` | GHSL, Dynamic World | 1975–2025 |
| Vegetation | `vegetation.py` | MODIS NDVI/EVI, Hansen GFC | 2000–2025 |
| Land Cover | `land_cover.py` | MODIS, Dynamic World, ESA WorldCover | 2001–2025 |
| Air Quality | `air_quality.py` | Sentinel-5P TROPOMI | 2018–2025 |
| Climate | `climate.py` | CHIRPS, MODIS LST, ERA5 | 1981–2025 |
| Poverty Proxy | `poverty.py` | Lights + Pop + Built + NDVI | 2000–2020 |
| Infrastructure | `infrastructure.py` | Dynamic World, GHSL | 2015–2025 |
| Crop Detection | `crop_detection.py` | Landsat, MODIS NDVI, Dynamic World | 2000–2025 |
| Slum Mapping | `slum_mapping.py` | GHSL, VIIRS, MODIS LST, WorldPop | 2000–2020 |
| Coastal Analysis | `coastal.py` | Landsat, SRTM, ESA WorldCover, MODIS | 1985–2025 |
| Soil Analysis | `soil_analysis.py` | OpenLandMap, SRTM, CHIRPS | Static + annual |
| Health Risk | `health_risk.py` | MODIS LST, Sentinel-5P, WorldPop | 2000–2025 |
| Energy Potential | `energy.py` | ERA5, MODIS NDVI, VIIRS | 2000–2025 |

## Study Area

Configurable scope via `--scope`:

| Scope | Coverage |
|-------|----------|
| `national` (default) | All 8 divisions of Bangladesh |
| `sylhet` | Sylhet Division haor wetlands |
| `<division>` | Any specific division (e.g., `dhaka`, `chittagong`) |

**Geographic features tracked:**
- **16 rivers**: Padma, Jamuna, Meghna, Brahmaputra, Ganges, Teesta, Surma, Kushiyara, Kalni, Kangsha, Gorai, Arial Khan, Dharla, Karnaphuli, Sangu, Matamuhuri
- **19 wetlands/haors**: Tanguar Haor (Ramsar), Hakaluki Haor, Sundarbans, Chalan Beel, and more
- **10 urban centers**: Dhaka, Chittagong, Khulna, Rajshahi, Sylhet, Rangpur, Barishal, Comilla, Gazipur, Narayanganj
- **7 economic zones**: Dhaka EPZ, Chittagong EPZ, Mongla EPZ, and more
- **8 extreme flood years**: 1987, 1988, 1998, 2004, 2007, 2017, 2020, 2022
- **9 known slum areas**: Korail, Kamrangirchar, Mirpur, Bhashantek, and more
- **8 arsenic hotspots**: Chandpur, Comilla, Munshiganj, Gopalganj, and more
- **8 cyclone landfall points**: Sidr 2007, Aila 2009, Amphan 2020, Mocha 2023, and more
- **14 coastal districts**: Satkhira to Cox's Bazar

## Data Sources

| Dataset | Period | Resolution | Used For |
|---------|--------|------------|----------|
| Landsat 5/7/8/9 | 1985–2025 | 30m | Water, vegetation, construction |
| Sentinel-2 | 2015–2025 | 10m | Water, vegetation |
| JRC Global Surface Water | 1984–2021 | 30m | Water validation |
| SRTM / ALOS DEM | Static | 30m | Elevation, haor delineation |
| DMSP-OLS Nighttime Lights | 1992–2013 | 1km | Historical light intensity |
| VIIRS DNB Monthly | 2014–2025 | 500m | Modern light intensity |
| MODIS Land Cover (MCD12Q1) | 2001–2023 | 500m | LULC classification |
| Dynamic World | 2015–2025 | 10m | Near real-time LULC, construction |
| ESA WorldCover | 2020–2021 | 10m | High-res land cover, cropland |
| Copernicus Global Land Cover | 2015–2019 | 100m | LULC validation |
| MODIS NDVI/EVI (MOD13A2) | 2000–2025 | 1km | Vegetation health |
| Hansen Global Forest Change | 2000–2023 | 30m | Forest loss/gain |
| Sentinel-5P TROPOMI | 2018–2025 | 1.1km | NO2, SO2, CO, Aerosol, HCHO |
| MODIS LST (MOD11A2) | 2000–2025 | 1km | Temperature, urban heat island |
| CHIRPS Precipitation | 1981–2025 | 5.5km | Rainfall analysis |
| ERA5-Land | 1950–2025 | 11km | Climate reanalysis |
| WorldPop | 2000–2020 | 100m | Population density |
| GHSL Built Surface | 1975–2030 | 100m | Built-up area tracking |
| GHSL Settlement Model | 1975–2030 | 1km | Urban/rural classification |
| OpenLandMap Soils | Static | 250m | Soil properties |

## Quick Start

```bash
pip install -r requirements.txt

# Basic tests
python run_pipeline.py --test                       # GEE auth + water test
python run_pipeline.py --scope sylhet --test        # Fastest scope

# Individual modules
python run_pipeline.py --nightlights                # Nighttime lights only
python run_pipeline.py --urbanization               # Urbanization only
python run_pipeline.py --airquality                 # Air quality only
python run_pipeline.py --crops                      # Crop detection
python run_pipeline.py --coastal                    # Coastal & mangrove
python run_pipeline.py --health                     # Health risk mapping

# Full pipelines
python run_pipeline.py --full                       # All water modules
python run_pipeline.py --full-extended              # ALL modules
python run_pipeline.py --scope sylhet --full-extended
```

## CLI Options

```
--scope SCOPE       Analysis scope: national | sylhet | <division name>

Water Analysis (original):
  --test              Quick test (2020 dry vs monsoon)
  --full              Full 40-year water pipeline
  --rivers            River erosion analysis only
  --floods            Flood extent mapping only
  --changes           Water change detection only
  --haors             Haor/wetland analysis only

Extended Analysis:
  --nightlights       Nighttime lights & electrification
  --urbanization      Built-up area & urban sprawl
  --vegetation        NDVI/EVI, forest change, agriculture
  --landcover         LULC classification & change
  --airquality        Sentinel-5P pollutant mapping
  --climate           Rainfall, temperature, drought
  --poverty           Multi-indicator poverty proxy mapping
  --infrastructure    Construction change, economic zones

Domain-Specific Analysis:
  --crops             Crop detection & rice phenology
  --slums             Slum/informal settlement mapping
  --coastal           Coastal zone, mangrove, cyclone impact
  --soil              Soil properties, erosion, salinity
  --health            Health risk proxy mapping
  --energy            Renewable energy potential

Full Pipeline:
  --full-extended     Run ALL modules (water + extended + domain)
```

## Outputs

All outputs saved to `outputs/`:

| Directory | Contents |
|-----------|----------|
| `outputs/rivers/` | Per-river erosion rates, migration maps |
| `outputs/floods/` | Flood time series, extreme flood maps |
| `outputs/haors/` | Haor area trends, boundary maps |
| `outputs/changes/` | Water persistence, decade-wise change |
| `outputs/nightlights/` | Light time series, electrification maps, city stats |
| `outputs/urbanization/` | Built-up growth, expansion maps, settlement classification |
| `outputs/vegetation/` | NDVI trends, forest loss, cropland maps |
| `outputs/landcover/` | LULC time series, change maps |
| `outputs/airquality/` | Pollutant trends, hotspot maps, AQI composite |
| `outputs/climate/` | Rainfall/LST trends, UHI, drought maps |
| `outputs/poverty/` | Poverty index maps, division/district rankings |
| `outputs/infrastructure/` | Construction maps, economic zone growth, connectivity |
| `outputs/crops/` | Rice paddy maps, crop type classification, yield proxy |
| `outputs/slums/` | Slum index maps, known slum stats, growth tracking |
| `outputs/coastal/` | LECZ maps, shoreline change, mangrove health, cyclone impacts |
| `outputs/soil/` | Erosion risk, salinity zones, agricultural suitability |
| `outputs/health/` | Health risk index, waterlogging, heat stress, arsenic zones |
| `outputs/energy/` | Solar/wind potential, biomass proxy, energy access |
| `outputs/report_maps/` | Publication-quality static figures |

## Key Methodologies

**Water Detection:** NDWI + MNDWI + AWEI majority voting with Otsu auto-thresholding

**Poverty Proxy Index:** Composite of (1) nightlight deficit, (2) built-up deficit, (3) population-light gap, (4) vegetation stress — normalized and equally weighted

**Urban Heat Island:** Difference between urban core MODIS LST and surrounding rural ring LST

**Construction Detection:** Dynamic World class transitions to "built" class + spectral NDBI/NDVI change

**Drought Index:** Normalized rainfall anomaly (CHIRPS vs 30-year mean) combined with temperature anomaly (MODIS LST)

**Rice Paddy Detection:** Phenology-based: monsoon flooding (LSWI > 0) followed by NDVI greening (> 0.4), combined with LULC cropland mask

**Slum Index:** Weighted composite of building density, vegetation deficit, overcrowding, LST anomaly, and nightlight irregularity — masked to urban areas via GHSL SMOD

**Erosion Risk (RUSLE):** Simplified RUSLE: rainfall erosivity + soil erodibility (clay/SOC) + slope (SRTM) + vegetation cover (NDVI inverse)

**Health Risk Index:** Composite of waterlogging, heat stress, population exposure, air pollution, and vegetation deficit — weighted sum normalized to 0–1

**Energy Potential:** Solar (ERA5 shortwave radiation), wind (ERA5 10m u/v → speed³), biomass (NDVI²), energy access (nightlights × electrification)
