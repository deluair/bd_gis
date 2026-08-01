"""Generate Google Earth Engine thumbnails for the Satellite Bangladesh series.

Produces five JPG thumbnails (one per chapter) at app/web/static/satellite/.
Each thumbnail is sourced from real GEE imagery, no fabricated visuals.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import ee

import config as cfg

ee.Initialize(project=cfg.GEE_PROJECT)

OUT = Path(__file__).resolve().parent.parent / "app" / "web" / "static" / "satellite"
OUT.mkdir(parents=True, exist_ok=True)

BD_BOUNDS = ee.Geometry.Rectangle([88.0, 20.5, 92.7, 26.7])
DIM = "1200x800"


def fetch(url: str, path: Path) -> None:
    print(f"  → {path.name}")
    req = urllib.request.Request(url, headers={"User-Agent": "bdpolicylab"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())


def drowning() -> None:
    def mask_s2(img):
        scl = img.select("SCL")
        good = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
        return img.updateMask(good)

    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(BD_BOUNDS)
        .filterDate("2020-07-01", "2020-09-30")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 70))
        .map(mask_s2)
        .median()
        .clip(BD_BOUNDS)
    )
    url = s2.getThumbURL(
        {
            "bands": ["B4", "B3", "B2"],
            "min": 0,
            "max": 2800,
            "gamma": 1.25,
            "dimensions": DIM,
            "format": "jpg",
            "region": BD_BOUNDS,
        }
    )
    fetch(url, OUT / "drowning.jpg")


def glowing() -> None:
    viirs = (
        ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG")
        .filterDate("2024-01-01", "2024-12-31")
        .select("avg_rad")
        .median()
        .clip(BD_BOUNDS)
    )
    log_lights = viirs.unitScale(0, 60).pow(0.4)
    url = log_lights.getThumbURL(
        {
            "min": 0,
            "max": 1,
            "palette": ["000010", "0a1a3e", "1d3a8a", "f59e0b", "fef3c7", "ffffff"],
            "dimensions": DIM,
            "format": "jpg",
            "region": BD_BOUNDS,
        }
    )
    fetch(url, OUT / "glowing.jpg")


def greening() -> None:
    ndvi = (
        ee.ImageCollection("MODIS/061/MOD13Q1")
        .filterDate("2024-01-01", "2024-12-31")
        .select("NDVI")
        .median()
        .multiply(0.0001)
        .clip(BD_BOUNDS)
    )
    url = ndvi.getThumbURL(
        {
            "min": 0.0,
            "max": 0.85,
            "palette": [
                "8b4513",
                "d4a574",
                "f5deb3",
                "c5e1a5",
                "66bb6a",
                "2e7d32",
                "1b5e20",
            ],
            "dimensions": DIM,
            "format": "jpg",
            "region": BD_BOUNDS,
        }
    )
    fetch(url, OUT / "greening.jpg")


def eroding() -> None:
    jamuna = ee.Geometry.Rectangle([89.4, 23.3, 90.4, 25.3])
    l9 = (
        ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
        .filterBounds(jamuna)
        .filterDate("2024-01-01", "2024-04-30")
        .filter(ee.Filter.lt("CLOUD_COVER", 20))
        .median()
        .clip(jamuna)
    )
    rgb = l9.select(["SR_B4", "SR_B3", "SR_B2"]).multiply(0.0000275).add(-0.2)
    url = rgb.getThumbURL(
        {
            "bands": ["SR_B4", "SR_B3", "SR_B2"],
            "min": 0.02,
            "max": 0.3,
            "gamma": 1.2,
            "dimensions": DIM,
            "format": "jpg",
            "region": jamuna,
        }
    )
    fetch(url, OUT / "eroding.jpg")


def dividing() -> None:
    viirs = (
        ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG")
        .filterDate("2024-01-01", "2024-12-31")
        .select("avg_rad")
        .median()
        .clip(BD_BOUNDS)
    )
    built = (
        ee.ImageCollection("JRC/GHSL/P2023A/GHS_BUILT_S")
        .filter(ee.Filter.eq("system:index", "2020"))
        .first()
        .select("built_surface")
        .clip(BD_BOUNDS)
    )
    pop = (
        ee.ImageCollection("WorldPop/GP/100m/pop")
        .filter(ee.Filter.eq("year", 2020))
        .filter(ee.Filter.eq("country", "BGD"))
        .mosaic()
        .clip(BD_BOUNDS)
    )

    r = viirs.unitScale(0, 50).clamp(0, 1)
    g = built.unitScale(0, 8000).clamp(0, 1)
    b = pop.log().unitScale(0, 8).clamp(0, 1)
    rgb = ee.Image.cat([r, g, b]).rename(["R", "G", "B"])
    url = rgb.getThumbURL(
        {
            "bands": ["R", "G", "B"],
            "min": 0,
            "max": 1,
            "dimensions": DIM,
            "format": "jpg",
            "region": BD_BOUNDS,
        }
    )
    fetch(url, OUT / "dividing.jpg")


def main() -> None:
    print(f"Saving thumbnails to {OUT}")
    for fn in (drowning, glowing, greening, eroding, dividing):
        try:
            fn()
        except Exception as e:
            print(f"  ✗ {fn.__name__} failed: {e}")
    print("done.")


if __name__ == "__main__":
    main()
