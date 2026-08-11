# bd_gis Codebase Ledger

Standing map of architecture truths, conventions, intentional quirks, and open issues. Read this before any audit or "is this right?" investigation, and write findings back into it, dated. A fact rediscovered by a later audit means this ledger failed.

Created 2026-08-01 from a verified repository hygiene pass.

## Architecture truths

- **Flat layout is deliberate.** All analysis modules sit at the repository root and do `import config as cfg`. `CLAUDE.md` explicitly forbids restructuring into a package. Do not "fix" this.
- **Earth Engine is the compute layer.** Modules build lazy `ee.*` graphs; nothing evaluates until `.getInfo()` or an export. Errors therefore surface at evaluation time, not at call time.
- **`config.py` is the single source of dataset truth.** Every collection ID, boundary, threshold and reference coordinate lives there. Modules must not hardcode dataset IDs.
- **`run_pipeline.py` is the only orchestrator.** 2,563 lines: argparse surface, GEE init, output directory creation, `ee.Number` resolution, CSV export, and the `--full-extended` wave scheduler.
- **Two execution backends.** The Earth Engine path (28 modules) and an offline path (`local_compute.py`, `local_landcover.py`, fed by `download_local.py`) that reads downloaded GeoTIFFs and makes no network calls.
- **Timeout mechanism is not uniform.** `run_pipeline.py` uses `signal.SIGALRM`; `river_analysis.py` and `char_accretion.py` use a `ThreadPoolExecutor` with `future.result(timeout=)`. SIGALRM is Unix and macOS only.

## Data and unit conventions

- **DMSP-OLS and VIIRS are not comparable.** DMSP is digital number 0–63, VIIRS is radiance in nW/cm2/sr. `compute_light_change` raises `ValueError` on a cross-sensor comparison rather than returning a silently wrong number. The 2013/2014 boundary is hard.
- **GHSL epochs are 5-year.** Requesting 2017 snaps to 2015 or 2020. The snap is logged, and two years snapping to the same epoch triggers a warning.
- **MODIS LST requires QA masking** via `_mask_lst_quality`. Fill values corrupt every LST statistic if skipped.
- **All Sentinel-5P pollutants are QA-filtered**: NO2 at >= 0.75, other products at >= 0.5.
- **Water occurrence uses dry-season composites (Nov to Feb)**, not full-year.
- **SAR flood threshold is -17 dB VV**, deliberately conservative, so it biases toward under-detection rather than false positives.
- **National scope forces fixed water thresholds.** Otsu times out over ~148,000 km2.
- **Coverage end dates differ by product**: WorldPop ends 2020, GRACE mascon ends 2017, Sentinel-5P starts late 2018, Dynamic World starts 2015.
- **Administrative boundaries are FAO GAUL 2015**, which does not exactly match official Bangladesh boundaries.

## Naming that does not mean what it looks like

These were renamed precisely because the original names overclaimed. Do not rename them back.

| Name | What it actually is |
|------|--------------------|
| `estimate_buildup_density` (was `estimate_road_density`) | Built-up area, not road length |
| `compute_pollutant_stack` (was `compute_aqi_composite`) | Relative index over incomparable units, not an AQI |
| `erosion_susceptibility` | Relative index, not a quantitative RUSLE soil loss rate |
| `salinity_proxy` | Proxy, not an EC measurement |
| `channel_abandonment` / `bank_erosion` (were `eroded` / `accreted`) | River channel change classes |

## Intentional quirks

- **Blind `except Exception` is the pipeline contract.** A failing feature prints and the run continues, so a multi-hour national run is not lost to one bad module. Ruff's `BLE001` (273 sites) is suppressed in `ruff.toml` for this reason.
- **Imports below module top (`E402`)** are ordering-sensitive: scripts call `ee.Initialize()` and set up output paths before importing dependent modules. Suppressed with rationale.
- **Implicit string concatenation in list literals** across `generate_pdf_report.py` is wrapped report prose, not missing commas. Reviewed site by site on 2026-08-01, all 26 deliberate.
- **Composite index weights are heuristic** and labelled as such in source. Poverty, slum, health risk and energy indices are normalised weighted sums, valid for ranking, not for reporting levels.
- **Arsenic hotspots, cyclone landfall points and known slum areas are literature-based** hardcoded constants, not satellite-derived.

## Open issues

