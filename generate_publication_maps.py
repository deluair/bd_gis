"""
Generate publication-quality GIS maps for each research brief domain.
Uses Google Earth Engine to fetch real satellite imagery and overlay analysis results.
Output: PNG files in outputs/publication_maps/
"""
import os
import sys
import io
import urllib.request
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import config as cfg

import ee
ee.Initialize(project=cfg.GEE_PROJECT)

from data_acquisition import get_study_area

OUT = os.path.join(cfg.OUTPUT_DIR, "publication_maps")
os.makedirs(OUT, exist_ok=True)

REGION = get_study_area()
DIMS = 2048
BD_BOUNDS = cfg.NATIONAL_BOUNDS
EXTENT = [BD_BOUNDS["west"], BD_BOUNDS["east"], BD_BOUNDS["south"], BD_BOUNDS["north"]]


def fetch_thumb(ee_image, vis_params, region=None, dims=DIMS):
    if region is None:
        region = REGION
    params = {**vis_params, "region": region, "dimensions": dims, "format": "png"}
    url = ee_image.getThumbURL(params)
    print(f"  Fetching thumbnail...")
    with urllib.request.urlopen(url, timeout=180) as resp:
        data = resp.read()
    return np.array(Image.open(io.BytesIO(data)))


def save_fig(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="#0a0f1e", edgecolor="none")
    plt.close(fig)
    size_kb = os.path.getsize(path) // 1024
    print(f"  Saved: {path} ({size_kb} KB)")
    return path


