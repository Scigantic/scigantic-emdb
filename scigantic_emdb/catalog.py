"""The searchable catalog over every released EMDB entry."""
from __future__ import annotations
import gzip

from ._coerce import _as_list, _nonempty, _num_ok, _truthy
from ._query import (FIELD_WEIGHT, LIGAND_ALIASES, SEARCH_FIELDS, adaptive_terms,
                     field_text, match_score)
from .accession import acc, image_url
from .config import CATALOG_URL, MOUNT, _session


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
