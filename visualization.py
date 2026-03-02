"""
Visualization module – interactive maps (geemap/folium), time series plots,
change maps, and report-ready figures.
"""
import os
import ee
import geemap
import folium
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import config as cfg
from export_utils import ensure_output_dir


# ═══════════════════════════════════════════════════════════════════════════════
# Color Palettes
# ═══════════════════════════════════════════════════════════════════════════════

WATER_VIS = {"min": 0, "max": 1, "palette": ["white", "blue"]}
OCCURRENCE_VIS = {"min": 0, "max": 1, "palette": [
    "ffffff", "d4e7f7", "89c4e8", "3e8ec4", "1a5fa4", "08306b"
]}
PERSISTENCE_VIS = {"min": 0, "max": 3, "palette": [
    "ffffff", "ffeda0", "41b6c4", "253494"
]}
CHANGE_VIS = {"min": -1, "max": 1, "palette": [
    "d73027", "fee08b", "ffffff", "d9ef8b", "1a9850"
]}
EROSION_VIS = {"min": 0, "max": 4, "palette": [
    "ffffff", "fed976", "fd8d3c", "e31a1c", "800026"
]}
DEM_VIS = {"min": 0, "max": 50, "palette": [
    "006837", "1a9850", "66bd63", "a6d96a", "d9ef8b",
    "fee08b", "fdae61", "f46d43", "d73027"
]}


# ═══════════════════════════════════════════════════════════════════════════════
# Interactive Maps
# ═══════════════════════════════════════════════════════════════════════════════

def create_base_map(center=None, zoom=None):
    """Create a geemap Map centered on the study area."""
    if center is None:
        b = cfg.STUDY_AREA_BOUNDS
        center = [(b["south"] + b["north"]) / 2, (b["west"] + b["east"]) / 2]
    if zoom is None:
        zoom = 7 if cfg.SCOPE == "national" else 9
    m = geemap.Map(center=center, zoom=zoom)
    return m


def add_water_layer(m, water_image, name="Water", vis_params=None):
    """Add a water mask layer to the map."""
    if vis_params is None:
        vis_params = WATER_VIS
    m.addLayer(water_image.selfMask(), vis_params, name)
    return m


def add_occurrence_layer(m, occurrence_image, name="Water Occurrence"):
    """Add water occurrence frequency layer."""
    m.addLayer(occurrence_image.selfMask(), OCCURRENCE_VIS, name)
    return m


def add_persistence_layer(m, persistence_image, name="Water Persistence"):
    """Add water persistence classification layer."""
    m.addLayer(persistence_image.selfMask(), PERSISTENCE_VIS, name)
    return m


def add_change_layer(m, change_image, name="Water Change"):
    """Add water gain/loss change layer."""
    m.addLayer(change_image, CHANGE_VIS, name)
    return m


def create_water_comparison_map(dry_water, monsoon_water, year):
    """
    Create a map comparing dry and monsoon season water extent.
    """
    m = create_base_map()
    m.addLayer(
        dry_water.selfMask(),
        {"min": 0, "max": 1, "palette": ["white", "darkblue"]},
        f"Dry Season {year}"
    )
    m.addLayer(
        monsoon_water.selfMask(),
        {"min": 0, "max": 1, "palette": ["white", "cyan"]},
        f"Monsoon Season {year}"
    )
    m.addLayerControl()
    return m


def create_temporal_map(water_masks_by_year, name_prefix="Water"):
    """
    Create a map with multiple year layers and layer control for toggling.
    """
    m = create_base_map()
    colors = plt.cm.viridis(np.linspace(0, 1, len(water_masks_by_year)))

    for i, (year, mask) in enumerate(sorted(water_masks_by_year.items())):
        color = "#{:02x}{:02x}{:02x}".format(
            int(colors[i][0] * 255), int(colors[i][1] * 255), int(colors[i][2] * 255)
        )
        m.addLayer(
            mask.selfMask(),
            {"min": 0, "max": 1, "palette": ["white", color]},
            f"{name_prefix} {year}"
        )

    m.addLayerControl()
    return m


