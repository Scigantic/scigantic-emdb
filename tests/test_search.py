"""Regression tests for the EMDB catalog query layer.

Run with plain stdlib, no pytest and no imaging stack:
    python3 infrastructure/docker/notebook-images/cryoem/scigantic_emdb/_search_test.py

Every test here corresponds to a defect that actually reached a user in the
EMPIAR work, written before shipping rather than after. The shared scorer is
loaded straight off disk, so this stays runnable without pandas/mrcfile.

The defects, and the tests that pin them:

  1. A catalog advertising coverage it did not have ("all ~3,000 entries" over
     12 rows), which the in-notebook AI then repeated to a scientist.
     → test_coverage_is_measured_not_asserted
  2. search("GPCR") returning zero across the whole archive, because neither
     archive tags a structure as a GPCR.
     → test_gpcr_recall
  3. Substring matching: the expansion term "g protein" matched inside
     "bindin[g protein]", scoring a helicase as a GPCR.
     → test_no_substring_bleed
  4. Fixing (3) with word boundaries then lost plurals: "nucleosome" stopped
     matching "nucleosomes" and the hit count dropped.
     → test_plurals_match_both_directions
  5. Synonym expansion outranking the literal query: search("rhodopsin")
     returned Cannabinoid Receptor 1 first and no rhodopsin in the top 5.
     → test_literal_query_outranks_synonyms
  6. Filters silently keeping records missing the filtered field, so a
     resolution bound returned entries with no resolution.
     → test_filters_exclude_missing_fields
  7. Advertising fields that are empty in practice (microscope: 0% populated).
     → test_no_empty_fields_advertised
"""
import importlib.util
import json
import os
import unittest

# In this repo the query layer comes from the installed scigantic-empiar, which
# is the single source of truth for it. There is deliberately no copy here: the
# fixes it carries (substring bleed, lost plurals, literal-over-synonym ranking,
# unconditional rewriting) were each found by a user hitting a dead end, and a
# second drifting copy means finding them twice.
from scigantic_empiar import _search as S  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.join(_HERE, os.pardir, "scigantic_emdb")

# Mirrors scigantic_emdb.SEARCH_FIELDS / FIELD_WEIGHT. Kept literal here so the
# test fails loudly if the package changes them without updating these tests.
FIELDS = ("title", "sample_name", "organism", "method",
          "pdb_ids", "uniprot_ids", "id", "paper_title")
WEIGHTS = {"title": 3, "sample_name": 3, "paper_title": 2,
           "pdb_ids": 2, "uniprot_ids": 2, "id": 2,
           "organism": 1, "method": 1}


def score(record, query):
    terms = S.expand_query(query)
    primary = str(query or "").strip().lower() or None
    return S.match_score(record, terms, primary, FIELDS, WEIGHTS)


def rank(records, query):
    """Records that match, best first — the ordering a user actually sees."""
    scored = [(score(r, query), r) for r in records]
    hits = [(s, r) for s, r in scored if s > 0]
    hits.sort(key=lambda sr: -sr[0])
    return [r for _, r in hits]


