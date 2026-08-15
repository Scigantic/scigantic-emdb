"""scigantic_emdb — search and read the Electron Microscopy Data Bank.

EMDB holds the 3D density maps produced by cryo-EM, cryo-ET and volume-EM: the
*reconstructions*, where EMPIAR holds the raw movies they were computed from.
The whole archive is FUSE-mounted read-only at ``$SCIGANTIC_MOUNT_PATH``.

What this library is for
------------------------
Finding entries. EMDB's I/O genuinely is easy — a map is 20-60 MB and
``mrcfile`` opens it — so this deliberately does NOT reimplement the parallel
range-reading machinery ``scigantic_empiar`` needs. What EMDB lacks is any way
to answer "which of these ~60,900 structures do I want", short of listing a
mount root that takes ~23 s and returns opaque directory names.

    from scigantic_emdb import EmdbCatalog
    cat = EmdbCatalog()
    cat.search("GPCR", max_res=3.0, organism="Homo sapiens")
    cat.search("ribosome", has_pdb=True, sort="resolution")

Then read one, in two lines rather than the usual six:

    vol, meta = load_map("EMD-22962")
    slices(vol)

Coverage is stated, not assumed. ``cat.coverage()`` reports exactly how many of
EMDB's released entries are in the index and where each record came from. The
EMPIAR catalog once advertised "all ~3,000 entries" while holding 12, and the
in-notebook AI repeated that claim to a user; every count this library prints
is measured at build time and carried in the catalog itself.
"""
from __future__ import annotations

import gzip
import os
import shutil
import sys

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


def _session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s = requests.Session()
    # EBI stalls ~3% of requests regardless of concurrency; retry beats waiting.
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504))))
    return s


def acc(entry_id):
    """Normalize 339 / '339' / 'EMD-339' / 'emd_0339' → 'EMD-0339'.

    Zero-padding is not cosmetic. EMDB accessions are always at least four
    digits: EMD-0339 exists and EMD-339 does not, and across the whole archive
    there is no case where a padded and an unpadded form are different entries
    (961 padded accessions, 0 collisions). Without the pad, load_map(339) builds
    a URL that 404s, which is exactly the sort of thing a user or the assistant
    would write and then have to debug.
    """
    s = str(entry_id).strip().upper().replace("EMD_", "EMD-")
    if s.startswith("EMD-"):
        s = s[4:]
    elif s.startswith("EMD"):
        s = s[3:].lstrip("-")
    s = s.strip()
    return f"EMD-{s.zfill(4)}" if s.isdigit() else f"EMD-{s}"


def map_path(entry_id, local=False):
    """Path to an entry's primary map, on the mount or at EBI."""
    a = acc(entry_id)
    n = a.split("-")[1]
    return (f"{MOUNT}/{a}/map/emd_{n}.map.gz" if not local
            else f"{FTP}/{a}/map/emd_{n}.map.gz")


SUBDIRS = ("map", "header", "images", "masks", "other", "fsc", "metadata")


def image_url(entry):
    """Public URL of an entry's published rendering, or "" if it has none.

    Takes a catalog row (dict or Series) rather than an accession, because the
    filename is NOT derivable: 93% are emd_<n>.png but the rest are things like
    1409.gif, wtVAT_ADP2.png and emd_5107_1.png. Constructing the canonical name
    and hoping would leave broken images on ~7% of gallery cards, so the catalog
    records the real filename and this just assembles the URL.
    """
    try:
        name = entry.get("image")
    except AttributeError:
        return ""
    if not name or name != name:
        return ""
    acc_id = entry.get("id")
    if not acc_id or acc_id != acc_id:
        return ""
    return f"{FTP}/{acc_id}/images/{name}"


def entry_files(entry_id):
    """What this entry actually deposited, per subdirectory.

    Half-maps, masks and FSC curves are per-deposition, not universal. Returns
    only the subdirectories that exist, so callers can check instead of
    assuming — nothing should tell a user a half-map is there without looking.

    Falls back to listing over HTTPS when the archive is not mounted, matching
    load_map. Without that the two disagreed: load_map worked off-mount and
    entry_files silently returned {}, which reads as "this entry deposited
    nothing" rather than "I could not look".
    """
    a = acc(entry_id)
    root = f"{MOUNT}/{a}"
    if os.path.isdir(root):
        out = {}
        for sub in SUBDIRS:
            p = os.path.join(root, sub)
            if os.path.isdir(p):
                try:
                    out[sub] = sorted(os.listdir(p))
                except OSError:
                    pass
        return out
    return _entry_files_http(a)


