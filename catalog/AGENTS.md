# AGENTS.md — Who's On First: a Cloud-Native Gazetteer

Guidance for AI agents and automated clients working with this catalog.

**One rule survives every edit to this file.** Every claim here is either
quoted from a source or measured from the data. If you cannot point at where a
fact came from, it does not belong in this file. An agent acting on an
invented join key or an invented column name produces a confident wrong
answer, and nothing downstream catches it.

Each factual claim is tagged with how it was established:
**[attested]** Who's On First or geocode.earth states it, with a link;
**[researched]** found outside the source's own metadata, with a link;
**[derived]** computed from the published data.

> [!IMPORTANT]
> **The license is a mix.** Who's On First scopes CC0 to "the format and
> structure that allows Who's On First to operate" — the schema, not the
> records — and the records inherit terms from over 300 sources. Attribution
> is required: *Data from Who's On First.
> [License](https://whosonfirst.org/docs/licenses/).* Measured on this
> distribution's own `geom_src` column, 70.88% of the geometry is GeoNames
> under CC BY and 14 records of 5,423,663 are share-alike. No ODbL source
> contributes geometry.

## What this catalog holds

Public root:
`https://data.source.coop/portolan-mirrors/whosonfirst-catalog/catalog.json`

| collection | level | places | holds |
|---|---|---|---|
| [`country`](country/collection.json) | 0 | 353 | `country`, `dependency`, `disputed` |
| [`region`](region/collection.json) | 1 | 4,362 | `macroregion`, `region` |
| [`county`](county/collection.json) | 2 | 42,115 | `macrocounty`, `county` |
| [`localadmin`](localadmin/collection.json) | 3 | 164,756 | `localadmin` |
| [`locality`](locality/collection.json) | 4 | 4,796,292 | `locality`, `borough` |
| [`neighbourhood`](neighbourhood/collection.json) | 5 | 397,416 | `macrohood`, `neighbourhood`, `microhood` |
| [`names`](names/collection.json) | all | 9,478,779 rows | the gazetteer name index |

[Who's On First](https://whosonfirst.org/) produces the data;
[geocode.earth](https://geocode.earth/data/whosonfirst/combined/) builds and
hosts the distribution this catalog describes. Only the **combined
administrative** distribution is carried here. Postcodes and constituencies
are separate upstream files and are not in this catalog
**[attested, geocode.earth's inventory]**.

**This is place-name and boundary lookup, not address geocoding.** There is no
street and no house number anywhere in Who's On First's administrative
distribution **[derived: the upstream file has 57 columns and none of them is
an address component]**.

## This is a metadata-first catalog

Most Portolan mirrors copy the upstream bytes. This one does not. Every
collection carries **geocode.earth's own files as assets**, at their original
URLs, with the size and sha256 their inventory records — the GeoParquet, the
PMTiles, the SQLite, the SpatiaLite, the GeoJSON bundle, and the inventory
itself.

What is built here is only what a measurement says those files cannot do, and
[changes-from-upstream.md](changes-from-upstream.md) carries every number. The
short version:

- **Per-level GeoParquet**, sorted by `(country, wof_id)` in exactly-full row
  groups under a megabyte. One place's geometry from the upstream combined
  file costs a median of 38 MiB and up to 285 MiB, because it has 83 row
  groups of 65,536 rows and 89% of its bytes in one column **[derived]**.
- **A display-simplified companion for levels 0 to 3**, and deliberately not
  for 4 and 5: a median country is 4,866 coordinates and a median locality is
  **one** **[derived]**.
- **PMTiles capped at 400 KB per tile.** geocode.earth's own archive is built
  with `--no-tile-size-limit` and its whole-world tile is 15,671,392 bytes
  **[derived]**.
- **The gazetteer name index**, which has no upstream equivalent.

Nothing else is changed. No place is added, no attribute value is edited, and
no geometry is moved except the 480 of 5,405,294 that failed `ST_IsValid`
upstream and are flagged with `geometry_repaired` **[derived]**.

## Start here

Column meanings, the traps and worked queries live in the collection guides.
Read the one for the level you are querying:
[`country`](country/AGENTS.md), [`region`](region/AGENTS.md),
[`county`](county/AGENTS.md), [`localadmin`](localadmin/AGENTS.md),
[`locality`](locality/AGENTS.md),
[`neighbourhood`](neighbourhood/AGENTS.md), [`names`](names/AGENTS.md).

## The traps that produce wrong answers

**1. `level` is this catalog's mapping, not WOF's.** Who's On First has no
administrative level number; it has placetypes with their own hierarchy
**[attested, [whosonfirst-placetypes](https://github.com/whosonfirst/whosonfirst-placetypes)]**.
The mapping is:

| level | placetypes |
|---|---|
| 0 | `country`, `dependency`, `disputed` |
| 1 | `macroregion`, `region` |
| 2 | `macrocounty`, `county` |
| 3 | `localadmin` |
| 4 | `locality`, `borough` |
| 5 | `macrohood`, `neighbourhood`, `microhood` |

A level is a *tier*, and a tier can hold a unit and its own subdivision: WOF
files `macroregion` above `region`, `microhood` below `neighbourhood`, and
`borough` below `locality`, without adding rungs anyone else recognizes. The
`placetype` column is on every row, so nothing about which placetype a place
actually is gets lost in the folding.

**2. Most localities and neighbourhoods are points, not polygons.** 4,031,001
of 4,796,292 localities and 334,785 of 397,416 neighbourhoods have a single
coordinate **[derived]**, because most of them come from GeoNames, which is a
point gazetteer. Check `vertices = 1`, or `is_point` in the names index,
before drawing an outline or computing an area.

**3. `parent_id` is not always an identifier.** WOF reserves `-1` "unknown
parent, record needs review", `-2` "shrug, this feature is complicated", `-3`
"contested, but not disputed", `-4` "multiple 'legal' parents"
**[attested, [wof properties](https://whosonfirst.org/docs/properties/wof/)]**.
This build maps `-1` to null and carries the other three through, so a join on
`parent_id` has to exclude them.

**4. Nothing here says whether a place still exists.** `mz:is_current`,
`edtf:cessation`, `edtf:deprecated` and `wof:superseded_by` are not carried by
geocode.earth's GeoParquet build **[derived]**. Pelias's own active-record
filter needs all four. A deprecated place can appear in this catalog with no
sign of it. Read the
[SQLite distribution](https://data.geocode.earth/wof/dist/sqlite/whosonfirst-data-admin-latest.db.bz2)
if currency matters.

**5. The index carries 25 languages, not hundreds.** Who's On First carries
names in hundreds — one San Francisco record has 214 `name:*` properties
**[attested, [wof names](https://whosonfirst.org/docs/names/)]** — and
geocode.earth's GeoParquet build flattens them to 25 fixed columns
**[derived]**. The SQLite and GeoJSON distributions have the rest.

**6. The GeoParquet vintage is six months behind the other formats.** The
build this catalog mirrors is from 2025-04-07; the SQLite, SpatiaLite,
GeoJSON-bundle and PMTiles builds of the same repository are from 2025-10-14
and come from a different WOF tree **[attested, geocode.earth's
inventory.json]**. A count from here and a count from the SQLite distribution
are two vintages, not a discrepancy. The HTTP `Last-Modified` header reads
2025-10-30 on every upstream object because the bucket was re-copied then; it
is not a vintage signal.

**7. The full hierarchy and the full concordance set are not here.** The
GeoParquet build flattens `wof:hierarchy` to three ancestor-id columns and
`wof:concordances` to a **single** key/id pair **[derived: 30 distinct
concordance keys across 4,282 populated level-1 rows, one per row]**. A place
with several concordances loses all but one of them in this distribution.

**8. `country` is derived; `country_iso2` is WOF's own.** WOF publishes a
two-letter code and mints six of its own that ISO does not have — `XK`
Kosovo, `XN` Null Island, `XS` Somaliland, `XX` disputed, `XY` undetermined,
`XZ` no country
**[attested, [whosonfirst-placetypes](https://github.com/whosonfirst/whosonfirst-placetypes)]**.
Those have no alpha-3, so `country` carries the two-letter code for them.

## Join keys

| from | to | on | uniqueness |
|---|---|---|---|
| `names` | the boundary collection at `names.level` | `names.feature_id = wof_id` | many:1 — an alternative-spelling row repeats its place's id |
| any collection | its parent's collection | `parent_id = wof_id` | many:1, and `parent_id` may be a negative sentinel |
| any collection | `country` | `country_wof_id = wof_id` | many:1 |
| any collection | `region` | `region_wof_id = wof_id` | many:1 |
| any collection | `county` | `county_wof_id = wof_id` | many:1 |

Every identifier in this catalog is a **string**, including `wof_id`,
`parent_id` and the three ancestor columns, so nothing needs a cast to join.
Upstream, `id` and `parent_id` are INT32 and the ancestor columns are
JSON-typed strings.

Branch on `names.level` to pick the collection. The names index also carries
an advisory `geometry_ref` that points straight at the row group and row in
the boundary file, which turns the geometry fetch into one range read — see
[`names/AGENTS.md`](names/AGENTS.md) for the verification it requires.

## How to read it

Everything is readable in place over HTTPS, with no credentials.

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

SELECT placetype, count(*) AS places
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/neighbourhood/wof_neighbourhood.parquet'
GROUP BY 1 ORDER BY 2 DESC;
```
```
neighbourhood  394020
microhood        2168
macrohood        1228
```

The PMTiles archives are for drawing, one per level plus one for the index
points. The GeoParquet files are for querying. Do not download a GeoParquet
file to draw a map: the locality file is 1.4 GiB and its PMTiles archive is a
fraction of that.

## How this catalog was built

Ten scripts in the
[source repository](https://github.com/portolan-mirrors/whosonfirst-catalog/tree/main/tools),
each runnable on its own:

```bash
python3 tools/fetch_sources.py       # 5.5 GiB from geocode.earth, verified
python3 tools/measure_upstream.py    # -> docs/upstream-measurements.md
python3 tools/build_boundaries.py    # -> 6 GeoParquet files
python3 tools/build_display.py       # -> 4 display companions
python3 tools/build_names.py         # -> the index and its manifest
python3 tools/build_pmtiles.py       # -> 7 PMTiles archives
python3 tools/measure_index.py       # -> docs/index-measurements.md
python3 tools/make_styles.py         # -> the style JSONs
python3 tools/make_collections.py    # -> 7 collection.json
python3 tools/make_docs.py           # -> 14 README and AGENTS files
```

`tools/distributions.sql` reruns every distribution behind every style class
break and every count this catalog's prose quotes.

The tool chosen at each step, and why:

| step | tool | why that one |
|---|---|---|
| The download | `curl`, no resume | The host sometimes answers a `Range` request with a 200 and the whole body, so `curl -C -` appended a second copy and produced 9,164,361,132 bytes where 5,948,636,588 was expected. Each attempt starts over and the size is checked against the host's own `Content-Length`. |
| Reshaping and measuring | DuckDB 1.4 with `spatial` | `ST_Area_Spheroid`, `ST_NPoints` and the geometry repair in one pass over 5.4M rows. |
| The Parquet write | PyArrow, streamed | The only writer here that honours an exact small row group size and writes the page index. Streaming also avoids DuckDB's 2 GiB Arrow binary-offset limit, which the locality geometry column exceeds on its own. |
| Geometry repair | DuckDB `ST_MakeValid` + `ST_CollectionExtract(..., 3)` | Applied only where `ST_IsValid` is false, so 5,404,814 of 5,405,294 geometries pass through unchanged. |
| Display geometry | `ST_SimplifyPreserveTopology` then `ST_Buffer` | Buffering outward is what makes the result safe as a spatial filter. Two quadrant segments, or the buffer puts back the coordinates simplification removed. |
| Vector tiles | `ogr2ogr -f GeoJSONSeq` piped to `tippecanoe` | No intermediate GeoJSON on disk. `--detect-shared-borders` keeps a shared edge between neighbours simplified identically. |
| Validation | `gpq validate`, `rashid`, `stac-check` | Plus `tests/test_index_refs.py`, which resolves a sample of the index's `geometry_ref` pointers against the real boundary files, and `tests/test_styles.py`, which counts the rows each legend class would colour. |

## Structure

Assets and structural links resolve relative to the object that carries them.
