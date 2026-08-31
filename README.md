# scigantic-emdb

[![CI](https://github.com/Scigantic/scigantic-emdb/actions/workflows/ci.yml/badge.svg)](https://github.com/Scigantic/scigantic-emdb/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/scigantic-emdb)](https://pypi.org/project/scigantic-emdb/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/scigantic-emdb)](https://pypi.org/project/scigantic-emdb/)
[![License](https://img.shields.io/github/license/Scigantic/scigantic-emdb)](https://github.com/Scigantic/scigantic-emdb/blob/main/LICENSE)

Search every structure in [EMDB](https://www.ebi.ac.uk/emdb/), EMBL-EBI's public archive of 3D cryo-EM density maps, and read one in two calls.

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

## Why this exists

Reading an EMDB map is easy. A map is 20 to 60 MB and `mrcfile` opens it. What EMDB lacks is a way to answer "which of these 60,895 structures do I want" without already knowing the accession. This is that index.

## Searching

```python
cat.search("spliceosome", max_res=3.5)
cat.search("GPCR", max_chain_kda=100, has_half_maps=True)
cat.search("protease", ligand="ATP", has_model=True)
cat.search("capsid", microscope="KRIOS", min_year=2023)
cat.search(min_proteins=2, has_ligand=True)          # a complex with something bound
cat.search("ribosome", has_raw_data=True, max_raw_gb=2000)
```

Filters: `max_res`, `min_res`, `organism`, `method`, `microscope`, `ligand`, `has_pdb`, `has_uniprot`, `has_model`, `has_half_maps`, `has_mask`, `has_ligand`, `min_proteins`, `max_proteins`, `max_chain_kda`, `complex_kda_max`, `has_raw_data`, `max_raw_gb`, `year`, `min_year`, `max_year`. Sort by `relevance`, `resolution`, `year`, `raw_size` or `id`.

`max_chain_kda` is the largest single protein chain, which is what you want for "a receptor under 100 kDa". The assembled complex carries the G protein and often a nanobody, so it is almost always heavier than the molecule of interest. Measured across the catalog, entries with a chain at or under 100 kDa have a median complex weight of 240 kDa.

## Coverage

```python
cat.coverage()
# {'catalog_entries': 60895, 'ftp_released_entries': 60895, 'coverage_pct': 100.0, ...}
```

Every released EMDB entry is indexed. That took two sources: EBI Search covers only 46,900 of them (76.9%), so the remaining 14,042 come from the per-entry REST API.

Molecular fields depend on what each group chose to deposit, so they are not universal:

| field | fill |
|---|---|
| `microscope`, `box`, `map_mb` | 100% |
| `image` | 99.0% |
| `contour_level` | 95.2% |
| `has_half_maps` | 67.2% |
| `complex_kda` | 59.1% |
| `max_chain_kda` | 58.5% |
| `has_mask` | 26.4% |
| `has_raw_data` | 8.2% |

A record missing the field you filter on is excluded, never silently kept. So "12 structures match" means twelve among those that deposited a weight, not twelve in EMDB. Read the real numbers from `cat.coverage()["enrichment"]["field_fill_pct"]`.

## Images

EBI publishes a rendered isosurface for about 97% of entries, so a gallery reads no maps and copies no pixels. The catalog stores the filename and each card points at EBI's public URL.

```python
cat.gallery(cat.search("spliceosome", max_res=4.0).head(8))
```

## Raw data, and which structures you can reprocess

EMDB holds the reconstruction. [EMPIAR](https://github.com/scigantic/scigantic-empiar) holds the raw movies it was computed from, when the authors deposited them.

```python
cat.search("GPCR", max_res=3.0, has_raw_data=True, sort="raw_size")
```
```
       id  resolution_a empiar_ids  raw_size_gb
EMD-24900          2.60    [10852]       1331.2
EMD-24898          2.90    [10854]       1638.4
```

Two things to know before planning a reprocessing run. Only 8.2% of EMDB (5,007 of 60,895) has public raw data, because most groups never deposit it. And those datasets are large: of the sub-3 Å GPCR structures with public movies, none is under 1 TB and the cheapest is 1,331 GB. `max_raw_gb` is the difference between reprocessable and reprocessable by you.

Only EMPIAR records this link. EMDB's own API exposes citations and PDB references but never mentions EMPIAR, so the cross-reference is built from EMPIAR's side.

`cat.with_empiar(hits)` returns the full pairing when you want the EMPIAR entries themselves.

## Half-maps

67% of entries deposit half-maps: two reconstructions built from independent halves of the data, kept separate so the agreement between them measures how much detail is real. With them you can recompute an FSC rather than trusting the reported resolution. Filter with `has_half_maps=True`.

## How search works

Free text runs over title, sample name, organism, method and accessions, with a small cryo-EM synonym vocabulary. What you literally typed always ranks first.

Expansion is a fallback, not a rewrite. Spelling variants (`cryoet` to `cryo-et`, `ribosome` to `ribosomal`) always apply. Family expansion (`GPCR` to its 30+ member receptors) engages only when the literal query is thin, because at this scale an unconditional rewrite turned `search("rhodopsin")` into 1,189 hits of which 40 mentioned rhodopsin. `cat.last_query_expanded` tells you which happened.

Ligand abbreviations resolve to the deposited chemical names, so `ligand="ATP"` matches the 965 entries filed as `ADENOSINE-5'-TRIPHOSPHATE` rather than the 4 that spell it "ATP".

`has_ligand=True` counts only notable molecules: nucleotides, cofactors, inhibitors, drugs. It excludes ions, water, glycosylation sugars and the lipids and detergents used in sample prep, which are 34,700 of the 56,321 deposited ligand mentions. Counting those would report 37.2% of EMDB as ligand-bound; the honest figure is 21.9%. Use `ligand="..."` to match the full list by name, including ions.

## Relationship to scigantic-empiar

The query layer is imported from [`scigantic-empiar`](https://pypi.org/project/scigantic-empiar/), never copied, so both archives share one implementation and its fixes cannot diverge. See `SYNC.md`. It is also why `with_empiar()` works with no extra setup.

## Notes

- The catalog is a prebuilt index fetched over HTTPS, about 13 MB gzipped, loading in roughly two seconds. Nothing else is downloaded until you read a map.
- `load_map()` works with or without the archive mounted. Off-mount it fetches from EBI.
- `entry_files()` reports only what an entry actually deposited. Half-maps, masks and FSC curves are per-deposition, so check rather than assume.
- Accessions are zero-padded to four digits. `acc(339)` gives `EMD-0339`, which is the entry that exists.
- Inside a [Scigantic](https://scigantic.com) cryo-EM notebook this is preinstalled and the archive is also FUSE-mounted. Standalone, it streams straight from EBI.

MIT licensed. EMDB data is CC0. Please cite EMDB.