def _entry_files_http(a):
    """List an entry's subdirectories from EBI's autoindex over HTTPS."""
    import re
    s = _session()
    try:
        top = s.get(f"{FTP}/{a}/", timeout=30)
        top.raise_for_status()
    except Exception:
        return {}
    present = set(re.findall(r'href="([a-z_]+)/"', top.text)) & set(SUBDIRS)
    out = {}
    for sub in SUBDIRS:
        if sub not in present:
            continue
        try:
            r = s.get(f"{FTP}/{a}/{sub}/", timeout=30)
            r.raise_for_status()
            names = re.findall(r'href="([^"/?][^"/]*)"', r.text)
            out[sub] = sorted(n for n in names if "." in n)
        except Exception:
            continue
    return out


def load_map(entry_id, cache_dir="/tmp/emdb", permissive=True):
    """Decompress and open an EMDB map. Returns (numpy array, metadata dict).

    Maps ship gzipped, and ``mrcfile`` needs random access, so streaming a gzip
    straight off the FUSE mount is slow. This decompresses to local disk once
    and reuses it — the six lines everyone writes, written once.
    """
    import mrcfile
    import numpy as np
    a = acc(entry_id)
    os.makedirs(cache_dir, exist_ok=True)
    local = os.path.join(cache_dir, f"{a}.map")
    if not os.path.exists(local) or os.path.getsize(local) == 0:
        src = map_path(a)
        if os.path.exists(src):
            with gzip.open(src, "rb") as fh, open(local, "wb") as out:
                shutil.copyfileobj(fh, out, length=8 << 20)
        else:  # not mounted (e.g. running outside a notebook) — fetch from EBI
            import io
            r = _session().get(map_path(a, local=True), timeout=120)
            r.raise_for_status()
            with gzip.open(io.BytesIO(r.content), "rb") as fh, open(local, "wb") as out:
                shutil.copyfileobj(fh, out, length=8 << 20)
    with mrcfile.open(local, permissive=permissive) as m:
        vol = np.array(m.data)
        vs = m.voxel_size
        meta = {
            "shape": tuple(int(s) for s in vol.shape),
            "dtype": str(vol.dtype),
            "voxel_size_a": tuple(round(float(v), 3) for v in (vs.x, vs.y, vs.z)),
            "path": local,
            "size_mb": round(os.path.getsize(local) / 1e6, 1),
        }
    return vol, meta