def create_river_migration_map(centerlines, water_masks, river_name):
    """Create a map showing river centerline migration across decades."""
    m = create_base_map()
    decade_colors = {
        1985: "red", 1995: "orange", 2005: "yellow", 2015: "green", 2025: "blue"
    }

    for year, mask in sorted(water_masks.items()):
        color = decade_colors.get(year, "gray")
        m.addLayer(
            mask.selfMask(),
            {"min": 0, "max": 1, "palette": ["white", color]},
            f"{river_name} Water {year}",
            shown=False,
        )

    for year, cl in sorted(centerlines.items()):
        color = decade_colors.get(year, "gray")
        m.addLayer(
            cl.selfMask(),
            {"min": 0, "max": 1, "palette": [color]},
            f"{river_name} Centerline {year}",
        )

    m.addLayerControl()
    return m


def create_haor_map(haor_boundaries, dem=None):
    """Create a map showing all haor boundaries with DEM context."""
    m = create_base_map()

    if dem is not None:
        m.addLayer(dem, DEM_VIS, "Elevation (SRTM)", shown=False)

    colors = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00"]
    for i, (name, boundary) in enumerate(haor_boundaries.items()):
        color = colors[i % len(colors)]
        # Cast to uint8 to ensure clean rendering
        m.addLayer(
            boundary.selfMask().toUint8(),
            {"min": 0, "max": 1, "palette": [color]},
            name,
        )

    m.addLayerControl()
    return m


def save_map(m, filename, subdir=None):
    """Save a geemap/folium map as HTML."""
    out_dir = ensure_output_dir(subdir)
    filepath = os.path.join(out_dir, filename)
    m.to_html(filepath)
    print(f"  Saved map: {filepath}")
    return filepath


# ═══════════════════════════════════════════════════════════════════════════════
# Matplotlib Figures
# ═══════════════════════════════════════════════════════════════════════════════

def plot_flood_time_series(time_series, save_path=None):
    """
    Plot annual dry, monsoon, and seasonal flood areas over time.
    time_series: list of {year, dry_area_km2, monsoon_area_km2, seasonal_area_km2}
    """
    years = [ts["year"] for ts in time_series]
    dry = [ts["dry_area_km2"] for ts in time_series]
    monsoon = [ts["monsoon_area_km2"] for ts in time_series]
    seasonal = [ts["seasonal_area_km2"] for ts in time_series]

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(years, dry, "o-", color="brown", label="Dry Season Water", markersize=4)
    ax.plot(years, monsoon, "s-", color="blue", label="Monsoon Water", markersize=4)
    ax.fill_between(years, dry, monsoon, alpha=0.2, color="cyan", label="Seasonal Inundation")

    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Water Area (km²)", fontsize=12)
    ax.set_title(f"{cfg.scope_label()} – Seasonal Water Extent (1985–2025)", fontsize=14)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")
        print(f"  Saved figure: {save_path}")
    return fig


def plot_haor_area_trends(haor_timeseries, save_path=None):
    """
    Plot area trends for multiple haors.
    haor_timeseries: dict {haor_name: [{year, area_km2}, ...]}
    """
    fig, ax = plt.subplots(figsize=(14, 6))

    for name, series in haor_timeseries.items():
        years = [s["year"] for s in series]
        areas = [s["area_km2"] for s in series]
        ax.plot(years, areas, "o-", label=name, markersize=4)

    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Water Area (km²)", fontsize=12)
    ax.set_title("Major Haor Water Area Trends", fontsize=14)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")
        print(f"  Saved figure: {save_path}")
    return fig


