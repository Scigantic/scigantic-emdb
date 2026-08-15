# scigantic-emdb

Search every structure in [EMDB](https://www.ebi.ac.uk/emdb/) — EMBL-EBI's public archive of **3D cryo-EM density maps** — from Python, and read one in two calls.

```bash
pip install "scigantic-emdb[maps]"
```

```python
from scigantic_emdb import EmdbCatalog, load_map, slices

cat = EmdbCatalog()
cat.search("GPCR", organism="Homo sapiens", max_res=3.0, sort="resolution")

vol, meta = load_map("EMD-22962")   # decompresses, caches, opens
slices(vol)                          # central XY / XZ / YZ sections
```

## Why

EMDB's I/O is easy: a map is 20–60 MB and `mrcfile` opens it. What EMDB lacks is any way to answer *"which of these 60,895 structures do I want"* short of already knowing the accession. This is that index.

```python
cat.search("spliceosome", max_res=3.5)
cat.search("GPCR", max_chain_kda=100, has_half_maps=True)
cat.search("protease", ligand="ATP", has_model=True)
cat.search("capsid", microscope="KRIOS", min_year=2023)
```

`max_chain_kda` is the largest **single protein chain**, which is the filter you want for "a receptor under 100 kDa". The assembled complex carries the G protein and any nanobodies, so it is almost always heavier than the molecule of interest — measured across the catalog, entries with a chain ≤100 kDa have a *median complex weight of 240 kDa*.

## Coverage is measured, not asserted

```python
cat.coverage()
# {'catalog_entries': 60895, 'ftp_released_entries': 60895, 'coverage_pct': 100.0, ...}
```

Every released EMDB entry is in the index. Getting there took two sources: EBI Search indexes only 46,900 of them (76.9%), so the remaining 14,042 come from the per-entry REST API.

Molecular fields come from what each group chose to deposit and are **not universal**:

| field | fill | | field | fill |
|---|---|---|---|---|
| `microscope`, `box`, `map_mb` | 100% | | `complex_kda` | 59.1% |
| `image` | 99.0% | | `max_chain_kda` | 58.5% |
| `contour_level` | 95.2% | | `ligands` | 37.2% |
| `has_half_maps` | 67.2% | | `has_mask` | 26.4% |

A record missing the field being filtered on is **excluded**, never silently kept. So "12 structures match" means twelve among those that deposited a weight, not twelve in EMDB. Read the real numbers from `cat.coverage()["enrichment"]["field_fill_pct"]` rather than presenting a filtered count as the whole picture.

## Galleries cost nothing

EBI already publishes a rendered isosurface for ~97% of entries, so a gallery involves no map reads and copies no pixels — the catalog stores the filename and the card points at EBI's public URL.

```python
cat.gallery(cat.search("spliceosome", max_res=4.0).head(8))
```

## Cross-archive: which of these can I reprocess?

EMDB says what was solved; [EMPIAR](https://github.com/scigantic/scigantic-empiar) says whether the raw movies are public. Neither answers this alone.

```python
cat.with_empiar(cat.search("GPCR", max_res=3.0))
# emdb_id    resolution_a  empiar_id  raw_size_gb
# EMD-13880  2.70          10877      4198.4
```

## Search behaviour worth knowing

Free text runs over title, sample name, organism, method and accessions, with a small cryo-EM synonym vocabulary, and what you literally typed always ranks first.

Expansion is a **recall fallback, not a query rewrite**. Spelling variants (`cryoet` → `cryo-et`, `ribosome` → `ribosomal`) always apply. Family expansion (`GPCR` → its 30+ member receptors) engages only when the literal query is thin, because at 60,895 entries an unconditional rewrite turned `search("rhodopsin")` into 1,189 hits of which only 40 mentioned rhodopsin. `cat.last_query_expanded` tells you which happened.

Ligand abbreviations resolve to deposited chemical names: `ligand="ATP"` matches the 965 entries deposited as `ADENOSINE-5'-TRIPHOSPHATE`, not the 4 that spell it "ATP".

## Relationship to scigantic-empiar

The query layer is **imported** from [`scigantic-empiar`](https://pypi.org/project/scigantic-empiar/), never copied. Both archives share one implementation, so the fixes it carries cannot diverge between them. That is also why `with_empiar()` works without extra setup.

## Notes

- The catalog is a prebuilt index fetched over HTTPS (~13 MB gzipped, loads in about two seconds). Nothing is downloaded until you read a map.
- `load_map()` works with or without the archive mounted; off-mount it fetches from EBI.
- `entry_files()` reports only what an entry actually deposited. Half-maps, masks and FSC curves are per-deposition, so check rather than assume.

MIT licensed. EMDB data is CC0; please cite EMDB.
