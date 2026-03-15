#!/usr/bin/env python3
"""Download satellite products for local computation (Bangladesh subset)."""
import argparse
import os
import sys
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

LOCAL_DATA = Path(__file__).parent / "local_data"

BD_BOUNDS = (88.0, 20.5, 92.7, 26.7)  # west, south, east, north

# ── Hansen Global Forest Change v1.11 ────────────────────────────────────────
HANSEN_BASE = (
    "https://storage.googleapis.com/earthenginepartners-hansen/"
    "GFC-2023-v1.11/Hansen_GFC-2023-v1.11_{layer}_{tile}.tif"
)
HANSEN_TILES = ["20N_090E", "30N_090E"]
HANSEN_LAYERS = ["treecover2000", "lossyear", "gain"]
HANSEN_FILES = []
for layer in HANSEN_LAYERS:
    for tile in HANSEN_TILES:
        fname = f"Hansen_GFC-2023-v1.11_{layer}_{tile}.tif"
        url = HANSEN_BASE.format(layer=layer, tile=tile)
        HANSEN_FILES.append((url, fname, f"Hansen {layer} {tile}"))

# ── JRC Global Surface Water v1.4 ────────────────────────────────────────────
JRC_BASE = (
    "https://storage.googleapis.com/global-surface-water/"
    "downloads2021/occurrence/occurrence_{tile}v1_4_2021.tif"
)
JRC_TILES = ["80E_30N", "90E_30N", "90E_20N"]
JRC_FILES = []
for tile in JRC_TILES:
    fname = f"occurrence_{tile}v1_4_2021.tif"
    url = JRC_BASE.format(tile=tile)
    JRC_FILES.append((url, fname, f"JRC Surface Water {tile}"))

# ── CHIRPS v2.0 monthly rainfall (2023, 12 files) ────────────────────────────
CHIRPS_BASE = (
    "https://data.chc.ucsb.edu/products/CHIRPS-2.0/"
    "global_monthly/tifs/chirps-v2.0.{year}.{month:02d}.tif.gz"
)
CHIRPS_FILES = []
for month in range(1, 13):
    fname = f"chirps-v2.0.2023.{month:02d}.tif.gz"
    url = CHIRPS_BASE.format(year=2023, month=month)
    CHIRPS_FILES.append((url, fname, f"CHIRPS 2023-{month:02d}"))

# ── WorldPop 2020 ────────────────────────────────────────────────────────────
WORLDPOP_FILES = [(
    "https://data.worldpop.org/GIS/Population/Global_2000_2020_1km/"
    "2020/BGD/bgd_ppp_2020_1km_Aggregated.tif",
    "bgd_ppp_2020_1km_Aggregated.tif",
    "WorldPop Bangladesh 2020 1km",
)]

# ── GHSL Built-up Surface 2020 (WGS84 3-arcsec tiles) ────────────────────────
GHSL_BASE = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
    "GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E2020_GLOBE_R2023A_4326_3ss/"
    "V1-0/tiles/GHS_BUILT_S_E2020_GLOBE_R2023A_4326_3ss_V1_0_{tile}.zip"
)
# BD at ~88-93E, 20.5-26.7N falls in row 4 (30N-10N), columns 27 (80-90E) and 28 (90-100E)
GHSL_TILES = ["R4_C27", "R4_C28"]
GHSL_FILES = []
for tile in GHSL_TILES:
    fname = f"GHS_BUILT_S_E2020_GLOBE_R2023A_4326_3ss_V1_0_{tile}.zip"
    url = GHSL_BASE.format(tile=tile)
    GHSL_FILES.append((url, fname, f"GHSL Built-up {tile}"))

# ── All downloads grouped by category ────────────────────────────────────────
CATEGORIES = {
    "hansen": ("Hansen Global Forest Change v1.11", HANSEN_FILES),
    "jrc": ("JRC Global Surface Water v1.4", JRC_FILES),
    "chirps": ("CHIRPS v2.0 Monthly Rainfall (2023)", CHIRPS_FILES),
    "worldpop": ("WorldPop 2020 Bangladesh", WORLDPOP_FILES),
    "ghsl": ("GHSL Built-up Surface 2020", GHSL_FILES),
}


def _progress_hook(block_num, block_size, total_size):
    """Print download progress."""
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100.0, downloaded * 100.0 / total_size)
        mb = downloaded / 1e6
        total_mb = total_size / 1e6
        sys.stdout.write(f"\r  {mb:.1f} / {total_mb:.1f} MB ({pct:.0f}%)")
    else:
        mb = downloaded / 1e6
        sys.stdout.write(f"\r  {mb:.1f} MB")
    sys.stdout.flush()


def _remote_size(url):
    """Get Content-Length from HEAD request, or -1 if unavailable."""
    from urllib.request import Request, urlopen
    try:
        req = Request(url, method="HEAD")
        with urlopen(req, timeout=15) as resp:
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else -1
    except Exception:
        return -1


def download_file(url, dest, description):
    """Download a single file with progress, skip if already complete."""
    if dest.exists():
        local_size = dest.stat().st_size
        remote_size = _remote_size(url)
        if remote_size > 0 and local_size == remote_size:
            print(f"  SKIP (exists, {local_size / 1e6:.1f} MB): {dest.name}")
            return True
        elif remote_size > 0 and local_size != remote_size:
            print(f"  Re-downloading (size mismatch: {local_size} vs {remote_size}): {dest.name}")
        else:
            print(f"  SKIP (exists, cannot verify size): {dest.name}")
            return True

    print(f"  Downloading: {description}")
    try:
        urlretrieve(url, str(dest), reporthook=_progress_hook)
        print()
        return True
    except Exception as e:
        print(f"\n  FAILED: {e}")
        if dest.exists():
            dest.unlink()
        return False