def dark_style(ax, title):
    ax.set_facecolor("#0a0f1e")
    ax.set_title(title, fontsize=13, fontweight="bold", color="#e2e8f0", pad=10)
    ax.set_xlabel("Longitude", fontsize=9, color="#94a3b8")
    ax.set_ylabel("Latitude", fontsize=9, color="#94a3b8")
    ax.tick_params(colors="#64748b", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#1e293b")


# ── 1. Nightlights: VIIRS 2024 vs 2014 ──────────────────────────────────────

def map_nightlights_change():
    print("\n[1] Nightlights change 2014 vs 2024...")
    viirs = ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG")

    early = viirs.filterDate("2014-01-01", "2014-12-31").median().select("avg_rad").clip(REGION)
    late = viirs.filterDate("2024-01-01", "2024-12-31").median().select("avg_rad").clip(REGION)

    vis = {"min": 0, "max": 30, "palette": ["000000", "0a0a2e", "1a0a4e", "c4a35a", "ffffff"]}
    arr_early = fetch_thumb(early, vis)
    arr_late = fetch_thumb(late, vis)

    fig, axes = plt.subplots(1, 2, figsize=(16, 7), facecolor="#0a0f1e")
    for ax, arr, year in zip(axes, [arr_early, arr_late], ["2014", "2024"]):
        ax.imshow(arr, extent=EXTENT, aspect="auto")
        dark_style(ax, f"Nighttime Lights {year} (VIIRS DNB)")
    fig.suptitle("Bangladesh Electrification and Economic Activity: 2014 vs 2024",
                 fontsize=15, fontweight="bold", color="#c4a35a", y=0.98)
    fig.text(0.5, 0.01, "Source: NOAA VIIRS Day/Night Band", ha="center", fontsize=8, color="#64748b")
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    save_fig(fig, "nightlights_change_2014_2024.png")


# ── 2. NDVI vegetation health ────────────────────────────────────────────────

def map_ndvi():
    print("\n[2] NDVI vegetation health 2024...")
    modis = ee.ImageCollection("MODIS/061/MOD13A2")
    ndvi_2024 = (modis.filterDate("2024-01-01", "2024-12-31")
                 .select("NDVI").median().multiply(0.0001).clip(REGION))

    arr = fetch_thumb(ndvi_2024, {
        "min": 0, "max": 0.8,
        "palette": ["d73027", "f46d43", "fdae61", "fee08b", "d9ef8b",
                     "a6d96a", "66bd63", "1a9850", "006837"]
    })

    fig, ax = plt.subplots(figsize=(10, 8), facecolor="#0a0f1e")
    im = ax.imshow(arr, extent=EXTENT, aspect="auto")
    dark_style(ax, "Vegetation Health (NDVI) 2024")
    # Colorbar
    sm = plt.cm.ScalarMappable(cmap=plt.cm.RdYlGn, norm=plt.Normalize(0, 0.8))
    cb = fig.colorbar(sm, ax=ax, shrink=0.7, pad=0.02)
    cb.set_label("NDVI", color="#94a3b8", fontsize=10)
    cb.ax.tick_params(colors="#94a3b8")
    fig.text(0.5, 0.01, "Source: MODIS MOD13A2 (NASA)", ha="center", fontsize=8, color="#64748b")
    save_fig(fig, "ndvi_vegetation_2024.png")


# ── 3. Air quality: NO2 from Sentinel-5P ─────────────────────────────────────

def map_no2():
    print("\n[3] NO2 air quality 2024...")
    s5p = ee.ImageCollection("COPERNICUS/S5P/OFFL/L3_NO2")
    no2 = (s5p.filterDate("2023-01-01", "2023-12-31")
           .select("tropospheric_NO2_column_number_density")
           .mean().clip(REGION))

    arr = fetch_thumb(no2, {
        "min": 0, "max": 0.0001,
        "palette": ["1a9850", "91cf60", "d9ef8b", "fee08b", "fc8d59", "d73027", "a50026"]
    })

    fig, ax = plt.subplots(figsize=(10, 8), facecolor="#0a0f1e")
    ax.imshow(arr, extent=EXTENT, aspect="auto")
    dark_style(ax, "Tropospheric NO\u2082 Concentration 2024")
    sm = plt.cm.ScalarMappable(
        cmap=mcolors.LinearSegmentedColormap.from_list("", ["#1a9850", "#d9ef8b", "#fc8d59", "#a50026"]),
        norm=plt.Normalize(0, 100)
    )
    cb = fig.colorbar(sm, ax=ax, shrink=0.7, pad=0.02)
    cb.set_label("NO\u2082 (\u03bcmol/m\u00b2)", color="#94a3b8", fontsize=10)
    cb.ax.tick_params(colors="#94a3b8")
    fig.text(0.5, 0.01, "Source: Sentinel-5P TROPOMI (ESA/Copernicus)", ha="center", fontsize=8, color="#64748b")
    save_fig(fig, "no2_airquality_2024.png")


# ── 4. Coastal LECZ with elevation ───────────────────────────────────────────

def map_coastal_lecz():
    print("\n[4] Coastal low-elevation zones...")
    dem = ee.Image("USGS/SRTMGL1_003").clip(REGION)
    lecz_5m = dem.lte(5).selfMask()
    lecz_10m = dem.lte(10).selfMask()

    # Satellite basemap (Landsat true color)
    l8 = (ee.ImageCollection("LANDSAT/LC08/C02/T1_TOA")
          .filterDate("2023-01-01", "2023-12-31")
          .filterBounds(REGION)
          .sort("CLOUD_COVER").limit(20)
          .median().clip(REGION))

    base = fetch_thumb(l8, {"bands": ["B4", "B3", "B2"], "min": 0, "max": 0.3})
    lecz5_arr = fetch_thumb(lecz_5m, {"palette": ["ff000080"]})
    lecz10_arr = fetch_thumb(lecz_10m, {"palette": ["ffaa0060"]})

    fig, ax = plt.subplots(figsize=(10, 8), facecolor="#0a0f1e")
    ax.imshow(base, extent=EXTENT, aspect="auto")
    # Overlay LECZ (semi-transparent)
    ax.imshow(lecz10_arr, extent=EXTENT, aspect="auto", alpha=0.4)
    ax.imshow(lecz5_arr, extent=EXTENT, aspect="auto", alpha=0.5)
    dark_style(ax, "Low Elevation Coastal Zones (LECZ)")

    import matplotlib.patches as mpatches
    legend_elements = [
        mpatches.Patch(facecolor="#ff0000", alpha=0.5, label="Below 5m"),
        mpatches.Patch(facecolor="#ffaa00", alpha=0.4, label="Below 10m"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=9,
              facecolor="#111827", edgecolor="#1e293b", labelcolor="#e2e8f0")
    fig.text(0.5, 0.01, "Source: SRTM DEM (NASA/USGS), Landsat 8 (USGS)", ha="center", fontsize=8, color="#64748b")
    save_fig(fig, "coastal_lecz.png")


# ── 5. Urban built-up change ─────────────────────────────────────────────────

def map_urban_growth():
    print("\n[5] Urban built-up change 2000 vs 2020...")
    ghsl_2000 = (ee.Image("JRC/GHSL/P2023A/GHS_BUILT_S/2000")
                 .select("built_surface").gt(0).selfMask().clip(REGION))
    ghsl_2020 = (ee.Image("JRC/GHSL/P2023A/GHS_BUILT_S/2020")
                 .select("built_surface").gt(0).selfMask().clip(REGION))

    arr_2000 = fetch_thumb(ghsl_2000, {"palette": ["c4a35a"]})
    arr_2020 = fetch_thumb(ghsl_2020, {"palette": ["c4a35a"]})

    fig, axes = plt.subplots(1, 2, figsize=(16, 7), facecolor="#0a0f1e")
    for ax, arr, year in zip(axes, [arr_2000, arr_2020], ["2000", "2020"]):
        ax.imshow(arr, extent=EXTENT, aspect="auto")
        dark_style(ax, f"Built-Up Area {year} (GHSL)")
    fig.suptitle("Bangladesh Urban Expansion: 2000 vs 2020",
                 fontsize=15, fontweight="bold", color="#c4a35a", y=0.98)
    fig.text(0.5, 0.01, "Source: JRC Global Human Settlement Layer (EC/JRC)", ha="center", fontsize=8, color="#64748b")
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])
    save_fig(fig, "urban_growth_2000_2020.png")


# ── 6. Flood extent (monsoon vs dry) ─────────────────────────────────────────