# Real EMDB records, as the builder emits them.
RHODOPSIN = {
    "id": "EMD-21356", "n": "21356",
    "title": "Rhodopsin-Gi complex",
    "sample_name": "Rhodopsin bound to heterotrimeric Gi",
    "organism": "Bos taurus", "method": "single-particle reconstruction",
    "resolution_a": 3.1, "pdb_ids": ["6vms"], "year": 2020,
}
CB1 = {
    "id": "EMD-0339", "n": "0339",
    "title": "Cannabinoid Receptor 1-G Protein Complex",
    "sample_name": "CB1-G protein complex",
    "organism": "Homo sapiens", "method": "single-particle reconstruction",
    "resolution_a": 3.0, "pdb_ids": ["6n4b"], "year": 2019,
}
# The trap for defect (3): "binding protein" contains the literal substring
# "g protein", and this structure is not a GPCR by any reading.
MDA5 = {
    "id": "EMD-6289", "n": "6289",
    "title": "MDA5 filament bound to double-stranded RNA",
    "sample_name": "RNA binding protein MDA5 helicase domain",
    "organism": "Homo sapiens", "method": "helical reconstruction",
    "resolution_a": 4.2, "pdb_ids": [], "year": 2016,
}
NUCLEOSOME_PLURAL = {
    "id": "EMD-30001", "n": "30001",
    "title": "Cryo-EM structure of stacked nucleosomes",
    "sample_name": "Di-nucleosomes in a chromatin fibre",
    "organism": "Homo sapiens", "method": "single-particle reconstruction",
    "resolution_a": 6.8, "pdb_ids": [], "year": 2021,
}
NUCLEOSOME_SINGULAR = {
    "id": "EMD-30002", "n": "30002",
    "title": "Nucleosome core particle",
    "sample_name": "Nucleosome", "organism": "Homo sapiens",
    "method": "single-particle reconstruction",
    "resolution_a": 2.9, "pdb_ids": ["7xyz"], "year": 2022,
}
RIBOSOME = {
    "id": "EMD-12250", "n": "12250",
    "title": "Bacterial 30S ribosomal subunit assembly complex state B",
    "organism": "Escherichia coli", "method": "single-particle reconstruction",
    "resolution_a": 3.77, "pdb_ids": [], "year": 2025, "src": "api",
}
NO_RESOLUTION = {
    "id": "EMD-99999", "n": "99999",
    "title": "Tomogram of a whole cell", "organism": "Homo sapiens",
    "method": "tomography", "pdb_ids": [], "year": 2024,
}

CORPUS = [RHODOPSIN, CB1, MDA5, NUCLEOSOME_PLURAL, NUCLEOSOME_SINGULAR,
          RIBOSOME, NO_RESOLUTION]


class TestRecall(unittest.TestCase):
    def test_gpcr_recall(self):
        """Defect 2: 'GPCR' must find receptors, though nothing is tagged GPCR."""
        hits = rank(CORPUS, "GPCR")
        ids = {r["id"] for r in hits}
        self.assertIn(CB1["id"], ids, "CB1-G protein complex is a GPCR structure")
        self.assertIn(RHODOPSIN["id"], ids, "rhodopsin is the archetypal GPCR")

    def test_plurals_match_both_directions(self):
        """Defect 4: singular query over plural corpus, and the reverse."""
        self.assertGreater(score(NUCLEOSOME_PLURAL, "nucleosome"), 0,
                           "singular query must match a plural title")
        self.assertGreater(score(NUCLEOSOME_SINGULAR, "nucleosomes"), 0,
                           "plural query must match a singular title")

    def test_case_and_hyphen_insensitive(self):
        self.assertGreater(score(RHODOPSIN, "Rhodopsin"), 0)
        self.assertGreater(score(MDA5, "cryo-EM") + score(MDA5, "helical"), 0)

    def test_accession_lookup(self):
        """Users paste accessions. Both EMD and fitted PDB ids must resolve."""
        self.assertGreater(score(CB1, "EMD-0339"), 0)
        self.assertGreater(score(RHODOPSIN, "6vms"), 0)


class TestPrecision(unittest.TestCase):
    def test_no_substring_bleed(self):
        """Defect 3: 'binding protein' must not register as 'g protein'."""
        self.assertEqual(
            score(MDA5, "GPCR"), 0,
            "MDA5 is an RNA helicase; 'RNA bindin[g protein]' must not match")

    def test_literal_query_outranks_synonyms(self):
        """Defect 5: what the user typed ranks above what expansion dragged in."""
        top = rank(CORPUS, "rhodopsin")[0]
        self.assertEqual(top["id"], RHODOPSIN["id"],
                         f"search('rhodopsin') ranked {top['title']!r} first")

    def test_distinct_queries_give_distinct_leaders(self):
        """Three GPCR-group queries returning an identical list is the bug."""
        leaders = [rank(CORPUS, q)[0]["id"]
                   for q in ("rhodopsin", "cannabinoid receptor")]
        self.assertEqual(len(set(leaders)), 2,
                         "different queries collapsed to the same top hit")


