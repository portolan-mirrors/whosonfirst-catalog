# AGENTS.md — Who's On First Countries, Dependencies and Disputed Areas

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

Level 0 of this catalog's administrative ladder: `country`, `disputed`,
`dependency`. 353 places. Public root:
`https://data.source.coop/portolan-mirrors/whosonfirst-catalog/catalog.json`

Who's On First is a gazetteer, so this is place-name and boundary lookup. It
holds no street or house number and cannot geocode an address.

## Accessing the data

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
```

Every file is readable in place over HTTPS range requests. No credentials, no
API, no server.

- `wof_country.parquet` — 61.5 MB, 353 rows, 89 row groups of 4 (708.1 KB
  each), sorted by `(country, wof_id)` with `sorting_columns` declared
  **[derived]**.
- `wof_country_display.parquet` — 5.1 MB, the same rows at the same offsets,
  simplified and buffered outward **[derived]**.
- `country.pmtiles` — 2.3 MB, layer `country`.
- [geocode.earth's combined
  GeoParquet](https://data.geocode.earth/wof/dist/parquet/whosonfirst-data-admin-latest.parquet)
  — 5.5 GB, all 21 placetypes, spatially clustered. Read this for a planet-wide
  scan or a spatial query; **do not** read it to fetch one place, because its
  geometry chunks are a median of 38 MiB and up to 285 MiB per row group
  **[derived]**.

## Schema & field notes

Every column is described in [collection.json](collection.json). The ones that
decide whether a query is right:

| column | what it is |
|---|---|
| `wof_id` | the Who's On First id, as a **string**. The key everything joins on |
| `parent_id` | the parent's `wof_id`, **or one of WOF's negative sentinels**: `-2`, `-3`, `-4` |
| `level` | this catalog's 0-to-5 mapping of `placetype`. WOF publishes no level |
| `placetype` | WOF's own placetype. A level can hold more than one |
| `country` | ISO 3166-1 alpha-3, derived. `country_iso2` is WOF's own two-letter code |
| `geom_src` | which source the outline came from, and therefore which license |
| `vertices` | coordinates in the geometry. `1` means the geometry is a point |
| `geometry_repaired` | true where this build rebuilt an invalid upstream polygon |

## Data quality & usage notes

**0 of 353 features (0.0%) are points, not polygons** **[derived]**. Check
`vertices = 1`, or `is_point` in the names collection, before drawing an
outline or computing an area.

```sql
SELECT count(*) FILTER (vertices = 1) AS points, count(*) AS total
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/country/wof_country.parquet';
```

**`parent_id` is not always an id.** WOF reserves `-2` "shrug, this feature is
complicated", `-3` "contested, but not disputed" and `-4` "multiple 'legal'
parents" **[attested, https://whosonfirst.org/docs/properties/wof/]**. A join
on `parent_id` has to exclude them.

**`country` is derived; `country_iso2` is WOF's.** Six of WOF's two-letter
codes are its own and have no alpha-3 — `XK`, `XN`, `XS`, `XX`, `XY`, `XZ`
**[attested, whosonfirst-placetypes]**. Those rows carry the two-letter code in
`country`.

**Nothing here says whether a place still exists.** `mz:is_current`,
`edtf:cessation`, `edtf:deprecated` and `wof:superseded_by` are not carried by
geocode.earth's GeoParquet build **[derived: the file has 57 columns and none
of them is any of those]**. Pelias's own active-record filter needs all four.
If currency matters, read the [SQLite
distribution](https://data.geocode.earth/wof/dist/sqlite/whosonfirst-data-admin-latest.db.bz2).

**Area is reproducible, not official.** `area_km2` is `ST_Area_Spheroid` on the
geometry in this file. For a place whose outline was carried up from a coarser
source, that is not its surveyed area.

## Example queries

Each of these was run against the published files before this guide was
written; the output under each one is what it returned.

Read it in place over HTTPS, with no credentials:

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

SELECT placetype, count(*) AS places
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/country/wof_country.parquet'
GROUP BY 1 ORDER BY 2 DESC;
```
```
country  213
disputed  100
dependency  40
```

The ten largest places here, by geodesic area:

```sql
SELECT name, country, placetype, round(area_km2) AS km2
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/country/wof_country.parquet'
ORDER BY area_km2 DESC LIMIT 10;
```
```
Solomon Islands  SLB  country  nan
Ashmore and Cartier Is.  AUS  dependency  nan
Coral Sea Islands  AUS  dependency  nan
Australia  AUS  country  nan
Japan  JPN  country  nan
Russia  RUS  country  nan
East Timor  TLS  country  nan
Tonga  TON  country  nan
Mexico  MEX  country  nan
Marshall Islands  MHL  country  nan
```

The country sort is what makes a country filter cheap: it prunes row groups
rather than scanning.

```sql
SELECT name, placetype, round(area_km2, 1) AS km2
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/country/wof_country.parquet'
WHERE country = 'NLD'
ORDER BY area_km2 DESC LIMIT 5;
```
```
Netherlands  country  66849.1
Caribbean Netherlands  dependency  126.3
```

Which sources the outlines came from, which is also which licenses apply:

```sql
SELECT geom_src, count(*) AS places
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/country/wof_country.parquet'
GROUP BY 1 ORDER BY 2 DESC LIMIT 5;
```
```
quattroshapes  176
whosonfirst  153
naturalearth  10
mz  5
us-dshiu  3
```

## Related collections

| collection | level | holds |
|---|---|---|
| [`country`](../country/collection.json) | 0 | `country`, `dependency`, `disputed` |
| [`region`](../region/collection.json) | 1 | `macroregion`, `region` |
| [`county`](../county/collection.json) | 2 | `macrocounty`, `county` |
| [`localadmin`](../localadmin/collection.json) | 3 | `localadmin` |
| [`locality`](../locality/collection.json) | 4 | `locality`, `borough` |
| [`neighbourhood`](../neighbourhood/collection.json) | 5 | `macrohood`, `neighbourhood`, `microhood` |
| [`names`](../names/collection.json) | all | the gazetteer name index, one row per place plus one per alternative spelling |

Join `names.feature_id` to `country.wof_id`, branching on `names.level` to pick
the collection. The names index also carries an advisory `geometry_ref` that
points straight at the row group and row in this file.

Two sibling catalogs are built to the same index contract: [geoBoundaries
CGAZ](https://source.coop/portolan-mirrors/geoboundaries-catalog) under
CC-BY-4.0, and [Overture
divisions](https://source.coop/portolan-mirrors/cn-gazetteer-overture) under
ODbL. This one reaches further down the hierarchy than geoBoundaries and
carries no share-alike obligation, unlike Overture.