| # | Severity | Date | Issue |
|---|----------|------|-------|
| 0a | **High** | 2026-08-01 | **The poverty index measures nothing detectable, even after the normalization bug was fixed.** The degenerate-constant bug is resolved (see Resolved), and the index now has real spatial variance. But scored at district level against IPUMS district MPI, `n = 60`, Pearson r = **-0.038**, 95% CI [-0.289, +0.218]. That interval excludes any useful positive relationship, so the composite does not track independent poverty measures. Do not publish it as a poverty estimate, and do not read the division-level `r` as evidence either way: at `n = 7` the 95% CI spans roughly [-0.49, +0.89] and cannot support any tier. The four inputs (light deficit, built-up deficit, population-light gap, vegetation stress) plausibly capture *rurality*, which is correlated with poverty in some divisions and not others. Rebuilding this needs a supervised approach trained on district ground truth, not a hand-weighted composite. |
| 0a-i | Medium | 2026-08-01 | Validation of poverty indicators should move from division (`n = 7`) to district (`n = 60-64`) resolution. At `n = 7` the tier thresholds (A at r>=0.8, B at r>=0.5) are not distinguishable from noise, so a division-level card can report tier A or tier C on essentially the same underlying skill. `outputs/poverty/ipums_district_mpi.csv` and `poverty_district_ranking.csv` already provide the two sides of a district join. |
| 0c | Medium | 2026-08-01 | `outputs/report_maps/05_extreme_floods_1988_2004.png` headlines "1988 (6,823 km2) vs 2004 (4,531 km2)". The 2004 panel shows visible Landsat 7 SLC-off scan-line striping. `data_acquisition.py` mitigates this by merging L5 first so median compositing prefers complete swaths, and warns at runtime, but ~22% L7 data loss is only partially recovered. Unobserved gap pixels render in the same white as "not flooded", so the 2004 area is biased low and the two numbers are not strictly comparable. The PDF report notes the limitation; the figure does not. |
| 0d | Medium | 2026-08-01 | `outputs/` (229 files, 49 MB: 173 CSV, 29 PNG, 22 HTML, 3 validation JSON, 1 PDF) exists only in the working copy at `~/bdpolicylab/bd_gis`, where bd_gis is a git submodule. It is gitignored and there is no `backup.sh` / `restore.sh`, so a fresh `git clone` of the standalone repo produces no outputs and nothing restores them. Commit `cfc7cc3` moved these to an OneDrive-backed symlink, but OneDrive was retired as a backup target on 2026-06-08. |
| 1 | Medium | 2026-08-01 | `aquaculture.py::_compute_turbidity_proxy` computes `swir1` and both the docstring and inline comment state the proxy uses "low SWIR1", but the returned expression is green/NIR only and never references `swir1`. Either the documented method or the implementation is wrong. Not resolved here because picking a side changes outputs. |
| 2 | Low | 2026-08-01 | `crop_detection.py` computes `harvest_start` / `harvest_end` for all three rice seasons and never samples that window. Harvest phase appears planned but unimplemented. |
| 3 | Low | 2026-08-01 | 9 further unused locals (ruff `F841`), mostly retained matplotlib handles. `F841` is suppressed in `ruff.toml`; re-enable after clearing issues 1 and 2. |
| 4 | Low | 2026-08-01 | 15 `except: pass` sites (ruff `S110`) silently swallow errors, contradicting the documented "print the failure, then continue" convention. |
| 5 | Low | 2026-08-01 | `generate_chapter_thumbnails.py` writes to `../app/web/static/satellite`, a path outside this repository, and calls `mkdir(parents=True)` at import time. Cross-repo coupling with the Satellite Bangladesh series. |
| 6 | Low | 2026-08-01 | 13 `zip()` calls without `strict=` (ruff `B905`). Ragged inputs would truncate silently. Suppressed rather than changed, since adding `strict=True` alters runtime behaviour. |
| 7 | Informational | 2026-08-01 | `cfg.GEE_PROJECT` still defaults to the original author's Cloud project. Now overridable via the `GEE_PROJECT` env var, but a fresh clone with no env var fails at Earth Engine init rather than with a clear message. |

## Resolved