def plot_erosion_rates(erosion_data, river_name, save_path=None):
    """
    Bar chart of erosion rates by period for a river.
    erosion_data: list of {period, rate_ha_per_year}
    """
    periods = [d["period"] for d in erosion_data]
    rates = [d["rate_ha_per_year"] for d in erosion_data]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(periods, rates, color="firebrick", edgecolor="black")
    ax.set_xlabel("Period", fontsize=12)
    ax.set_ylabel("Erosion Rate (ha/year)", fontsize=12)
    ax.set_title(f"{river_name} – Bank Erosion Rates", fontsize=14)
    ax.grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")
        print(f"  Saved figure: {save_path}")
    return fig


def plot_seasonal_cycle(monthly_data, haor_name, save_path=None):
    """
    Plot monthly water area cycle for a haor.
    monthly_data: dict {month: [area_km2 values]}
    """
    months = list(range(1, 13))
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    fig, ax = plt.subplots(figsize=(10, 5))

    means = []
    stds = []
    for m in months:
        vals = monthly_data.get(m, [])
        if vals:
            means.append(np.mean(vals))
            stds.append(np.std(vals))
        else:
            means.append(0)
            stds.append(0)

    ax.fill_between(months, np.array(means) - np.array(stds),
                    np.array(means) + np.array(stds), alpha=0.2, color="blue")
    ax.plot(months, means, "o-", color="blue", markersize=6)
    ax.set_xticks(months)
    ax.set_xticklabels(month_labels)
    ax.set_xlabel("Month", fontsize=12)
    ax.set_ylabel("Water Area (km²)", fontsize=12)
    ax.set_title(f"{haor_name} – Average Seasonal Filling Cycle", fontsize=14)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")
        print(f"  Saved figure: {save_path}")
    return fig


def plot_period_comparison(comparison_data, save_path=None):
    """
    Grouped bar chart comparing pre-2000 vs post-2000 haor areas.
    comparison_data: dict {haor_name: {period1_avg_km2, period2_avg_km2, ...}}
    """
    # Filter out entries with None values
    names = [n for n in comparison_data
             if comparison_data[n].get("period1_avg_km2") is not None
             and comparison_data[n].get("period2_avg_km2") is not None]
    if not names:
        print("  No valid comparison data to plot.")
        return None
    p1_areas = [comparison_data[n]["period1_avg_km2"] for n in names]
    p2_areas = [comparison_data[n]["period2_avg_km2"] for n in names]

    x = np.arange(len(names))
    width = 0.35

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar(x - width / 2, p1_areas, width, label="Pre-2000", color="steelblue")
    ax.bar(x + width / 2, p2_areas, width, label="Post-2000", color="coral")

    ax.set_ylabel("Avg. Monsoon Water Area (km²)", fontsize=12)
    ax.set_title("Haor Area: Pre-2000 vs Post-2000", fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=15, ha="right")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")
        print(f"  Saved figure: {save_path}")
    return fig


def create_change_figure(early_water, late_water, early_label, late_label,
                         region=None, save_path=None):
    """
    Side-by-side change map figure (1985 vs 2025 style).
    Uses geemap thumbnail export.
    """
    if region is None:
        b = cfg.STUDY_AREA_BOUNDS
        region = ee.Geometry.Rectangle([b["west"], b["south"], b["east"], b["north"]])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))

    # Generate thumbnails via GEE
    for ax, water, label in [(ax1, early_water, early_label), (ax2, late_water, late_label)]:
        url = water.selfMask().getThumbURL({
            "min": 0, "max": 1,
            "palette": ["white", "blue"],
            "region": region,
            "dimensions": 800,
        })
        ax.set_title(label, fontsize=14)
        ax.text(0.5, 0.5, f"View at:\n{url[:80]}...",
                transform=ax.transAxes, ha="center", va="center", fontsize=8)
        ax.axis("off")

    # Add legend
    legend_patches = [
        mpatches.Patch(color="blue", label="Water"),
        mpatches.Patch(color="white", edgecolor="black", label="Land"),
    ]
    fig.legend(handles=legend_patches, loc="lower center", ncol=2, fontsize=11)

    plt.suptitle("Water Extent Change", fontsize=16, y=1.02)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")
        print(f"  Saved figure: {save_path}")
    return fig
