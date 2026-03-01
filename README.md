# Sylhet Haor Wetlands Geospatial Analysis Pipeline

40-year satellite-based water body detection and change analysis for Bangladesh's Sylhet Division haor wetlands using Google Earth Engine.

## Study Area
- **Region**: Sylhet Division (Sunamganj, Habiganj, Moulvibazar, Kishoreganj, Netrokona)
- **Bounds**: 24.0°N–25.2°N, 90.5°E–92.2°E
- **Key haors**: Tanguar Haor (Ramsar), Hakaluki Haor, Hail Haor, Shanir Haor, Dekar Haor
- **Rivers**: Surma, Kushiyara, Kalni, Kangsha

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
| `config.py` | Study area bounds, band mappings, thresholds |
| `data_acquisition.py` | GEE auth, Landsat/Sentinel harmonization, cloud masking, compositing |
| `water_classification.py` | NDWI, MNDWI, AWEI indices + Otsu thresholding + majority voting |
| `river_analysis.py` | River centerline extraction, channel migration, erosion rates |
| `flood_analysis.py` | Monsoon/dry mapping, seasonal inundation, extreme flood analysis |
| `water_change.py` | Water occurrence frequency, permanent/seasonal/rare, decade-wise change |
| `haor_analysis.py` | Haor delineation, area tracking, seasonal cycles, period comparison |
| `visualization.py` | Interactive maps (geemap/folium), matplotlib figures |
| `export_utils.py` | GeoTIFF, Shapefile, CSV export helpers |
| `run_pipeline.py` | Main orchestrator with CLI modes |

## Quick Start

```bash
pip install -r requirements.txt
python run_pipeline.py --test    # Verify GEE auth + 2020 dry/monsoon test
python run_pipeline.py --full    # Full 40-year analysis
```

## CLI Options
```
--test      Quick test (2020 dry vs monsoon)
--full      Full 40-year pipeline
--rivers    River erosion analysis only
--floods    Flood extent mapping only
--changes   Water change detection only
--haors     Haor-specific analysis only
```

## Outputs (saved to `outputs/`)
- Interactive HTML maps with layer toggles
- GeoTIFF exports via Google Drive
- Time series CSVs (flood area, haor area, erosion rates)
- Matplotlib figures (PNG, 300 DPI)

## Water Detection Method
1. Compute NDWI, MNDWI, AWEI for each composite
2. Apply Otsu auto-thresholding per scene per index
3. Majority voting: pixel = water if 2+ of 3 indices agree