def unzip_ghsl(zip_path):
    """Extract GHSL zip, return path to the .tif inside."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        tifs = [n for n in zf.namelist() if n.endswith(".tif")]
        if not tifs:
            print(f"  WARNING: no .tif found in {zip_path.name}")
            return None
        for tif in tifs:
            out = zip_path.parent / tif
            if out.exists():
                continue
            zf.extract(tif, zip_path.parent)
        return zip_path.parent / tifs[0]


def decompress_gz(gz_path):
    """Decompress a .gz file, return path to decompressed file."""
    import gzip
    import shutil
    out_path = gz_path.with_suffix("")  # remove .gz
    if out_path.exists():
        return out_path
    print(f"  Decompressing: {gz_path.name}")
    with gzip.open(gz_path, "rb") as f_in, open(out_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    return out_path


def clip_to_bangladesh(src_path, dst_path):
    """Clip a raster to Bangladesh bounds using rasterio. Skip if already exists."""
    if dst_path.exists():
        print(f"  SKIP clip (exists): {dst_path.name}")
        return True

    try:
        import rasterio
        from rasterio.mask import mask as rio_mask
        from rasterio.transform import from_bounds
        from shapely.geometry import box
    except ImportError as e:
        print(f"  SKIP clip (missing dependency: {e})")
        return False

    west, south, east, north = BD_BOUNDS
    bd_box = box(west, south, east, north)

    try:
        with rasterio.open(src_path) as src:
            # Check if source CRS is WGS84; if not, skip clipping
            if src.crs and src.crs.to_epsg() != 4326:
                print(f"  SKIP clip (CRS is {src.crs}, not EPSG:4326): {src_path.name}")
                return False

            out_image, out_transform = rio_mask(
                src, [bd_box.__geo_interface__], crop=True, nodata=src.nodata
            )
            out_meta = src.meta.copy()
            out_meta.update({
                "driver": "GTiff",
                "height": out_image.shape[1],
                "width": out_image.shape[2],
                "transform": out_transform,
                "compress": "lzw",
            })
            with rasterio.open(dst_path, "w", **out_meta) as dst:
                dst.write(out_image)
        print(f"  Clipped: {dst_path.name} ({dst_path.stat().st_size / 1e6:.1f} MB)")
        return True
    except Exception as e:
        print(f"  CLIP FAILED ({src_path.name}): {e}")
        if dst_path.exists():
            dst_path.unlink()
        return False


def download_category(cat_key):
    """Download all files in a category and clip global files to BD bounds."""
    label, files = CATEGORIES[cat_key]
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")

    LOCAL_DATA.mkdir(parents=True, exist_ok=True)
    ok, fail = 0, 0

    for url, fname, desc in files:
        dest = LOCAL_DATA / fname
        if download_file(url, dest, desc):
            ok += 1
        else:
            fail += 1

    # Post-processing: decompress, unzip, clip
    if cat_key == "chirps":
        print("\n  Post-processing CHIRPS (decompress + clip)...")
        for _, fname, _ in files:
            gz_path = LOCAL_DATA / fname
            if not gz_path.exists():
                continue
            tif_path = decompress_gz(gz_path)
            bd_name = tif_path.stem + "_bd.tif"
            clip_to_bangladesh(tif_path, LOCAL_DATA / bd_name)

    elif cat_key == "ghsl":
        print("\n  Post-processing GHSL (unzip)...")
        for _, fname, _ in files:
            zip_path = LOCAL_DATA / fname
            if not zip_path.exists():
                continue
            unzip_ghsl(zip_path)

    elif cat_key == "hansen":
        # Hansen tiles already cover only ~10x10 deg, clip to exact BD bounds
        print("\n  Post-processing Hansen (clip to BD)...")
        for _, fname, _ in files:
            src = LOCAL_DATA / fname
            if not src.exists():
                continue
            bd_name = src.stem + "_bd.tif"
            clip_to_bangladesh(src, LOCAL_DATA / bd_name)

    elif cat_key == "jrc":
        print("\n  Post-processing JRC (clip to BD)...")
        for _, fname, _ in files:
            src = LOCAL_DATA / fname
            if not src.exists():
                continue
            bd_name = src.stem + "_bd.tif"
            clip_to_bangladesh(src, LOCAL_DATA / bd_name)

    # WorldPop is already Bangladesh-only, no clipping needed

    print(f"\n  Done: {ok} downloaded, {fail} failed")
    return fail == 0


def main():
    parser = argparse.ArgumentParser(
        description="Download satellite products for local computation (Bangladesh subset)."
    )
    parser.add_argument(
        "--all", action="store_true", help="Download all categories (default if none specified)"
    )
    for key, (label, _) in CATEGORIES.items():
        parser.add_argument(f"--{key}", action="store_true", help=label)

    args = parser.parse_args()

    selected = [k for k in CATEGORIES if getattr(args, k, False)]
    if not selected:
        if args.all or len(sys.argv) == 1:
            selected = list(CATEGORIES.keys())
        else:
            parser.print_help()
            return

    print(f"Download directory: {LOCAL_DATA}")
    total_cats = len(selected)
    all_ok = True
    for i, cat in enumerate(selected, 1):
        label, files = CATEGORIES[cat]
        print(f"\n[{i}/{total_cats}] {label} ({len(files)} files)")
        if not download_category(cat):
            all_ok = False

    print(f"\n{'=' * 60}")
    if all_ok:
        print("  All downloads complete.")
    else:
        print("  Some downloads failed. Re-run to retry.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
