"""scigantic_emdb — search and read the Electron Microscopy Data Bank.

EMDB holds the 3D density maps produced by cryo-EM, cryo-ET and volume-EM: the
*reconstructions*, where EMPIAR holds the raw movies they were computed from.

What this library is for
------------------------
Finding entries. EMDB's I/O genuinely is easy — a map is 20-60 MB and
``mrcfile`` opens it. What EMDB lacks is any way to answer "which of these
~60,900 structures do I want", short of already knowing the accession.

    from scigantic_emdb import EmdbCatalog
    cat = EmdbCatalog()
    cat.search("GPCR", max_res=3.0, organism="Homo sapiens")
    cat.search("ribosome", max_chain_kda=100, has_half_maps=True)

Then read one, in two lines rather than the usual six:

    vol, meta = load_map("EMD-22962")
    slices(vol)

Coverage is stated, not assumed. ``cat.coverage()`` reports exactly how many of
EMDB's released entries are in the index, and the per-field fill rates, because
molecular fields are deposition-dependent. The EMPIAR catalog once advertised
"all ~3,000 entries" while holding 12, and the in-notebook AI repeated that
claim to a scientist; every count this library prints is measured at build time
and carried in the catalog itself.

Layout
------
``config``      locations + the shared HTTP session
``_query``      the query layer, imported from scigantic-empiar (see SYNC.md)
``accession``   accession normalisation and the URLs derived from it
``files``       what an entry actually deposited
``maps``        load_map / slices
``catalog``     EmdbCatalog
``_coerce``     NaN-safe coercions for DataFrame cells

This file re-exports the public API, so flat ``scigantic_emdb.<name>`` calls
keep working and are the supported surface.
"""
from __future__ import annotations

from ._query import expand_query, match_score
from .accession import acc, image_url, map_path
from .catalog import EmdbCatalog
from .config import CATALOG_URL, FTP, MOUNT, SUBDIRS
from .files import entry_files
from .maps import load_map, slices

__version__ = "0.2.0"

__all__ = [
    # catalog
    "EmdbCatalog",
    # reading a map
    "load_map", "slices",
    # entry contents + addressing
    "entry_files", "acc", "map_path", "image_url",
    # query layer (shared with scigantic-empiar)
    "expand_query", "match_score",
    # locations
    "MOUNT", "CATALOG_URL", "FTP", "SUBDIRS",
    "__version__",
]
