# Who's On First: a Cloud-Native Gazetteer

[Who's On First](https://whosonfirst.org/) is an open gazetteer. It holds
named administrative places — countries, regions, counties, local
administrative units, towns, boroughs, neighbourhoods — each with a stable
numeric identifier, a placetype, a parent, names in many languages, and a
record of which source its geometry came from.

This catalog describes it as
[geocode.earth](https://geocode.earth/data/whosonfirst/combined/) distributes
it, and adds the few files a browser needs to search it.

**It is place-name and boundary lookup, not address geocoding.** Who's On
First's administrative distribution holds no street and no house number.

## What is here

| collection | level | places | holds |
|---|---|---|---|
| [`country`](country/) | 0 | 353 | `country`, `dependency`, `disputed` |
| [`region`](region/) | 1 | 4,362 | `macroregion`, `region` |
| [`county`](county/) | 2 | 42,115 | `macrocounty`, `county` |
| [`localadmin`](localadmin/) | 3 | 164,756 | `localadmin` |
| [`locality`](locality/) | 4 | 4,796,292 | `locality`, `borough` |
| [`neighbourhood`](neighbourhood/) | 5 | 397,416 | `macrohood`, `neighbourhood`, `microhood` |
| [`names`](names/) | all | 9,478,779 rows | the gazetteer name index |

5,405,294 places in all, which is 99.66% of the 5,423,663 rows geocode.earth's
combined administrative distribution carries. The other 18,369 are placetypes
that are not land administration — `campus`, `postalregion`, `marinearea`,
`marketarea`, `timezone`, `ocean` — plus `continent` and `empire`, which sit
above the country rung and so have no place on a 0-based ladder.
[changes-from-upstream.md](changes-from-upstream.md) lists every one with its
count and its reason.

**Who's On First has no administrative level number.** It has placetypes,
arranged in a hierarchy of its own. The `level` column in every file here is
this catalog's mapping of those placetypes onto the 0-to-5 ladder a name
search needs, and it is defined in exactly one place in the
[source repository](https://github.com/portolan-mirrors/whosonfirst-catalog).
A level is a *tier*: a tier can hold a unit and its own subdivision, because
WOF inserts `macroregion` above `region` and `microhood` below
`neighbourhood` without adding a rung anyone else recognizes.

## Why this catalog links to geocode.earth instead of copying it

geocode.earth's combined GeoParquet is already cloud-native: GeoParquet 1.1
with a `covering` bbox, spatially clustered, served over HTTPS with range
requests and `Access-Control-Allow-Origin: *`. A planet-wide aggregate over it
takes seconds from a laptop. Copying it would produce a staler duplicate of a
file that already works.

So every collection here carries geocode.earth's own files as assets — the
GeoParquet, the PMTiles, the SQLite, the SpatiaLite, the GeoJSON bundle, and
their inventory — at their original URLs, with the size and sha256 their
inventory records.

What this catalog builds is only what a measurement says those files cannot
do. Three measurements, all reproducible from the
[source repository](https://github.com/portolan-mirrors/whosonfirst-catalog):

**Fetching one place's geometry from the upstream GeoParquet costs tens of
megabytes.** It has 83 row groups of 65,536 rows, no declared sort, and 89% of
its bytes in the `geometry` column, so one row group's geometry chunk is a
median of 38 MiB and as much as 285 MiB. Every Parquet reader is
row-group-granular, so that is the cost of decoding a single row. Filtering to
one placetype prunes nothing either, because `placetype` statistics span most
of the alphabet in most row groups.

**The upstream PMTiles archive cannot be opened at low zoom.** It is 2.0 GiB
over zoom 0 to 9 with one layer per placetype, built with
`tippecanoe -zg --no-tile-size-limit`. Its whole-world tile is 15,671,392
bytes and its mid zooms reach 26 MB. It also reports dropping 4,412,845
features by rate at zoom 0 to fit what it does carry, so the low zooms are
both heavy and incomplete.

**Nothing upstream answers "what places are called something like *this*".**
That is what a gazetteer is for, and it needs a file sorted by name.

So this catalog adds, per level: one GeoParquet sorted by `(country, wof_id)`
in exactly-full row groups under a megabyte each; a display-simplified
companion for the four levels whose geometry is heavy enough to need one; and
vector tiles capped at 400 KB per tile. Plus one gazetteer index.

## Which file to read

| you want | read |
|---|---|
| To find a place by name | `names/wof_names.parquet`, after `names/index.json` |
| To draw one outline, now | `{level}/wof_{level}_display.parquet` (levels 0–3) |
| To draw many at once | `{level}/{level}.pmtiles` |
| To clip, measure, export or analyse one place | `{level}/wof_{level}.parquet` |
| To scan the planet, or all 21 placetypes at once | [geocode.earth's combined GeoParquet](https://data.geocode.earth/wof/dist/parquet/whosonfirst-data-admin-latest.parquet) |
| The full hierarchy, every language, or the temporal fields | [geocode.earth's SQLite distribution](https://data.geocode.earth/wof/dist/sqlite/whosonfirst-data-admin-latest.db.bz2) |

The last row matters more than it looks. geocode.earth's GeoParquet build is a
flattened projection of Who's On First, and three things do not survive it:
the full `wof:hierarchy`, the full `wof:concordances`, and every temporal and
deprecation field (`mz:is_current`, `edtf:cessation`, `edtf:deprecated`,
`wof:superseded_by`). **So nothing in this catalog can tell you whether a
place still exists.** If that matters, the SQLite distribution is where to
look, and it is an asset of every collection here.

Names are the same story in miniature. WOF carries names in hundreds of
languages — one San Francisco record has 214 `name:*` properties — and the
GeoParquet build carries 25 of them. The index here is as multilingual as the
GeoParquet allows, and no more.

## Vintage

There are no versioned URLs upstream. Every file is named `-latest` and
overwritten in place, so the vintage comes from geocode.earth's inventory, not
from a URL.

| distribution | built |
|---|---|
| GeoParquet, which this catalog is built from | 2025-04-07 |
| PMTiles | 2025-10-14 |
| SQLite, SpatiaLite, GeoJSON bundle | 2025-10-14 |

**The GeoParquet build is about six months behind the others, from a different
WOF tree.** A count taken from this catalog and a count taken from the SQLite
distribution are two vintages, not a discrepancy. The HTTP `Last-Modified`
header on every upstream object reads 2025-10-30 because the bucket was
re-copied then; it is not a vintage signal.

## License

`other`, with links, because no single SPDX identifier is true of Who's On
First.

WOF's own LICENSE.md says that "the format and structure that allows Who's On
First to operate is made available under a Creative Commons Zero
designation" — the schema, not the records — and that the dataset "is both an
original work and a modification of existing open data. Some of those open
data projects do require attribution."

Measured on this distribution's own `geom_src` column, joined to
[whosonfirst-sources](https://github.com/whosonfirst/whosonfirst-sources):

| share | records | license of the geometry source |
|---|---|---|
| 70.88% | 3,844,289 | CC BY — GeoNames |
| 16.44% | 891,696 | CC-BY — Karmashapes, Mesoshapes |
| 7.27% | 394,250 | CC BY 2.0 — Quattroshapes, Open Data France |
| 2.58% | 139,913 | CC0 — Who's On First, Metazen, US Census |
| 0.97% | 52,730 | unmatched or empty `geom_src` |
| 0.0003% | 14 | CC BY-SA 3.0 — Wikipedia |

Attribution-requiring, not share-alike. No ODbL source contributes geometry at
all: `whosonfirst-sources` marks OpenStreetMap as `usage_geometry: 0`, used
only to mint concordance identifiers.

**What you have to do:** pass on the link, which is the one thing WOF
requires.

> Data from Who's On First.
> [License](https://whosonfirst.org/docs/licenses/).

Two additions this catalog recommends and WOF does not require by name: credit
GeoNames under CC BY 4.0, because it is 71% of the geometry, and credit
geocode.earth, because they build the distribution.

And one thing no blanket license can do: **check the record.** `geom_src` is
on every row of every boundary file. Join it to
`whosonfirst-sources/data/sources-spec-latest.json` and a specific place's
license is a fact rather than an average.

## How a browser gazetteer consumes this catalog

End to end, with no server.

1. **Fetch [`names/index.json`](names/index.json)** — a few kilobytes. It
   carries the index's exact size, row group count, checksum and footer size,
   every boundary file's URL and row count, the `catalog_version` all of them
   are pinned to, and the attribution to display.
2. **Range-request the index.** It is sorted by `name_norm`, a folded form of
   the name, so a typed prefix lives in a contiguous run of row groups that a
   client finds by binary search over the footer's statistics. Measured over
   all 200,087 two-character prefixes that occur: a prefix touches a median of
   one row group.
3. **Rank the hits.** `name_dupes` says how many places in the world share the
   folded name, `population` and `min_zoom` rank them, `parent_name`
   disambiguates them, and `bbox` moves the camera with no further fetch.
4. **Check `is_point` before drawing an outline.** 84% of localities and
   neighbourhoods are points, because most of them come from GeoNames, which
   is a point gazetteer.
5. **Resolve the geometry.** `geometry_ref` is a `{file, row_group, row}`
   pointer into the level's boundary file and its display companion — one
   range read. Verify the `wof_id` of the row you land on before trusting it;
   it is advisory by design.
6. **Use the display polygon as a spatial filter** for downloading some
   *other* dataset. It is buffered outward on purpose, so it contains the true
   boundary and a filter built from it over-fetches slightly rather than
   silently dropping features along the edge.

## Start here

- [Catalog agent guide](AGENTS.md) — the join keys and the traps.
- [What changed from the upstream distribution](changes-from-upstream.md).
- Per-collection guides: [`country`](country/AGENTS.md),
  [`region`](region/AGENTS.md), [`county`](county/AGENTS.md),
  [`localadmin`](localadmin/AGENTS.md), [`locality`](locality/AGENTS.md),
  [`neighbourhood`](neighbourhood/AGENTS.md), [`names`](names/AGENTS.md).

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

-- Every place called Kyoto, in any language this index carries.
SELECT name, name_lang, level, placetype, country, parent_name
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/names/wof_names.parquet'
WHERE name_norm = 'kyoto'
ORDER BY level, population DESC NULLS LAST;
```

## Two sibling catalogs

Three gazetteer catalogs are built to the same index contract, so one client
can be pointed at any of them. **Choose by license and by coverage.**

| catalog | license | reaches | names |
|---|---|---|---|
| this one | mixed, attribution, **no share-alike** | neighbourhood | 25 languages |
| [geoBoundaries CGAZ](https://source.coop/portolan-mirrors/geoboundaries-catalog) | CC-BY-4.0 | second-level | one |
| [Overture divisions](https://source.coop/portolan-mirrors/cn-gazetteer-overture) | ODbL, **share-alike** | locality | hundreds |

This one reaches further down than geoBoundaries and carries no share-alike
obligation, unlike Overture. Overture carries far more languages and a
conflated, actively maintained geometry set; Who's On First carries more
placetypes and publishes per-record geometry provenance, which is what makes
its licensing checkable rather than assumed.
