"""
Division-based tiling for national-scale GEE processing.
Splits heavy computations across Bangladesh's 8 administrative divisions
to avoid GEE timeouts and memory limits.
"""
import ee
import config as cfg
from data_acquisition import get_division_boundaries_all


def get_division_tiles():
    """
    Return list of {name, geometry} for each Bangladesh division.
    """
    fc = get_division_boundaries_all()
    names = fc.aggregate_array("ADM1_NAME").getInfo()
    tiles = []
    for name in names:
        geom = fc.filter(ee.Filter.eq("ADM1_NAME", name)).geometry()
        tiles.append({"name": name, "geometry": geom})
    return tiles


def run_tiled(func, region_arg_name="region", merge_func=None, **kwargs):
    """
    Run a GEE function tiled across divisions.

    func: callable that accepts a region keyword argument
    region_arg_name: name of the region parameter in func
    merge_func: callable to merge per-tile results (or None → return dict)
    """
    tiles = get_division_tiles()
    results = {}
    for tile in tiles:
        print(f"  Processing tile: {tile['name']}...")
        kwargs[region_arg_name] = tile["geometry"]
        try:
            results[tile["name"]] = func(**kwargs)
        except Exception as e:
            print(f"    Tile {tile['name']} failed: {e}")

    if merge_func:
        return merge_func(results)
    return results


def merge_image_tiles(tile_results):
    """Merge per-division ee.Image results into a national mosaic."""
    images = [v for v in tile_results.values() if v is not None]
    if not images:
        return None
    return ee.ImageCollection(images).mosaic()


def merge_area_tiles(tile_results):
    """Sum numeric area results across all tiles."""
    total = 0.0
    for name, area in tile_results.items():
        if area is not None:
            if isinstance(area, (ee.Number, ee.ComputedObject)):
                try:
                    area = area.getInfo()
                except Exception:
                    continue
            if area is not None:
                total += area
    return total


def merge_time_series_tiles(tile_results):
    """
    Merge per-division time series (list of dicts with 'year' key).
    Sums area columns across divisions for each year.
    """
    from collections import defaultdict
    year_totals = defaultdict(lambda: defaultdict(float))

    for div_name, series in tile_results.items():
        if series is None:
            continue
        for entry in series:
            year = entry["year"]
            for key, val in entry.items():
                if key == "year":
                    continue
                if val is not None:
                    if isinstance(val, (ee.Number, ee.ComputedObject)):
                        try:
                            val = val.getInfo()
                        except Exception:
                            val = 0.0
                    year_totals[year][key] += val

    result = []
    for year in sorted(year_totals.keys()):
        row = {"year": year}
        row.update(year_totals[year])
        result.append(row)
    return result