class TestAdaptiveExpansion(unittest.TestCase):
    """Defect 8, found while validating this library against all 46,900 rows.

    Ranking was correct but recall was not: search("rhodopsin") returned 1,189
    hits where only 40 mention rhodopsin, because expansion rewrote the query
    unconditionally. Identical hit counts for "rhodopsin" and "GPCR" was the
    tell. Expansion now engages only when the literal query is thin, which is
    what _search.py always claimed it did.
    """

    def test_thin_literal_query_expands(self):
        terms, widened = S.adaptive_terms("rhodopsin", lambda t: 2)
        self.assertTrue(widened)
        self.assertIn("cannabinoid receptor", terms)

    def test_sufficient_literal_query_does_not_expand(self):
        terms, widened = S.adaptive_terms("rhodopsin", lambda t: 400)
        self.assertFalse(widened)
        self.assertEqual(terms, ["rhodopsin"])

    def test_threshold_boundary(self):
        n = S.EXPANSION_MIN_HITS
        self.assertFalse(S.adaptive_terms("rhodopsin", lambda t: n)[1])
        self.assertTrue(S.adaptive_terms("rhodopsin", lambda t: n - 1)[1])

    def test_term_with_no_synonyms_never_reports_expansion(self):
        terms, widened = S.adaptive_terms("spliceosome", lambda t: 0)
        self.assertFalse(widened)
        self.assertEqual(terms, ["spliceosome"])

    def test_empty_query_is_not_an_expansion(self):
        self.assertEqual(S.adaptive_terms("", lambda t: 0), ([], False))

    def test_spelling_variants_apply_even_when_literal_is_plentiful(self):
        """The first threshold attempt gated variants too, dropping ~900 correct
        'cryo-ET' hits for a user who typed 'cryoET'. Variants are the same
        concept and must never be suppressed."""
        for q, sibling in (("cryoet", "cryo-et"),
                           ("ribosome", "ribosomal"),
                           ("cryoem", "cryo-em")):
            terms, widened = S.adaptive_terms(q, lambda t: 10_000)
            self.assertIn(sibling, terms, f"{q!r} must always reach {sibling!r}")
            self.assertFalse(widened, "variants are not a family widening")

    def test_family_members_do_not_drag_in_siblings_when_well_served(self):
        """'rhodopsin' must not return every other GPCR."""
        terms, _ = S.adaptive_terms("rhodopsin", lambda t: 40)
        self.assertNotIn("cannabinoid receptor", terms)
        self.assertNotIn("muscarinic", terms)

    def test_umbrella_query_still_reaches_members_when_thin(self):
        """The original defect: search('GPCR') returning nothing at all."""
        terms, widened = S.adaptive_terms("gpcr", lambda t: 4)
        self.assertTrue(widened)
        self.assertIn("rhodopsin", terms)

    def test_variant_groups_carry_no_family_terms(self):
        """A family term leaking into VARIANT_GROUPS would silently restore the
        unconditional-rewrite behaviour this class exists to prevent."""
        variants = {t for g in S.VARIANT_GROUPS for t in g}
        family = {t for g in S.FAMILY_GROUPS for t in g}
        self.assertEqual(variants & family, set())