def slices(vol, cmap="gray", figsize=(12, 4), percentile=(1, 99)):
    """Central sections through all three axes — the fastest look at a map.

    Contrast is stretched per-panel on a percentile range. Cryo-EM maps carry
    outliers that flatten a naive min/max scale to featureless grey; that was a
    real defect in the EMPIAR thumbnails, so it is handled here from the start.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    z, y, x = [s // 2 for s in vol.shape]
    panels = [(vol[z], "XY"), (vol[:, y], "XZ"), (vol[:, :, x], "YZ")]
    fig, ax = plt.subplots(1, 3, figsize=figsize)
    for a_, (img, t) in zip(ax, panels):
        lo, hi = np.percentile(img, percentile)
        a_.imshow(img, cmap=cmap, vmin=lo, vmax=hi if hi > lo else None)
        # Equal aspect: anisotropic voxels otherwise render a squashed map, the
        # distortion that made the first EMPIAR thumbnail set unusable.
        a_.set_aspect("equal")
        a_.set_title(t, fontsize=9)
        a_.axis("off")
    fig.tight_layout()
    return fig


class EmdbCatalog:
    """Searchable index over EMDB, built from EBI Search + the EMDB REST API.

    Loads a prebuilt catalog (one row per released entry: title, sample name,
    resolution, method, organism, PDB/UniProt cross-references, dates) so search
    and filtering are instant and involve no live reads.

    Unlike the EMPIAR catalog this has no thumbnail column, deliberately. 71% of
    EMPIAR is raw movie frames where a single frame is noise by physics, and
    shipping that as a preview was a mistake. An EMDB map renders meaningfully,
    but rendering is a per-entry read — so it is offered on demand via
    ``slices()``, not baked into 60,900 rows.
    """

    def __init__(self, url=CATALOG_URL):
        self.url = url
        self._df = None
        self._meta = {}
        # True when the last search fell back to synonym expansion because the
        # literal query was too thin. Exposed so the caller (or the in-notebook
        # AI) can say so instead of presenting a widened result set as if it
        # were what the user asked for.
        self.last_query_expanded = False

    def load(self):
        """Fetch and cache the catalog. Raises loudly if it cannot be read.

        No silent fallback to an empty or mount-derived catalog: a catalog that
        quietly degrades to 12 rows while still answering queries is exactly how
        the EMPIAR index came to advertise coverage it did not have.
        """
        import pandas as pd
        if self._df is not None:
            return self._df
        import io
        import json
        r = _session().get(self.url, timeout=60)
        r.raise_for_status()
        raw = r.content
        # Sniff the magic bytes rather than trusting the URL suffix: if S3 ever
        # serves the object with Content-Encoding: gzip, requests decompresses
        # it transparently and a suffix check would gunzip plain JSON and throw.
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        payload = json.loads(raw)
        if isinstance(payload, dict):
            self._meta = payload.get("meta", {}) or {}
            rows = payload.get("entries", [])
        else:
            rows = payload
        self._df = pd.DataFrame(rows)
        return self._df

    def coverage(self):
        """What this catalog actually contains, as measured when it was built."""
        self.load()
        m = dict(self._meta)
        m["loaded_rows"] = 0 if self._df is None else len(self._df)
        return m

    def entry(self, entry_id):
        """One row, as a dict. Returns {} if the accession is not in the index."""
        df = self.load()
        a = acc(entry_id)
        hit = df[df["id"] == a]
        return {} if hit.empty else {k: v for k, v in hit.iloc[0].to_dict().items()
                                     if v is not None and v == v}

    def search(self, query=None, *, organism=None, method=None, limit=50,
               max_res=None, min_res=None, has_pdb=None, has_uniprot=None,
               year=None, min_year=None, max_year=None, sort="relevance",
               max_chain_kda=None, min_chain_kda=None, complex_kda_max=None,
               complex_kda_min=None, has_half_maps=None, has_mask=None,
               has_model=None, microscope=None, ligand=None):
        """Find structures by scientific content.

        query       free text over title, sample name, organism, method and
                    accessions, with cryo-EM synonym expansion (so "GPCR" and
                    "cryoET" work). What you literally typed always outranks
                    anything expansion pulled in.
        organism    source organism substring, e.g. "Homo sapiens".
        method      one of: single-particle reconstruction, subtomogram
                    averaging, tomography, helical reconstruction,
                    2D crystallography.
        max_res     resolution bound in Å, lower being better. 96% of entries
                    report one; those that do not are excluded by this filter
                    rather than silently kept.
        has_pdb     require (or exclude) a fitted PDB model. ~58% have one.
        year        release year; or min_year/max_year for a range.
        sort        "relevance" (default), "resolution", "year", or "id".

        max_chain_kda   largest single protein chain, in kDa. This is the filter
                        for "a receptor under 100 kDa" — the assembled complex is
                        almost always heavier than the molecule of interest, so
                        filtering on complex weight finds the wrong things. Same
                        field name and meaning as EmpiarCatalog.
        complex_kda_max total assembly weight bound, when you do mean the complex.
        has_half_maps   require deposited half-maps (needed to recompute an FSC).
        has_mask        require a deposited mask.
        has_model       require a fitted atomic model.
        microscope      substring, e.g. "KRIOS", "JEOL".
        ligand          substring matched against deposited ligand names.

        A record missing the field being filtered on is EXCLUDED, never silently
        kept. Molecular fields come from depositions and are not universal, so
        check cat.coverage()["enrichment"]["field_fill_pct"] before reading a
        result count as "this is all there is".

        Returns a DataFrame.
        """
        df = self.load()
        if df.empty:
            return df
        records = df.to_dict("records")
        primary = str(query or "").strip().lower() or None
        # Widen the query only if the literal one is thin. At 60,900 entries an
        # unconditional synonym rewrite turns search("rhodopsin") into 1,189
        # hits, 1,149 of them some other GPCR.
        terms, widened = adaptive_terms(
            query,
            lambda t: sum(1 for r in records
                          if match_score(r, t, primary, SEARCH_FIELDS, FIELD_WEIGHT) > 0))
        self.last_query_expanded = widened
        # "ATP" is what a scientist types; "ADENOSINE-5'-TRIPHOSPHATE" is what
        # was deposited. Resolve the abbreviation before matching, or the filter
        # quietly returns almost nothing.
        ligand_q = str(ligand or "").strip().lower() or None
        if ligand_q:
            ligand_q = LIGAND_ALIASES.get(ligand_q, ligand_q)

        def keep(r):
            if terms and match_score(r, terms, primary, SEARCH_FIELDS, FIELD_WEIGHT) <= 0:
                return False
            if organism and organism.lower() not in field_text(r.get("organism")).lower():
                return False
            if method and method.lower() not in field_text(r.get("method")).lower():
                return False
            res = r.get("resolution_a")
            if max_res is not None and (res is None or res != res or res > max_res):
                return False
            if min_res is not None and (res is None or res != res or res < min_res):
                return False
            if has_pdb is not None and bool(_nonempty(r.get("pdb_ids"))) != bool(has_pdb):
                return False
            if has_uniprot is not None and bool(_nonempty(r.get("uniprot_ids"))) != bool(has_uniprot):
                return False
            y = r.get("year")
            y = None if y is None or y != y else int(y)
            if year is not None and y != year:
                return False
            if min_year is not None and (y is None or y < min_year):
                return False
            if max_year is not None and (y is None or y > max_year):
                return False
            if not _num_ok(r.get("max_chain_kda"), min_chain_kda, max_chain_kda):
                return False
            if not _num_ok(r.get("complex_kda"), complex_kda_min, complex_kda_max):
                return False
            for flag, want in (("has_half_maps", has_half_maps),
                               ("has_mask", has_mask),
                               ("has_model", has_model)):
                if want is not None and bool(_truthy(r.get(flag))) != bool(want):
                    return False
            if microscope and microscope.lower() not in field_text(r.get("microscope")).lower():
                return False
            if ligand_q and ligand_q not in field_text(r.get("ligands")).lower():
                return False
            return True

        hits = [r for r in records if keep(r)]
        if sort == "relevance" and terms:
            hits.sort(key=lambda r: -match_score(r, terms, primary,
                                                 SEARCH_FIELDS, FIELD_WEIGHT))
        elif sort == "resolution":
            hits.sort(key=lambda r: (r.get("resolution_a") is None
                                     or r.get("resolution_a") != r.get("resolution_a"),
                                     r.get("resolution_a") or 0))
        elif sort == "year":
            hits.sort(key=lambda r: -(r.get("year") or 0
                                      if r.get("year") == r.get("year") else 0))
        elif sort == "id":
            hits.sort(key=lambda r: int(r.get("n", 0) or 0))

        import pandas as pd
        out = pd.DataFrame(hits[:limit] if limit else hits)
        if out.empty:
            return out
        preferred = ["id", "title", "sample_name", "resolution_a", "method",
                     "organism", "max_chain_kda", "complex_kda", "has_half_maps",
                     "has_mask", "pdb_ids", "year"]
        cols = [c for c in preferred if c in out.columns]
        return out[cols + [c for c in out.columns if c not in cols]]

    def gallery(self, df=None, cols=4):
        """Render a gallery (HTML) of EMDB's own published renderings.

        These are EBI's isosurface renderings of the finished map, present for
        ~97% of entries. That is the opposite of the EMPIAR situation, where 71%
        of the archive is raw movies and a single frame is noise by physics, so
        previews had to be generated and turned out unusable. Here the picture
        already exists and is authored, so nothing is generated and nothing is
        copied: the card points at the public URL.

        A card without an image still has to be worth reading, so it leads with
        the sample name and carries resolution, weight and map availability.
        """
        from IPython.display import HTML
        import html as _html
        df = self.load() if df is None else df
        cells = []
        for _, r in df.iterrows():
            def g(key, default=""):
                v = r.get(key, default)
                return default if v is None or v != v else v

            eid = str(g("id"))
            img = image_url(r)
            if img:
                art = (f'<img src="{_html.escape(img)}" title="EMDB rendering" '
                       'style="width:100%;border-radius:6px;background:#fff" '
                       'loading="lazy">'
                       '<div style="font:9px sans-serif;color:#aaa;margin-top:2px">'
                       'EMDB rendering</div>')
            else:
                art = ('<div style="height:120px;border-radius:6px;background:#f2f2f2;'
                       'display:flex;align-items:center;justify-content:center;'
                       f'color:#aaa;font:10px sans-serif">no rendering ({_html.escape(eid)})</div>')

            label = str(g("sample_name") or g("title"))
            bits = []
            res = g("resolution_a", None)
            if res:
                bits.append(f"{float(res):.2f} &Aring;")
            mx = g("max_chain_kda", None)
            if mx:
                bits.append(f"{float(mx):.0f} kDa chain")
            if _truthy(g("has_half_maps")):
                bits.append("half-maps")
            if _truthy(g("has_mask")):
                bits.append("mask")

            cells.append(
                '<div style="width:calc(100%/' + str(cols) + ' - 10px);'
                'font:11px sans-serif;color:#333">' + art +
                f'<div style="margin-top:3px"><b>{_html.escape(eid)}</b></div>'
                f'<div style="color:#666;line-height:1.25">{_html.escape(label[:76])}</div>'
                f'<div style="color:#999">{" &middot; ".join(bits)}</div></div>')
        return HTML('<div style="display:flex;flex-wrap:wrap;gap:10px">'
                    + "".join(cells) + "</div>")

    def with_empiar(self, df=None, limit=None):
        """Join EMDB hits to the raw EMPIAR datasets behind them.

        This is the query neither archive answers alone: "structures better than
        3 Å where the raw movies are also public". EMDB says what was solved,
        EMPIAR says whether you can reprocess it. The EMPIAR catalog carries
        emdb_ids per entry, so the join runs locally over both indexes.
        """
        import pandas as pd
        try:
            from scigantic_empiar import EmpiarCatalog
        except Exception as e:
            raise RuntimeError(f"scigantic_empiar unavailable: {e}")
        rows = self.search(limit=None) if df is None else df
        if rows is None or len(rows) == 0:
            return pd.DataFrame()
        if limit:
            rows = rows.head(limit)
        emp = EmpiarCatalog().load()
        if emp.empty or "emdb_ids" not in emp.columns:
            return pd.DataFrame()
        back = {}
        for r in emp.to_dict("records"):
            # NOT `r.get("emdb_ids") or []`. A missing cell in a DataFrame reads
            # back as NaN, and NaN is truthy, so `or []` returns the NaN and the
            # loop raises "'float' object is not iterable". Same trap as
            # `if row.get("has_mask")` passing every row.
            for e in _as_list(r.get("emdb_ids")):
                back.setdefault(acc(e), []).append(r)
        out = []
        for r in rows.to_dict("records"):
            for src in back.get(r["id"], []):
                out.append({
                    "emdb_id": r["id"],
                    "title": r.get("title"),
                    "resolution_a": r.get("resolution_a"),
                    "empiar_id": src.get("id"),
                    "raw_size_gb": src.get("size_gb"),
                    "raw_method": src.get("method"),
                })
        return pd.DataFrame(out)


def _nonempty(v):
    if v is None or v != v:
        return False
    if isinstance(v, (list, tuple, set)):
        return len(v) > 0
    return bool(str(v).strip())


def _as_list(v):
    """NaN-safe list coercion for a DataFrame cell that should hold a list.

    `v or []` is wrong here: a missing cell reads back as NaN, NaN is truthy, and
    the caller then iterates a float. Returns [] for missing, wraps a bare
    scalar, and passes a real list through.
    """
    if v is None or (isinstance(v, float) and v != v):
        return []
    if isinstance(v, (list, tuple, set)):
        return [x for x in v if x is not None and x == x]
    return [v]


def _truthy(v):
    """NaN-safe truth. A missing column in a DataFrame reads back as NaN, which
    is truthy in Python, so `if r.get("has_mask")` would pass every row."""
    if v is None or (isinstance(v, float) and v != v):
        return False
    return bool(v)


def _num_ok(v, lo, hi):
    """Range check that EXCLUDES a record with no value for the field.

    Keeping such records would silently pad every molecular-weight filter with
    entries that never deposited a weight, which reads as a bigger result set
    than the data supports.
    """
    if lo is None and hi is None:
        return True
    if v is None or (isinstance(v, float) and v != v):
        return False
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    if lo is not None and x < lo:
        return False
    if hi is not None and x > hi:
        return False
    return True
