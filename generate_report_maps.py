"""
Generate static map images for the findings report by downloading
actual GEE thumbnail tiles and composing them with matplotlib.
"""
import os
import sys
import io
import urllib.request
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from PIL import Image

# Setup
sys.path.insert(0, os.path.dirname(__file__))
import config as cfg

import ee
ee.Initialize(project=cfg.GEE_PROJECT)

from data_acquisition import (
    get_study_area, get_seasonal_composite, get_jrc_water, get_srtm_dem
)
from water_classification import classify_water
from water_change import compute_water_occurrence, classify_water_persistence

OUT = cfg.OUTPUT_DIR
os.makedirs(os.path.join(OUT, "report_maps"), exist_ok=True)

REGION = get_study_area()
DIMS = 1024  # thumbnail resolution


# ── Helpers ──────────────────────────────────────────────────────────────────

def fetch_thumb(ee_image, vis_params, region=None, dims=DIMS):
    """Download a GEE thumbnail and return as numpy array."""
    if region is None:
        region = REGION
    params = {**vis_params, "region": region, "dimensions": dims, "format": "png"}
    url = ee_image.getThumbURL(params)
    print(f"  Fetching: {url[:90]}...")
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    img = Image.open(io.BytesIO(data))
    return np.array(img)


def save_fig(fig, name):
    path = os.path.join(OUT, "report_maps", name)
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {path}")
    return path


# ── 1. Study Area Overview with DEM ─────────────────────────────────────────

def map_study_area():
    print("\n[1/8] Study area DEM overview...")
    dem = get_srtm_dem().clip(REGION)
    arr = fetch_thumb(dem, {"min": 0, "max": 50, "palette": [
        "006837", "1a9850", "66bd63", "a6d96a", "d9ef8b",
        "fee08b", "fdae61", "f46d43", "d73027"
    ]})

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(arr, extent=[90.5, 92.2, 24.0, 25.2], aspect="auto")
    ax.set_xlabel("Longitude (°E)", fontsize=11)
    ax.set_ylabel("Latitude (°N)", fontsize=11)
    ax.set_title("Sylhet Haor Wetlands – Study Area Elevation (SRTM)", fontsize=13)

    # Mark haors
    for name, h in cfg.HAORS.items():
        ax.plot(h["lon"], h["lat"], "ko", markersize=6)
        ax.annotate(name.replace(" Haor", ""), (h["lon"], h["lat"]),
                    xytext=(5, 5), textcoords="offset points", fontsize=8,
                    fontweight="bold", color="black",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.7))

    # Colorbar
    sm = plt.cm.ScalarMappable(cmap=plt.cm.RdYlGn_r, norm=plt.Normalize(0, 50))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.7, label="Elevation (m)")

    return save_fig(fig, "01_study_area_dem.png")


# ── 2. Seasonal Comparison (Dry vs Monsoon 2020) ────────────────────────────

def map_seasonal_comparison():
    print("\n[2/8] Seasonal comparison 2020...")
    dry_comp = get_seasonal_composite(2020, "dry", "landsat", REGION)
    dry_water = classify_water(dry_comp, region=REGION, method="fixed")

    mon_comp = get_seasonal_composite(2020, "monsoon", "landsat", REGION)
    mon_water = classify_water(mon_comp, region=REGION, method="fixed")

    # Composite: 0=land, 1=dry-only, 2=monsoon-only, 3=both
    combined = dry_water.add(mon_water.multiply(2)).clip(REGION)

    arr = fetch_thumb(combined, {
        "min": 0, "max": 3,
        "palette": ["e8e8e8", "08306b", "41b6c4", "253494"]
    })

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(arr, extent=[90.5, 92.2, 24.0, 25.2], aspect="auto")
    ax.set_xlabel("Longitude (°E)", fontsize=11)
    ax.set_ylabel("Latitude (°N)", fontsize=11)
    ax.set_title("Seasonal Water Extent – 2020", fontsize=13)

    legend_patches = [
        mpatches.Patch(color="#e8e8e8", label="Land"),
        mpatches.Patch(color="#08306b", label="Dry season only"),
        mpatches.Patch(color="#41b6c4", label="Monsoon season only"),
        mpatches.Patch(color="#253494", label="Both seasons (permanent)"),
    ]
    ax.legend(handles=legend_patches, loc="lower left", fontsize=9,
              framealpha=0.9)

    return save_fig(fig, "02_seasonal_comparison_2020.png")


# ── 3. JRC Water Occurrence ─────────────────────────────────────────────────