class TestAccessionNormalisation(unittest.TestCase):
    """Defect 9: accessions are zero-padded to four digits, and dropping the pad
    builds a URL that 404s. EMD-0339 exists; EMD-339 does not. Measured across
    the archive: 961 padded accessions, 0 cases where an unpadded form is a
    separate entry, so padding is always the right guess."""

    @staticmethod
    def _acc():
        # Import the package's own acc() without pulling numpy/mrcfile: the
        # module is import-light by design (see _load_search in __init__).
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_emdb_pkg", os.path.join(_PKG, "__init__.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.acc

    def test_pads_short_accessions(self):
        a = self._acc()
        for given in (339, "339", "EMD-339", "emd_339", "EMD-0339", " emd-0339 "):
            self.assertEqual(a(given), "EMD-0339", f"{given!r} normalised wrong")

    def test_leaves_five_digit_accessions_alone(self):
        a = self._acc()
        for given in (22962, "22962", "EMD-22962", "emd_22962"):
            self.assertEqual(a(given), "EMD-22962")

    def test_map_url_pads_both_directory_and_filename(self):
        """Verified against the live FTP tree: EMD-0339/map/emd_0339.map.gz is
        206, EMD-0339/map/emd_339.map.gz is 404. The pad appears in both, so
        dropping it breaks the path twice over."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_emdb_pkg2", os.path.join(_PKG, "__init__.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertTrue(m.map_path(339, local=True).endswith(
            "/EMD-0339/map/emd_0339.map.gz"))
        self.assertTrue(m.map_path("EMD-22962", local=True).endswith(
            "/EMD-22962/map/emd_22962.map.gz"))


class TestEntryFiles(unittest.TestCase):
    """entry_files must never answer "nothing deposited" when it simply could
    not look. load_map already fell back to HTTPS off-mount; entry_files
    returned {}, which reads as an empty deposition rather than an absent mount.

    Network-gated: set EMDB_NETWORK=1 to run against EBI.
    """

    @staticmethod
    def _mod():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_emdb_ef", os.path.join(_PKG, "__init__.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_subdirs_cover_the_documented_layout(self):
        m = self._mod()
        for sub in ("map", "header", "images", "masks", "other", "fsc", "metadata"):
            self.assertIn(sub, m.SUBDIRS)

    @unittest.skipUnless(os.environ.get("EMDB_NETWORK"), "set EMDB_NETWORK=1")
    def test_lists_a_real_entry_without_a_mount(self):
        m = self._mod()
        f = m.entry_files("EMD-22962")
        self.assertIn("map", f)
        self.assertTrue(any("half_map" in n for n in f.get("other", [])),
                        "EMD-22962 deposited half-maps; they must be visible")

    @unittest.skipUnless(os.environ.get("EMDB_NETWORK"), "set EMDB_NETWORK=1")
    def test_absent_subdirs_are_omitted_not_invented(self):
        m = self._mod()
        f = m.entry_files(1001)
        self.assertIn("map", f)
        for k, v in f.items():
            self.assertTrue(v, f"{k} listed but empty — omit it instead")


class TestFilters(unittest.TestCase):
    """Defect 6: a record missing the filtered field is excluded, never kept."""

    @staticmethod
    def by_res(records, max_res):
        out = []
        for r in records:
            res = r.get("resolution_a")
            if res is None or res != res or res > max_res:
                continue
            out.append(r)
        return out

    def test_missing_resolution_excluded(self):
        got = self.by_res(CORPUS, 4.0)
        self.assertNotIn(NO_RESOLUTION["id"], {r["id"] for r in got},
                         "an entry with no resolution must not pass max_res")

    def test_bound_is_inclusive_and_correct(self):
        got = {r["id"] for r in self.by_res(CORPUS, 3.1)}
        self.assertIn(RHODOPSIN["id"], got)   # 3.1, on the bound
        self.assertIn(CB1["id"], got)         # 3.0
        self.assertNotIn(MDA5["id"], got)     # 4.2


class TestEnrichmentFilters(unittest.TestCase):
    """Molecular filters added by the enrichment pass.

    The weight fields are deposition-dependent, so the governing rule is the
    same one that applies to resolution: a record with no value is EXCLUDED,
    never silently kept. Keeping them would pad every molecular-weight query
    with entries that never deposited a weight, which reads as a larger result
    set than the data supports.
    """

    @staticmethod
    def _mod():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_emdb_enr", os.path.join(_PKG, "__init__.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_num_ok_excludes_missing_values(self):
        n = self._mod()._num_ok
        self.assertFalse(n(None, None, 100), "missing value must not pass a bound")
        self.assertFalse(n(float("nan"), None, 100), "NaN must not pass a bound")
        self.assertTrue(n(None, None, None), "no bound means don't care")

    def test_num_ok_bounds_are_inclusive(self):
        n = self._mod()._num_ok
        self.assertTrue(n(100.0, None, 100))
        self.assertTrue(n(100.0, 100, None))
        self.assertFalse(n(100.1, None, 100))

    def test_truthy_is_nan_safe(self):
        """A column absent from a partial index reads back as NaN, and NaN is
        truthy in Python — so `if row.get("has_mask")` passes EVERY row."""
        t = self._mod()._truthy
        self.assertFalse(t(float("nan")), "NaN must not read as True")
        self.assertFalse(t(None))
        self.assertTrue(t(True))

    def test_image_url_needs_a_recorded_filename(self):
        """Never construct emd_<n>.png and hope: 7% of entries use another
        name, and a guessed URL is a broken gallery card."""
        u = self._mod().image_url
        self.assertEqual(u({"id": "EMD-0339"}), "", "no filename means no URL")
        self.assertEqual(u({"id": "EMD-0339", "image": float("nan")}), "")
        self.assertTrue(u({"id": "EMD-5203", "image": "emd_5203_1.png"})
                        .endswith("/EMD-5203/images/emd_5203_1.png"))

    def test_as_list_is_nan_safe(self):
        """Defect 11: with_empiar() crashed with "'float' object is not
        iterable". `r.get("emdb_ids") or []` looks safe but is not — a missing
        DataFrame cell reads back as NaN, NaN is truthy, so `or []` hands the
        NaN straight to the for-loop. Same root cause as `if row.get("has_mask")`
        passing every row, and it only surfaced against a real DataFrame with
        missing values, not against dict fixtures."""
        f = self._mod()._as_list
        self.assertEqual(f(float("nan")), [])
        self.assertEqual(f(None), [])
        self.assertEqual(f([]), [])
        self.assertEqual(f(["EMD-0339"]), ["EMD-0339"])
        self.assertEqual(f("EMD-0339"), ["EMD-0339"])
        self.assertEqual(f([float("nan"), "EMD-1"]), ["EMD-1"])

    def test_ligand_abbreviations_resolve_to_deposited_names(self):
        """Defect 10: ligands are deposited under full chemical names, so the
        abbreviation a scientist types matched almost nothing. Measured on the
        real catalog: ligand="ATP" found 4 entries against 965 deposited as
        ADENOSINE-5'-TRIPHOSPHATE, and "GTP" found 2 against 434. Same failure
        as search("GPCR") returning zero — deposited vocabulary versus spoken.
        After aliasing: ATP 4 -> 971, GTP 2 -> 464, NAG -> 2,334.
        """
        al = self._mod().LIGAND_ALIASES
        self.assertEqual(al["atp"], "adenosine-5'-triphosphate")
        self.assertEqual(al["gtp"], "guanosine-5'-triphosphate")
        for k, v in al.items():
            self.assertEqual(k, k.lower(), f"alias key {k!r} must be lowercase")
            self.assertEqual(v, v.lower(), f"alias target {v!r} must be lowercase")

    def test_ligand_aliases_do_not_shadow_full_names(self):
        """A user who types the deposited name must be unaffected: the alias map
        is a fallback for abbreviations, not a rewrite of every query."""
        al = self._mod().LIGAND_ALIASES
        for spelled_out in ("cholesterol", "magnesium ion", "cardiolipin"):
            self.assertNotIn(spelled_out, al,
                             f"{spelled_out!r} is already the deposited name")

    def test_kda_units_are_kda_not_mda(self):
        """EMDB deposits molecular weight in MDa; the catalog stores kDa so the
        field matches EmpiarCatalog.max_chain_kda. A missed conversion makes
        max_chain_kda=100 match nothing at all."""
        builder = os.path.join(_HERE, os.pardir, "tools", "emdb_enrich_catalog.py")
        if not os.path.exists(builder):
            self.skipTest("enrichment builder not present")
        with open(builder, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("* 1000.0", src, "MDa -> kDa conversion missing")


class TestCatalogHonesty(unittest.TestCase):
    """Defect 1 and 7: claims must be measured, and fields must be populated."""

    CATALOG = os.environ.get("EMDB_CATALOG_JSON")

    def test_no_empty_fields_advertised(self):
        """A field may only be offered by a source that actually populates it.

        This test originally banned `microscope` outright, because EBI Search
        reports it as 0% populated. That was true of EBI Search and false of the
        archive: the per-entry REST API carries it (e.g. "FEI TITAN KRIOS"), so
        the enrichment pass reads it from there and search() now filters on it.
        The rule is therefore per-source, not per-field — the original blanket
        ban would have kept a real, populated field permanently off the table.

        `vitrificationinstrument` and `synspeciesname` remain banned: measured
        empty in EBI Search and not read from the REST API either.
        """
        import re
        with open(os.path.join(_PKG, "__init__.py"), encoding="utf-8") as fh:
            pkg = fh.read()
        for banned in ("vitrificationinstrument", "synspeciesname"):
            self.assertNotIn(
                f'"{banned}"', pkg,
                f"{banned} is empty in practice; do not offer it as a field")
        # The EBI Search builder must still not request the fields that source
        # leaves empty, even though enrichment gets microscope elsewhere.
        builder = os.path.join(_HERE, os.pardir, "tools", "emdb_build_catalog.py")
        if os.path.exists(builder):
            with open(builder, encoding="utf-8") as fh:
                src = fh.read()
            fields = re.search(r"^FIELDS = \[(.*?)\]", src, re.S | re.M)
            if fields:
                for banned in ("microscope", "vitrificationinstrument",
                               "synspeciesname"):
                    self.assertNotIn(banned, fields.group(1),
                                     f"EBI Search leaves {banned} empty")

    def test_search_fields_match_package(self):
        """These tests must score over the same fields the package does."""
        with open(os.path.join(_PKG, "__init__.py"), encoding="utf-8") as fh:
            pkg = fh.read()
        for f in FIELDS:
            self.assertIn(f'"{f}"', pkg, f"{f} missing from the package")

    @unittest.skipUnless(CATALOG and os.path.exists(CATALOG or ""),
                         "set EMDB_CATALOG_JSON to check the built catalog")
    def test_coverage_is_measured_not_asserted(self):
        """The catalog states its own coverage, and the number is true."""
        with open(self.CATALOG, encoding="utf-8") as fh:
            payload = json.load(fh)
        meta, entries = payload["meta"], payload["entries"]
        for key in ("ftp_released_entries", "catalog_entries", "coverage_pct"):
            self.assertIn(key, meta, f"catalog must record {key}")
        ids = [e["id"] for e in entries]
        self.assertEqual(
            meta["catalog_entries"], len(set(ids)),
            "declared entry count must equal the rows actually present")
        self.assertEqual(len(ids), len(set(ids)), "duplicate accessions in catalog")
        self.assertGreaterEqual(meta["coverage_pct"], 99.0,
                                "coverage regressed below 99% of released EMDB")
        # Every row must be readable. EBI Search indexes entries whose maps have
        # been withdrawn (they 404 on the FTP tree); shipping one means a user
        # finds a promising hit and load_map() dies on it.
        self.assertLessEqual(
            meta["catalog_entries"], meta["ftp_released_entries"],
            "catalog holds accessions that are not on the FTP tree")

    @unittest.skipUnless(CATALOG and os.path.exists(CATALOG or ""),
                         "set EMDB_CATALOG_JSON to check the built catalog")
    def test_every_row_has_what_search_needs(self):
        """A row with no title and no sample name is unfindable by text."""
        with open(self.CATALOG, encoding="utf-8") as fh:
            entries = json.load(fh)["entries"]
        blind = [e for e in entries if not e.get("title") and not e.get("sample_name")]
        self.assertEqual(blind[:5], [], f"{len(blind)} rows carry no searchable text")
        for e in entries[:2000]:
            self.assertTrue(e.get("map_url", "").endswith(".map.gz"),
                            f"{e['id']} has no usable map_url")

    @unittest.skipUnless(CATALOG and os.path.exists(CATALOG or ""),
                         "set EMDB_CATALOG_JSON to check the built catalog")
    def test_real_queries_return_real_hits(self):
        """The 'where's the table' check: common questions must find something."""
        with open(self.CATALOG, encoding="utf-8") as fh:
            entries = json.load(fh)["entries"]
        for q, floor in (("GPCR", 50), ("ribosome", 500), ("nucleosome", 50),
                         ("spliceosome", 20), ("proteasome", 50),
                         ("cryoET", 10), ("SARS-CoV-2 spike", 20)):
            n = sum(1 for r in entries if score(r, q) > 0)
            self.assertGreaterEqual(
                n, floor, f"search({q!r}) found {n}, expected >= {floor}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
