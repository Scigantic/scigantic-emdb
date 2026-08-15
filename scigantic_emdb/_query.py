"""The query layer, imported from scigantic-empiar rather than copied.

This module exists to keep that import in one place. scigantic_emdb carries no
search implementation of its own: both archives share one, so the fixes it
holds cannot diverge between them. See SYNC.md.
"""
from __future__ import annotations
import os


# One search implementation, shared with scigantic_empiar rather than copied.
# expand_query/_pattern/match_score carry fixes for five defects found in
# production use (substring bleed, lost plurals, synonym expansion outranking
# the literal query, zero-recall on "GPCR", unconditional query rewriting). A
# second copy would silently diverge from those fixes the first time one is
# revised.
#
# Loaded from the file rather than as `from scigantic_empiar._search import ...`
# because that form imports scigantic_empiar's package __init__ first, which
# pulls numpy, requests and scigantic-headers. _search.py is deliberately free
# of all three so the query layer stays testable without the imaging stack, and
# routing through the parent package would throw that away — `import
# scigantic_emdb` would then need numpy just to run a text query.
def _load_search():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, os.pardir, "scigantic_empiar", "_search.py"),
                 "/opt/scigantic/pylib/scigantic_empiar/_search.py"):
        if os.path.exists(cand):
            spec = importlib.util.spec_from_file_location("_scigantic_search", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    from scigantic_empiar import _search as mod  # installed some other way
    return mod


_S = _load_search()
adaptive_terms, expand_query = _S.adaptive_terms, _S.expand_query
field_text, match_score = _S.field_text, _S.match_score

__all__ = [
    "EmdbCatalog", "load_map", "slices", "entry_files", "map_path",
    "image_url", "MOUNT", "CATALOG_URL",
]

MOUNT = os.environ.get("SCIGANTIC_MOUNT_PATH", "/mnt/http-archive/data")
CATALOG_URL = os.environ.get(
    "SCIGANTIC_EMDB_CATALOG",
    "https://scigantic-empiar-catalog.s3.amazonaws.com/emdb-catalog.json.gz",
)
FTP = "https://ftp.ebi.ac.uk/pub/databases/emdb/structures"

# Fields the free-text query runs over, with EMDB's names. `title` and
# `sample_name` carry the science; `organism` and the accession lists are worth
# matching but should not outrank a title hit.
SEARCH_FIELDS = ("title", "sample_name", "organism", "method",
                 "pdb_ids", "uniprot_ids", "id", "paper_title")
FIELD_WEIGHT = {"title": 3, "sample_name": 3, "paper_title": 2,
                "pdb_ids": 2, "uniprot_ids": 2, "id": 2,
                "organism": 1, "method": 1}


# Ligands are deposited under full chemical names, so the abbreviation a
# scientist actually types finds almost nothing: ligand="ATP" matched 4 entries
# against 965 deposited as "ADENOSINE-5'-TRIPHOSPHATE", and "GTP" matched 2
# against 434. That is the same failure as search("GPCR") returning zero across
# the archive: the deposited vocabulary and the spoken one differ.
#
# Every target below was read off the deposited names in the built catalog, not
# invented. Values are substrings, matched case-insensitively, so "ADENOSINE-5'"
# covers both the triphosphate and diphosphate spellings where that is intended.
LIGAND_ALIASES = {
    "atp": "adenosine-5'-triphosphate",
    "adp": "adenosine-5'-diphosphate",
    "gtp": "guanosine-5'-triphosphate",
    "gdp": "guanosine-5'-diphosphate",
    "amp-pnp": "phosphoaminophosphonic acid-adenylate ester",
    "amppnp": "phosphoaminophosphonic acid-adenylate ester",
    "atp-gamma-s": "phosphothiophosphoric acid-adenylate ester",
    "fmn": "flavin mononucleotide",
    "nadph": "nadph",
    "heme": "protoporphyrin ix containing fe",
    "haem": "protoporphyrin ix containing fe",
    "chs": "cholesterol hemisuccinate",
    "ddm": "dodecyl-beta-d-maltoside",
    "nag": "2-acetamido-2-deoxy-beta-d-glucopyranose",
    "glcnac": "2-acetamido-2-deoxy-beta-d-glucopyranose",
    "mg": "magnesium ion",
    "zn": "zinc ion",
    "ca": "calcium ion",
    "fe/s": "iron/sulfur cluster",
    "iron-sulfur": "iron/sulfur cluster",
    "pc": "1,2-diacyl-sn-glycero-3-phosphocholine",
}

_S = _load_search()
adaptive_terms, expand_query = _S.adaptive_terms, _S.expand_query
field_text, match_score = _S.field_text, _S.match_score

# Fields the free-text query runs over, with EMDB's names. `title` and
# `sample_name` carry the science; `organism` and the accession lists are worth
# matching but should not outrank a title hit.
SEARCH_FIELDS = ("title", "sample_name", "organism", "method",
                 "pdb_ids", "uniprot_ids", "id", "paper_title")
FIELD_WEIGHT = {"title": 3, "sample_name": 3, "paper_title": 2,
                "pdb_ids": 2, "uniprot_ids": 2, "id": 2,
                "organism": 1, "method": 1}

# Ligands are deposited under full chemical names, so the abbreviation a
# scientist actually types finds almost nothing: ligand="ATP" matched 4 entries
# against 965 deposited as "ADENOSINE-5'-TRIPHOSPHATE", and "GTP" matched 2
# against 434. That is the same failure as search("GPCR") returning zero across
# the archive: the deposited vocabulary and the spoken one differ.
#
# Every target below was read off the deposited names in the built catalog, not
# invented. Values are substrings, matched case-insensitively, so "ADENOSINE-5'"
# covers both the triphosphate and diphosphate spellings where that is intended.
LIGAND_ALIASES = {
    "atp": "adenosine-5'-triphosphate",
    "adp": "adenosine-5'-diphosphate",
    "gtp": "guanosine-5'-triphosphate",
    "gdp": "guanosine-5'-diphosphate",
    "amp-pnp": "phosphoaminophosphonic acid-adenylate ester",
    "amppnp": "phosphoaminophosphonic acid-adenylate ester",
    "atp-gamma-s": "phosphothiophosphoric acid-adenylate ester",
    "fmn": "flavin mononucleotide",
    "nadph": "nadph",
    "heme": "protoporphyrin ix containing fe",
    "haem": "protoporphyrin ix containing fe",
    "chs": "cholesterol hemisuccinate",
    "ddm": "dodecyl-beta-d-maltoside",
    "nag": "2-acetamido-2-deoxy-beta-d-glucopyranose",
    "glcnac": "2-acetamido-2-deoxy-beta-d-glucopyranose",
    "mg": "magnesium ion",
    "zn": "zinc ion",
    "ca": "calcium ion",
    "fe/s": "iron/sulfur cluster",
    "iron-sulfur": "iron/sulfur cluster",
    "pc": "1,2-diacyl-sn-glycero-3-phosphocholine",
}