def map_jrc_occurrence():
    print("\n[3/8] JRC water occurrence...")
    jrc = get_jrc_water()
    occurrence = jrc.select("occurrence").divide(100).clip(REGION)

    arr = fetch_thumb(occurrence.selfMask(), {
        "min": 0, "max": 1,
        "palette": ["d4e7f7", "89c4e8", "3e8ec4", "1a5fa4", "08306b"]
    })

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(arr, extent=[90.5, 92.2, 24.0, 25.2], aspect="auto")
    ax.set_xlabel("Longitude (°E)", fontsize=11)
    ax.set_ylabel("Latitude (°N)", fontsize=11)
    ax.set_title("JRC Global Surface Water – Occurrence (1984–2021)", fontsize=13)

    sm = plt.cm.ScalarMappable(cmap=plt.cm.Blues, norm=plt.Normalize(0, 100))
    sm.set_array([])
    fig.colorbar(sm, ax=ax, shrink=0.7, label="Water Occurrence (%)")

    return save_fig(fig, "03_jrc_water_occurrence.png")


# ── 4. Water Persistence (Permanent/Seasonal/Rare) ──────────────────────────

def map_water_persistence():
    print("\n[4/8] Water persistence classification...")
    occurrence = compute_water_occurrence(1985, 2025, REGION)
    persistence = classify_water_persistence(occurrence)

    arr = fetch_thumb(persistence.selfMask().clip(REGION), {
        "min": 1, "max": 3,
        "palette": ["ffeda0", "41b6c4", "253494"]
    })

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(arr, extent=[90.5, 92.2, 24.0, 25.2], aspect="auto")
    ax.set_xlabel("Longitude (°E)", fontsize=11)
    ax.set_ylabel("Latitude (°N)", fontsize=11)
    ax.set_title("Water Persistence Classification (1985–2025)", fontsize=13)

    legend_patches = [
        mpatches.Patch(color="#ffeda0", label="Rare (<25% of time)"),
        mpatches.Patch(color="#41b6c4", label="Seasonal (25–75%)"),
        mpatches.Patch(color="#253494", label="Permanent (>75%)"),
    ]
    ax.legend(handles=legend_patches, loc="lower left", fontsize=9,
              framealpha=0.9)

    return save_fig(fig, "04_water_persistence.png")


# ── 5. Extreme Flood: 1988 vs 2004 ──────────────────────────────────────────

def map_extreme_floods():
    print("\n[5/8] Extreme flood years (1988 vs 2004)...")
    imgs = {}
    for year in [1988, 2004]:
        comp = get_seasonal_composite(year, "monsoon", "landsat", REGION)
        water = classify_water(comp, region=REGION, method="fixed")
        imgs[year] = water

    arr_1988 = fetch_thumb(imgs[1988].selfMask().clip(REGION), {
        "min": 0, "max": 1, "palette": ["ffffff", "d73027"]
    })
    arr_2004 = fetch_thumb(imgs[2004].selfMask().clip(REGION), {
        "min": 0, "max": 1, "palette": ["ffffff", "d73027"]
    })

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
    for ax, arr, year in [(ax1, arr_1988, 1988), (ax2, arr_2004, 2004)]:
        ax.imshow(arr, extent=[90.5, 92.2, 24.0, 25.2], aspect="auto")
        ax.set_xlabel("Longitude (°E)", fontsize=10)
        ax.set_ylabel("Latitude (°N)", fontsize=10)
        ax.set_title(f"Monsoon Flood Extent – {year}", fontsize=12)

    legend_patches = [
        mpatches.Patch(color="#d73027", label="Flooded"),
        mpatches.Patch(color="white", edgecolor="gray", label="Not flooded"),
    ]
    fig.legend(handles=legend_patches, loc="lower center", ncol=2, fontsize=10)
    plt.suptitle("Extreme Flood Comparison: 1988 (6,823 km²) vs 2004 (4,531 km²)",
                 fontsize=14, y=1.02)
    plt.tight_layout()
    return save_fig(fig, "05_extreme_floods_1988_2004.png")


# ── 6. Decadal Water Change ─────────────────────────────────────────────────

def map_decadal_change():
    print("\n[6/8] Decadal water change...")
    early = compute_water_occurrence(1985, 1999, REGION)
    late = compute_water_occurrence(2010, 2025, REGION)
    change = late.subtract(early).clip(REGION)

    arr = fetch_thumb(change, {
        "min": -0.5, "max": 0.5,
        "palette": ["d73027", "fc8d59", "fee08b", "ffffff",
                     "d9ef8b", "91cf60", "1a9850"]
    })

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(arr, extent=[90.5, 92.2, 24.0, 25.2], aspect="auto")
    ax.set_xlabel("Longitude (°E)", fontsize=11)
    ax.set_ylabel("Latitude (°N)", fontsize=11)
    ax.set_title("Water Occurrence Change: 1985–1999 vs 2010–2025", fontsize=13)

    sm = plt.cm.ScalarMappable(cmap=plt.cm.RdYlGn, norm=plt.Normalize(-50, 50))
    sm.set_array([])
    fig.colorbar(sm, ax=ax, shrink=0.7, label="Change in occurrence (%)")

    return save_fig(fig, "06_decadal_water_change.png")


