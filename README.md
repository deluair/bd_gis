# Bangladesh Geospatial Analysis Pipeline

40-year satellite-based water body detection, river migration, flood mapping, and wetland change analysis for Bangladesh using Google Earth Engine.

## Study Area

Configurable scope via `--scope`:

| Scope | Coverage |
|-------|----------|
| `national` (default) | All 8 divisions of Bangladesh |
| `sylhet` | Sylhet Division haor wetlands |
| `<division>` | Any specific division (e.g., `dhaka`, `chittagong`) |

**Key features tracked:**
- **16 rivers**: Padma, Jamuna, Meghna, Brahmaputra, Ganges, Teesta, Surma, Kushiyara, Kalni, Kangsha, Gorai, Arial Khan, Dharla, Karnaphuli, Sangu, Matamuhuri
- **19 wetlands/haors**: Tanguar Haor (Ramsar), Hakaluki Haor, Sundarbans, Chalan Beel, and more
- **Extreme flood years**: 1987, 1988, 1998, 2004, 2007, 2017, 2020, 2022

## Data Sources

| Dataset | Period | Resolution |
|---------|--------|------------|
| Landsat 5/7/8/9 | 1985–2025 | 30m |
| Sentinel-2 | 2015–2025 | 10m |
| JRC Global Surface Water | 1984–2021 | 30m |
| SRTM DEM | — | 30m |

## Pipeline Modules

| Module | Description |
|--------|-------------|
| `config.py` | Study area bounds, river/haor definitions, band mappings, thresholds |
| `data_acquisition.py` | GEE auth, Landsat/Sentinel harmonization, cloud masking, compositing |
| `water_classification.py` | NDWI, MNDWI, AWEI indices + Otsu thresholding + majority voting |
| `river_analysis.py` | River centerline extraction, channel migration, erosion rates |
| `flood_analysis.py` | Monsoon/dry mapping, seasonal inundation, extreme flood analysis |
| `water_change.py` | Water occurrence frequency, permanent/seasonal/rare, decade-wise change |
| `haor_analysis.py` | Haor delineation, area tracking, seasonal cycles, period comparison |
| `visualization.py` | Interactive maps (geemap/folium), matplotlib figures |
| `export_utils.py` | GeoTIFF, Shapefile, CSV export helpers |
| `generate_report_maps.py` | Static publication-quality maps (PNG, 300 DPI) |
| `generate_pdf_report.py` | Automated PDF findings report |
| `tiling.py` | Tile-based processing for large areas |
| `run_pipeline.py` | Main orchestrator with CLI modes |

## Quick Start

```bash
pip install -r requirements.txt
python run_pipeline.py --test                       # Verify GEE auth + 2020 dry/monsoon test
python run_pipeline.py --full                       # Full 40-year analysis (national)
python run_pipeline.py --scope sylhet --full        # Sylhet-only analysis
```

## CLI Options

```
--scope SCOPE   Analysis scope: national | sylhet | <division name>
--test          Quick test (2020 dry vs monsoon)
--full          Full 40-year pipeline
--rivers        River erosion analysis only
--floods        Flood extent mapping only
--changes       Water change detection only
--haors         Haor/wetland analysis only
```

## Outputs

All outputs are saved to `outputs/`:

| Directory | Contents |
|-----------|----------|
| `outputs/rivers/` | Per-river erosion rate CSVs, trend charts (PNG), interactive migration maps (HTML) |
| `outputs/floods/` | Flood time series CSV and chart |
| `outputs/haors/` | Per-haor area timeseries, trend charts, boundary maps, period comparisons |
| `outputs/changes/` | Water persistence stats, change maps, before/after comparisons |
| `outputs/report_maps/` | 8 publication-quality static figures |
| `outputs/` | Master map, JRC overlay, multiyear comparison, findings report (HTML/MD/PDF) |

## Water Detection Method

1. Compute NDWI, MNDWI, AWEI for each composite
2. Apply Otsu auto-thresholding per scene per index
3. Majority voting: pixel = water if 2+ of 3 indices agree
