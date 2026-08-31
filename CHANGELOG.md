# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.4.3] - 2026-08-31

### Fixed
- `files._entry_files_http()` no longer swallows request failures into `{}`.
  A connection error or non-2xx HTTP status now propagates, instead of
  reading indistinguishably from "this entry deposited nothing" — the exact
  ambiguity `entry_files()`'s own docstring says the HTTPS fallback exists to
  avoid.

### Added
- Regression tests for the `files.py` fix (`tests/test_files.py`).
- Basic no-network tests for accession normalization/zero-padding
  (`tests/test_accession.py`) and a smoke test for `maps.slices()`
  (`tests/test_maps.py`).

### Changed
- Added PyPI classifiers (license, supported Python versions, development
  status, audience, topic).
- Added `Repository` and `Issues` links to `[project.urls]`.
- Added upper bounds to `requests`, `pandas`, and `scigantic-empiar`
  dependencies so a future breaking major release doesn't silently break
  installs.
- Added CI/PyPI/license/Python-version badges and a scigantic.com link to
  the README.
- Widened the CI matrix from Python 3.9/3.12 to the full 3.9-3.13 range,
  matching scigantic-empiar's matrix.

## [0.4.2] - 2026-08-29
### Fixed
- Reused one shared HTTP session across `catalog.load()`, `files.entry_files()`
  and `maps.load_map()` instead of building a fresh session (and connection
  pool) on every call.
- Deduplicated `_query.py`.

## [0.4.1] - 2026-08-16
### Changed
- README brought up to date with 0.4.0 and simplified.

## [0.4.0] - 2026-08-16
### Added
- Filter by complex size (`complex_kda_max`/`complex_kda_min`) and by
  ligands that actually mean something (`has_ligand`, `ligand`), excluding
  ions, water and sample-prep additives from the "ligand-bound" count.

## [0.3.0] - 2026-08-16
### Added
- Filter by whether an entry's raw data is public (`has_raw_data`,
  `max_raw_gb`/`min_raw_gb`), cross-referenced from EMPIAR.

## [0.2.0] - 2026-08-15
### Changed
- Split the package into modules (`catalog.py`, `files.py`, `maps.py`,
  `accession.py`, `config.py`, `_query.py`, `_coerce.py`).

## [0.1.0] - 2026-08-15
### Added
- First public release: search every structure in EMDB by protein, organism,
  resolution, molecular weight and PDB cross-reference; read a map in two
  calls.