| Date | Item |
|------|------|
| 2026-08-01 | **The `gis_poverty_index` card claimed tier A, `pearson_r = 0.99957`, `n = 8`, `caveats: []`, and was not reproducible from any file in `outputs/`.** Regenerated from `outputs/poverty/poverty_by_division.csv`: now tier **C**, `n = 7`, `r = +0.197`, three caveats. Root causes fixed below. Note a stale `outputs/poverty/hies_division_hcr.csv` (different schema and values from the current `HIES_HCR_BY_DIVISION` dict) is NOT what validation reads and should be regenerated or deleted to avoid confusing future audits. |
| 2026-08-01 | **Poverty index normalization was saturating every component.** Each input was unit-scaled against a fixed physical range (VIIRS 0-200 nW/cm2/sr, WorldPop 0-25000 people per 100 m pixel, NDVI 0-0.9), which puts essentially all of Bangladesh in the bottom few percent. Measured nationally at 2 km: `light_dep` mean 0.9970 sd 0.0052, `built_dep` mean 0.9973 sd 0.0284, `pop_light_gap` mean 0.0004 sd 0.0009. Three of four components were constants, so the composite reduced to `0.5 + veg_stress/4`, i.e. inverted NDVI. Replaced with `robust_unit_scale`, a 2nd-98th percentile stretch against the observed distribution over the region, with a log transform for the log-normal quantities (radiance, built fraction, population). After: sd 0.1974 / 0.0971 / 0.1655 / 0.2067. Division spread went from 0.0101 to 0.0825. |
| 2026-08-01 | **Division and district aggregation is now population-weighted.** A plain `reduceRegion(mean)` weights Sundarbans mangrove and empty char land the same as Dhaka, while survey poverty rates are shares of people. Both the weighted and unweighted means are reported. Note the accompanying `population_weight_sum` is WorldPop sampled at `scale` and is NOT a population count (the factor cancels in the ratio); it is named accordingly so it is never quoted as one. |
| 2026-08-01 | **Root cause 1, silent partial join.** `validate_indicator` only flagged predicted units that failed to match the reference, never reference units with no prediction. With 7 GAUL divisions all matching, `matched == total` and no caveat fired, so Mymensingh vanished from the score with no trace. The check is now bidirectional, and the card carries an explicit `coverage` block (`n_predicted` / `n_reference` / `n_matched`). Regression test added. |
| 2026-08-01 | **Root cause 2, no join-key normalisation.** GAUL spells two divisions "Barisal" and "Chittagong" against BBS "Barishal" and "Chattogram", so a raw join would have dropped them too. Indicators now carry `key_aliases`, reusing the existing `GEE_TO_HIES` map from `calibrate_poverty.py` rather than a second copy. |
| 2026-08-01 | **Root cause 3, no provenance.** Cards recorded no input path, so a wrong `--predicted-csv` was undetectable after the fact. Cards now record `predicted_source`. |
| 2026-08-01 | The poverty indicator had no `static_caveats` despite two structural problems (GAUL/BBS geography mismatch, and a unitless 0-1 index compared against a percentage so only `pearson_r` is interpretable). Both are now attached to every card it generates. |
| 2026-08-01 | `requirements.txt` declared `geopandas`, `scipy` and `scikit-image`, none of which are imported anywhere (geopandas alone pulls GDAL). Removed. `Pillow` and `fpdf2` were imported but undeclared. Added. |
| 2026-08-01 | `pytest` and `ruff` were undeclared. Added `requirements-dev.txt`. |
| 2026-08-01 | `generate_chapter_thumbnails.py` hardcoded the GEE project ID inline, bypassing `config.py` and violating the repo's own convention. Now uses `cfg.GEE_PROJECT`. |
| 2026-08-01 | `GEE_PROJECT` was a hardcoded constant, making the repository unusable by anyone else. Now reads the `GEE_PROJECT` env var, matching the existing `BD_GIS_SCOPE` pattern. |
| 2026-08-01 | `--full-extended` help said "ALL modules" but the wave scheduler runs 23 of 28, excluding cyclones, aquaculture, chars, timelapse and alerts. Help text corrected. |
| 2026-08-01 | No LICENSE on a public repository. Added MIT. |
| 2026-08-01 | No CI. Added ruff, pytest on 3.11 and 3.12, and an install-and-import job that catches dependency drift on a clean environment. |
| 2026-08-01 | README documented 22 CLI flags against 34 real ones, omitted 12 modules entirely, never mentioned the `validation/` subsystem, and gave no Earth Engine setup instructions. Rewritten against the code. |
| 2026-08-01 | 101 mechanical lint defects (unsorted imports, 19 unused imports, empty f-strings) auto-fixed; 7 further sites fixed by hand. |
| 2026-08-01 | `.gitignore` listed `outputs/FINDINGS_REPORT.html` redundantly alongside `outputs/`. |

## Verified clean

| Date | Check | Method | Result |
|------|-------|--------|--------|
| 2026-08-01 | Test suite | `pytest -q` | 26 passed, no Earth Engine credentials needed |
| 2026-08-01 | Module importability | Imported all 46 root modules in a clean env built from `requirements.txt` | 46/46 clean. 3 excluded (`generate_report_maps`, `generate_publication_maps`, `generate_chapter_thumbnails`) call `ee.Initialize()` at import and need credentials |
| 2026-08-01 | Lint | `ruff check .` under the explicit `ruff.toml` rule set (E, F, I, W, UP, B, C4) | Clean |
| 2026-08-01 | Missing-comma audit | Reviewed all 26 `ISC004` sites | All deliberate prose wrapping, no data corruption |
| 2026-08-01 | Dependency reality | Cross-checked every third-party import against `requirements.txt` | Reconciled, see Resolved |
| 2026-08-01 | Secrets scan | Grepped for credentials, keys and `.env` | None committed. The GCP project ID is an identifier, not a secret |

## Branch cleanup

2026-08-10 branch cleanup (Claude): chore/repo-hygiene (tip 41c738a, 6 commits, PR #1 open) was genuinely unmerged, finished work: merged into main via --no-ff, gate `uvx ruff check .` passed, branch deleted local+remote. Worktree .claude/worktrees/repo-hygiene was clean: unlocked and removed. Untracked .claude/ in main checkout left untouched. Repo goal state reached: only main remains.