def map_flood_extent():
    print("\n[6] Flood extent: dry vs monsoon 2023...")
    jrc = ee.Image("JRC/GSW1_4/GlobalSurfaceWater")
    occurrence = jrc.select("occurrence").clip(REGION)

    arr = fetch_thumb(occurrence, {
        "min": 0, "max": 100,
        "palette": ["ffffff", "d4e7f5", "89c0e8", "3690c0", "034e7b"]
    })

    fig, ax = plt.subplots(figsize=(10, 8), facecolor="#0a0f1e")
    ax.imshow(arr, extent=EXTENT, aspect="auto")
    dark_style(ax, "Surface Water Occurrence (1984-2021)")
    sm = plt.cm.ScalarMappable(cmap=plt.cm.Blues, norm=plt.Normalize(0, 100))
    cb = fig.colorbar(sm, ax=ax, shrink=0.7, pad=0.02)
    cb.set_label("% of time water present", color="#94a3b8", fontsize=10)
    cb.ax.tick_params(colors="#94a3b8")
    fig.text(0.5, 0.01, "Source: JRC Global Surface Water (EC/JRC)", ha="center", fontsize=8, color="#64748b")
    save_fig(fig, "water_occurrence.png")


# ── 7. Forest loss (Hansen) ──────────────────────────────────────────────────

def map_forest_loss():
    print("\n[7] Forest loss 2000-2023 (Hansen)...")
    gfc = ee.Image("UMD/hansen/global_forest_change_2023_v1_11").clip(REGION)
    tree_2000 = gfc.select("treecover2000").gte(30).selfMask()
    loss = gfc.select("lossyear").gt(0).selfMask()

    tree_arr = fetch_thumb(tree_2000, {"palette": ["006837"]})
    loss_arr = fetch_thumb(loss, {"palette": ["ff0000"]})

    fig, ax = plt.subplots(figsize=(10, 8), facecolor="#0a0f1e")
    ax.imshow(tree_arr, extent=EXTENT, aspect="auto")
    ax.imshow(loss_arr, extent=EXTENT, aspect="auto", alpha=0.7)
    dark_style(ax, "Forest Cover (2000) and Loss (2001-2023)")

    import matplotlib.patches as mpatches
    legend = [
        mpatches.Patch(facecolor="#006837", label="Forest 2000 (>30% canopy)"),
        mpatches.Patch(facecolor="#ff0000", alpha=0.7, label="Loss 2001-2023"),
    ]
    ax.legend(handles=legend, loc="upper left", fontsize=9,
              facecolor="#111827", edgecolor="#1e293b", labelcolor="#e2e8f0")
    fig.text(0.5, 0.01, "Source: Hansen/UMD/Google/USGS/NASA Global Forest Change", ha="center", fontsize=8, color="#64748b")
    save_fig(fig, "forest_loss_2000_2023.png")


# ── 8. Land surface temperature / UHI ────────────────────────────────────────

def map_lst():
    print("\n[8] Land surface temperature 2024...")
    modis_lst = ee.ImageCollection("MODIS/061/MOD11A2")
    lst = (modis_lst.filterDate("2024-03-01", "2024-05-31")
           .select("LST_Day_1km").median()
           .multiply(0.02).subtract(273.15).clip(REGION))

    arr = fetch_thumb(lst, {
        "min": 25, "max": 45,
        "palette": ["1a9850", "91cf60", "d9ef8b", "fee08b", "fc8d59", "d73027", "67001f"]
    })

    fig, ax = plt.subplots(figsize=(10, 8), facecolor="#0a0f1e")
    ax.imshow(arr, extent=EXTENT, aspect="auto")
    dark_style(ax, "Daytime Land Surface Temperature (Mar-May 2024)")
    sm = plt.cm.ScalarMappable(cmap=plt.cm.RdYlGn_r, norm=plt.Normalize(25, 45))
    cb = fig.colorbar(sm, ax=ax, shrink=0.7, pad=0.02)
    cb.set_label("Temperature (\u00b0C)", color="#94a3b8", fontsize=10)
    cb.ax.tick_params(colors="#94a3b8")
    fig.text(0.5, 0.01, "Source: MODIS MOD11A2 (NASA)", ha="center", fontsize=8, color="#64748b")
    save_fig(fig, "lst_temperature_2024.png")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    maps = {
        "nightlights": map_nightlights_change,
        "ndvi": map_ndvi,
        "no2": map_no2,
        "coastal": map_coastal_lecz,
        "urban": map_urban_growth,
        "flood": map_flood_extent,
        "forest": map_forest_loss,
        "lst": map_lst,
    }

    if len(sys.argv) > 1 and sys.argv[1] != "--all":
        targets = sys.argv[1:]
    else:
        targets = list(maps.keys())

    print(f"Generating {len(targets)} publication maps...")
    for name in targets:
        if name in maps:
            try:
                maps[name]()
            except Exception as e:
                print(f"  ERROR [{name}]: {e}")
        else:
            print(f"  Unknown map: {name}")
    print("\nDone.")
