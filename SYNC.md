# Where the query layer lives

`scigantic_emdb` does **not** contain a search implementation. It imports one
from `scigantic-empiar`:

    from scigantic_empiar import _search

That is deliberate. Both archives share a single query layer, so the fixes it
carries cannot diverge between them:

- `search("GPCR")` returning zero, because neither archive tags a structure as
  "a GPCR"
- `"g protein"` matching inside `"bindin[g protein]"`, scoring a helicase as a
  GPCR hit
- word boundaries then losing plurals, so `"nucleosome"` stopped matching
  `"nucleosomes"`
- synonym expansion outranking the literal query
- unconditional expansion, which at 60,895 entries turned `search("rhodopsin")`
  into 1,189 hits of which 40 mentioned rhodopsin

Those cost real users real dead ends. A second copy means finding each of them
twice, and the copy nobody remembers is the one users get. If the vocabulary or
the matching needs to change, change it in `scigantic-empiar` and bump the
dependency here.