# ── 7. River Corridors (Surma + Kushiyara water 2020) ────────────────────────

def map_river_corridors():
    print("\n[7/8] River corridors...")
    # Full study area with 2020 monsoon water
    comp = get_seasonal_composite(2020, "monsoon", "landsat", REGION)
    water = classify_water(comp, region=REGION, method="fixed")

    # Natural color composite (RGB = swir1, nir, green for false color water-enhanced)
    false_color = comp.select(["swir1", "nir", "green"]).clip(REGION)

    arr_bg = fetch_thumb(false_color, {
        "min": 0.0, "max": 0.3,
        "bands": ["swir1", "nir", "green"]
    })
    arr_water = fetch_thumb(water.selfMask().clip(REGION), {
        "min": 0, "max": 1, "palette": ["0000ff"]
    })

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(arr_bg, extent=[90.5, 92.2, 24.0, 25.2], aspect="auto")
    # Overlay water (transparent where white)
    water_rgba = arr_water.copy().astype(float) / 255.0
    mask = (arr_water[:, :, :3].sum(axis=2) < 600)  # non-white pixels
    water_overlay = np.zeros((*arr_water.shape[:2], 4))
    water_overlay[mask, 0] = 0.0
    water_overlay[mask, 1] = 0.4
    water_overlay[mask, 2] = 1.0
    water_overlay[mask, 3] = 0.7
    ax.imshow(water_overlay, extent=[90.5, 92.2, 24.0, 25.2], aspect="auto")

    # Mark rivers
    for name, r in cfg.RIVERS.items():
        pts = r["points"]
        lons = [p[1] for p in pts]
        lats = [p[0] for p in pts]
        ax.plot(lons, lats, "w--", linewidth=1.5, alpha=0.8)
        ax.annotate(name, (lons[0], lats[0]), fontsize=9, fontweight="bold",
                    color="white", bbox=dict(boxstyle="round", fc="black", alpha=0.5))

    ax.set_xlabel("Longitude (°E)", fontsize=11)
    ax.set_ylabel("Latitude (°N)", fontsize=11)
    ax.set_title("River Network & Monsoon Water Extent (2020)", fontsize=13)

    legend_patches = [
        mpatches.Patch(color="#0066ff", label="Water (monsoon 2020)"),
        mpatches.Patch(color="white", edgecolor="gray", label="River corridor"),
    ]
    ax.legend(handles=legend_patches, loc="lower left", fontsize=9, framealpha=0.9)

    return save_fig(fig, "07_river_corridors.png")


# ── 8. Multi-year water comparison (2000 vs 2010 vs 2020) ───────────────────

def map_multiyear():
    print("\n[8/8] Multi-year comparison (2000/2010/2020)...")
    years_colors = {2000: "d73027", 2010: "fc8d59", 2020: "3e8ec4"}
    arrs = {}
    for year in [2000, 2010, 2020]:
        comp = get_seasonal_composite(year, "monsoon", "landsat", REGION)
        water = classify_water(comp, region=REGION, method="fixed")
        arrs[year] = fetch_thumb(water.selfMask().clip(REGION), {
            "min": 0, "max": 1, "palette": ["ffffff", years_colors[year]]
        })

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    for ax, (year, arr) in zip(axes, arrs.items()):
        ax.imshow(arr, extent=[90.5, 92.2, 24.0, 25.2], aspect="auto")
        ax.set_xlabel("Longitude (°E)", fontsize=10)
        ax.set_ylabel("Latitude (°N)", fontsize=10)
        ax.set_title(f"Monsoon Water – {year}", fontsize=12)

    plt.suptitle("Monsoon Water Extent Across Decades", fontsize=14, y=1.02)
    plt.tight_layout()
    return save_fig(fig, "08_multiyear_comparison.png")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Generating report maps from GEE...\n")

    paths = []
    paths.append(map_study_area())
    paths.append(map_seasonal_comparison())
    paths.append(map_jrc_occurrence())
    paths.append(map_water_persistence())
    paths.append(map_extreme_floods())
    paths.append(map_decadal_change())
    paths.append(map_river_corridors())
    paths.append(map_multiyear())

    print(f"\nDone! Generated {len(paths)} map images.")
    for p in paths:
        print(f"  {p}")
