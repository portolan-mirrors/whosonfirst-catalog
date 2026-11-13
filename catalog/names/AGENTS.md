# AGENTS.md — Who's On First Gazetteer Name Index

Guidance for AI agents and automated clients working with this collection.

**One rule survives every edit to this file.** Every claim here is either
quoted from a source or measured from the data. If you cannot point at where a
fact came from, it does not belong in this file. An agent acting on an invented
join key or an invented column name produces a confident wrong answer, and
nothing downstream catches it.

Each factual claim is tagged with how it was established:
**[attested]** Who's On First or geocode.earth states it, with a link;
**[researched]** found outside the source's own metadata, with a link;
**[derived]** computed from the published data, with the query that computed
it. Every query below was run against the published files before this guide
was written.

> [!IMPORTANT]
> **The license is a mix.** Who's On First scopes CC0 to "the format and
> structure that allows Who's On First to operate" — the schema, not the
> records — and the records inherit terms from over 300 sources. Attribution
> is required: *Data from Who's On First.
> [License](https://whosonfirst.org/docs/licenses/).* Measured on this
> distribution's own
> `geom_src` column, 70.88% of the geometry is GeoNames under CC BY and 14
> records of 5,423,663 are share-alike. No ODbL source contributes geometry.
> Join `geom_src` to
> [whosonfirst-sources](https://github.com/whosonfirst/whosonfirst-sources)
> for a specific feature's license.

## Overview

**A name search sidecar, not a boundary dataset.** 5,405,294 places plus
4,073,485 alternative spellings, 9,478,779 rows, sorted by a folded form of the
name. Public root:
`https://data.source.coop/portolan-mirrors/whosonfirst-catalog/catalog.json`

```
names/wof_names.parquet  575.9 MiB, 9,478,779 rows, 741 row groups of 12,800
names/index.json  11,748 bytes, fetch first
names/wof_names_prominent.parquet  20.2 MiB, 285,735 rows, strict subset, load eagerly for instant + fuzzy search
```

**The prominent subset** **[derived]** is a strict row subset of the full index
(same schema, same `name_norm` sort, same `feature_id` and `geometry_ref`
values), selected by the measured criteria in the manifest's
`prominent_index.criteria` — including the english_guarantee: every place kept
is findable by its English spelling where the distribution carries one. Load it
whole on search-box focus; it is the only file a client's fuzzy (typo) fallback
can scan without downloading the full index, so a name absent here is
prefix-searchable but not typo-findable in range mode.

The `geometry` column is **one point per row**, the place's centroid. It is a
marker, not a shape: do not compute area, length or containment from this file.
The shape lives in the boundary collection at the row's `level`.

## Accessing the data

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
```

**Fetch [index.json](index.json) first** **[derived]**. It carries the index's
size (603,916,555 bytes), row group count (741), checksum, footer size
(1,713,128 bytes), the `catalog_version`
(`whosonfirst-admin-parquet-2025-04-07`) that must match the footer metadata of
this file and of every boundary file, the URL and row count of each boundary
and display file, and the attribution each source requires.

**Then range-request the index.** At 575.9 MiB this file is not meant to be
loaded whole. The manifest's `index.size` lets the footer read be one
exactly-sized tail request of 1,713,128 bytes rather than hyparquet's
speculative 512 KB default, with a further 431,565 bytes of page index read
lazily per column chunk **[derived: `tools/measure_index.py`]**.

## Schema & field notes

Every column is described in [collection.json](collection.json). The ones that
decide whether a query is right:

| column | what it is |
|---|---|
| `name_norm` | **the sort key.** NFD, combining marks dropped, only letters, digits, space, hyphen and apostrophe kept, whitespace collapsed, lowercased. Compared byte-wise on UTF-8, not by a locale collation |
| `name` | the spelling to display |
| `feature_id` | the place's `wof_id`. Joins to `wof_id` in a boundary collection |
| `alt_of` | null on a primary row; the row's own `feature_id` on an alternative-spelling row |
| `name_lang` | the ISO 639-3 code this spelling came from; null on a primary row |
| `level` | 0 to 5. **Which boundary collection to join** |
| `is_point` | whether the place's geometry is a point rather than a polygon |
| `geometry_ref` | advisory `{file, row_group, row}` into the boundary file and its display companion |

## Data quality & usage notes

**An alternative-spelling row shares its place's `feature_id`.** Dedupe results
on it, or the same city appears once per language **[derived]**:

```sql
SELECT count(*) AS rows, count(DISTINCT feature_id) AS places
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/names/wof_names.parquet';
```

**7,221,629 of 9,478,779 rows are points in their boundary collection**
**[derived]**. `is_point` says so per row. A client about to draw an outline
should check it first.

**The geometry_ref fast path, and why it must be verified.** `geometry_ref`
names a file, a row group and a row. A client range-reads that row group and
takes that row — and **must assert that row's `wof_id` equals the result's
`feature_id`** before trusting its geometry. If the pointer is stale the client
gets another place's polygon and nothing looks wrong: the geometry is valid,
the bbox is plausible, and the map flies somewhere else. On any mismatch, fall
back to locating the row by `wof_id`, which the boundary files' `(country,
wof_id)` sort and row group statistics make cheap. `tests/test_index_refs.py`
in the repository is the gate that resolves a sample of these pointers against
the real files.

**Because the display companion holds the same rows at the same offsets**, one
`geometry_ref` resolves against either file, so a client switching between
display and full resolution recomputes nothing.

**25 languages, not hundreds** **[derived]**. See the `name_lang` column
description: Who's On First carries names in hundreds of languages, and
geocode.earth's GeoParquet build carries 25 of them.

**Nothing here says whether a place still exists.** The GeoParquet build
carries no `mz:is_current`, `edtf:cessation`, `edtf:deprecated` or
`wof:superseded_by` **[derived]**, so a deprecated place can appear in this
index with no sign of it.

## Example queries

Each of these was run against the published index before this file was written.

Everything called Kyoto, in any of the languages this index carries:

```sql
INSTALL httpfs; LOAD httpfs;

SELECT name, name_lang, level, placetype, country, parent_name
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/names/wof_names.parquet'
WHERE name_norm = 'kyoto'
ORDER BY level, population DESC NULLS LAST;
```
```
Kyoto  tur  1  region  JPN  Japan
Kyōto  deu  2  county  JPN  Kyoto
Kyōto  deu  4  locality  JPN  Kyoto
Kyōto  deu  4  locality  TZA  Muleba
```

A prefix lookup, which is what the sort exists for:

```sql
SELECT name, level, country, parent_name, population
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/names/wof_names.parquet'
WHERE name_norm >= 'zuri' AND name_norm < 'zurj'
  AND alt_of IS NULL
ORDER BY population DESC NULLS LAST LIMIT 5;
```
```
Zürich  3  CHE  Zurich  396955
Zürich (Kreis 11)  5  CHE  Zürich  54260
Zürich (Kreis 3)  5  CHE  Zürich  46018
Zürich (Kreis 9)  5  CHE  Zürich  44878
Zürich (Kreis 10)  5  CHE  Zürich  36216
```

The most ambiguous place names in the world, which is why `name_dupes` exists:

```sql
SELECT any_value(name) AS example, max(name_dupes) AS places
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/names/wof_names.parquet'
GROUP BY name_norm ORDER BY places DESC LIMIT 8;
```
```
１丁目  2,413
２丁目  2,059
San Antonio  1,828
סן אנטוניו  1,788
Сан-Антоніо  1,770
Сан-Антонио  1,765
سان أنطونيو  1,765
サンアントニオ  1,763
```

The join back to geometry, branching on `level`:

```sql
SELECT n.name, n.country, b.area_km2, b.vertices
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/names/wof_names.parquet' n
JOIN 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/country/wof_country.parquet' b
  ON b.wof_id = n.feature_id
WHERE n.level = 0 AND n.alt_of IS NULL
ORDER BY b.area_km2 DESC LIMIT 5;
```
```
روسيا  RUS  16975473.0  480671
القارة القطبية الجنوبية  ATA  12358174.0  23835
كندا  CAN  9875450.0  129056
الولايات المتحدة  USA  9833548.0  75410
الصين  CHN  9377064.0  238558
```

## Related collections

| level | collection | placetypes |
|---|---|---|
| 0 | [`country`](../country/collection.json) | `country`, `dependency`, `disputed` |
| 1 | [`region`](../region/collection.json) | `macroregion`, `region` |
| 2 | [`county`](../county/collection.json) | `macrocounty`, `county` |
| 3 | [`localadmin`](../localadmin/collection.json) | `localadmin` |
| 4 | [`locality`](../locality/collection.json) | `locality`, `borough` |
| 5 | [`neighbourhood`](../neighbourhood/collection.json) | `macrohood`, `neighbourhood`, `microhood` |

Branch on `level` to pick the collection, then join `names.feature_id` to that
collection's `wof_id`.

Two sibling catalogs are built to the same index contract: [geoBoundaries
CGAZ](https://source.coop/portolan-mirrors/geoboundaries-catalog) under
CC-BY-4.0 and [Overture
divisions](https://source.coop/portolan-mirrors/cn-gazetteer-overture) under
ODbL. A client configurable to any of the three can filter on one code system,
because all three publish `country` as ISO 3166-1 alpha-3.

