# Who's On First Local Administrative Units

Level 3 of the Who's On First administrative ladder, as a cloud-native
gazetteer collection: 164,756 places across 81 country codes.

Placetypes here: `localadmin` (164,756).

Who's On First calls itself a gazetteer, and that is what this is: place-name
and boundary lookup. There is no street or house number anywhere in WOF's admin
distribution, so this is not address geocoding.

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

## Which file to read

| you want | read | why |
|---|---|---|
| To draw an outline, now | `wof_localadmin_display.parquet` | Simplified, 219.9 MiB against 841.2 MiB |
| To draw many at once | `localadmin.pmtiles` | Tiled, capped at 400 KB per tile |
| To clip, measure, export or analyse one place | `wof_localadmin.parquet` | The real geometry, 1.3 MiB per range request |
| To scan the whole planet, or all 21 placetypes at once | [geocode.earth's combined GeoParquet](https://data.geocode.earth/wof/dist/parquet/whosonfirst-data-admin-latest.parquet) | One file, spatially clustered, 5.5 GiB |
| The full hierarchy, every language, or the temporal fields | [geocode.earth's SQLite distribution](https://data.geocode.earth/wof/dist/sqlite/whosonfirst-data-admin-latest.db.bz2) | The GeoParquet build does not carry them |

### Why this catalog has its own GeoParquet at all

geocode.earth's combined file is cloud-native already: GeoParquet 1.1 with a
`covering` bbox, served with HTTP range requests and
`Access-Control-Allow-Origin: *`. For a scan or a spatial query it is the right
file, and this collection links straight to it.

It is the wrong file for fetching **one** place. Measured
(`docs/upstream-measurements.md` in the
[repository](https://github.com/portolan-mirrors/whosonfirst-catalog)): 83 row
groups of 65,536 rows, no declared sort, 89% of the bytes in the `geometry`
column, so one row group's geometry chunk is a median of 38 MiB and as much as
285 MiB. Every Parquet reader is row-group-granular, so that is the cost of
decoding a single row. `placetype` statistics span most of the alphabet in most
row groups, so filtering to this level prunes nothing either.

This file is the same 164,756 places sorted by `(country, wof_id)` with the
sort declared, in 644 exactly-full row groups of 256 — 1.3 MiB each.

## Files

```
localadmin/wof_localadmin.parquet  841.2 MiB, 164,756 rows, 644 row groups of 256
localadmin/wof_localadmin_display.parquet  219.9 MiB (26.1% of the full file)
localadmin/localadmin.pmtiles  116.1 MiB, layer "localadmin"
```

### The display file is outward-biased, and that matters

Its geometry is `ST_SimplifyPreserveTopology` followed by `ST_Buffer`
**outward** by the same tolerance, which is 0.4% of each feature's own
bounding-box diagonal capped at 0.002 degrees. Simplification alone cuts
corners *inward*, and a shape used as a spatial filter that sits inside the
true boundary silently drops features near the edge. Buffering outward makes
the result contain the original instead.

So neighbouring places overlap in the margin, a point near a border can fall
inside two display polygons, and you should not measure area from them or
decide which side of a border a point is on with them. **Row *i* is the same
place in both files**, and so is row group *g*: the display file is written
with the same row count, row order and row group boundaries as the
full-resolution file, so one byte-range plan serves either.

Point geometries are carried through untouched. Buffering a point would turn a
marker into a circle and change the row's geometry type.

## Schema

Every column, with its provenance tag and full description, is in
[collection.json](collection.json). The short version:

| column | type | what it is |
|---|---|---|
| `wof_id` | string | The Who's On First identifier, and the key everything in this catalog joins on |
| `parent_id` | string | The `wof_id` of the direct parent record, as a string |
| `name` | string | The display name |
| `placetype` | string | The WOF placetype, which is what WOF has instead of an administrative level |
| `level` | int8 | This catalog's mapping of `placetype` onto the 0-based administrative ladder a name search needs: 0 country, dependency and disputed; 1 macroregion and region; 2 macrocounty and county; 3 localadmin; 4 locality and borough; 5 macrohood, neighbourhood and microhood |
| `country` | string | ISO 3166-1 alpha-3, mapped from WOF's own two-letter code through the official ISO 3166-1 table packaged with pycountry, so this catalog and its two sibling gazetteer catalogs can be filtered with one code system |
| `country_iso2` | string | WOF's own code, byte for byte |
| `placetype_local` | string | "What locals consider the placetype to be (string value)" ([wof properties](https://whosonfirst.org/docs/properties/wof/), `wof:placetype_local`) |
| `repo` | string | The `whosonfirst-data-admin-{cc}` GitHub repository this record comes from |
| `lat` | double | "The latitude of a feature's geometric centroid" ([geom properties](https://whosonfirst.org/docs/properties/geom/), `geom:latitude`) |
| `lon` | double | "The longitude of a feature's geometric centroid" ([geom properties](https://whosonfirst.org/docs/properties/geom/), `geom:longitude`) |
| `min_zoom` | float | WOF's own answer to how early a place should appear on a map |
| `max_zoom` | float | The upper end of the same pair |
| `min_label` | float | The zoom at which a label for this place should first be drawn |
| `max_label` | float | The upper end of the same undocumented pair |
| `population` | int64 | "An integer value to represent the most current, known population of a place" ([wof properties](https://whosonfirst.org/docs/properties/wof/), `wof:population`) |
| `is_funky` | int8 | WOF's own "needs a human" flag |
| `modified` | date | When the WOF record last changed |
| `country_wof_id` | string | The `wof_id` of the country this record sits in, flattened out of WOF's `wof:hierarchy` ([wof properties](https://whosonfirst.org/docs/properties/wof/): "A list of hashes, where each object is the list of ancestors") by geocode.earth's parquet build |
| `region_wof_id` | string | The `wof_id` of the containing region, from the same flattened hierarchy |
| `county_wof_id` | string | The `wof_id` of the containing county, from the same flattened hierarchy |
| `iso_code` | string | An ISO 3166-2 subdivision code, such as `AL-01` |
| `hasc_id` | string | A Hierarchical Administrative Subdivision Code, such as `AR.CT` |
| `geonames_id` | string | The [GeoNames](https://www.geonames.org/) identifier for the same place, from WOF's `gn:id` concordance |
| `wikidata_id` | string | The [Wikidata](https://www.wikidata.org/) Q-identifier, from WOF's `wd:id` concordance |
| `concordance_keys` | string | **One** concordance key, not the set |
| `concordance_ids` | string | The identifier belonging to `concordance_keys` |
| `geom_src` | string | **The provenance and licensing key, and the most important column here.** WOF documents `src:geom` as "The data source of a record's geometry |
| `area_km2` | double | Geodesic area in square kilometres, from pyproj's `Geod`, which is GeographicLib |
| `perimeter_km` | double | Geodesic perimeter in kilometres, from the same pyproj `Geod` call |
| `vertices` | int32 | Coordinates in the geometry, from `ST_NPoints` |
| `geometry_repaired` | boolean | True where the upstream geometry failed `ST_IsValid` and this build rebuilt it with `ST_MakeValid` and `ST_CollectionExtract(..., 3)` |
| `geometry_flattened` | boolean | True where the upstream geometry carried a Z coordinate and this build dropped it with `ST_Force2D` |
| `bbox` | struct | The feature's bounding box in EPSG:4326 degrees, as four doubles declared in the GeoParquet 1.1 `covering` metadata, so a reader can prune row groups spatially without decoding any geometry |
| `geometry` | byte_array | WKB, EPSG:4326 (OGC:CRS84), exactly the coordinates WOF publishes except for the 480 rows `geometry_repaired` flags and the 2 rows `geometry_flattened` flags |

## What this collection measures

| | |
|---|---|
| Places | 164,756 |
| Country codes | 81 |
| Point geometries | 35,741 (21.7%) |
| Coordinates per outline | median 210, 95th percentile 1,718, max 226,232 |
| Features carrying a population | 116,072 (70.5%) |
| Geometries repaired by this build | 44 |

Where the outlines came from, by WOF's own `geom_src`:

| `geom_src` | places |
|---|---|
| `quattroshapes` | 37,812 |
| `frgov` | 35,282 |
| `qs_pg` | 27,628 |
| `uscensus` | 23,494 |
| `esp-cnig` | 8,211 |
| `(none)` | 7,300 |
| `ee-mamt` | 4,713 |
| `de-bkg` | 4,646 |

That column is the licensing key as well as the provenance one. Join it to
[sources-spec-latest.json](https://github.com/whosonfirst/whosonfirst-sources)
and a specific place's license is a fact rather than an average.

## Known issues

- **The GeoParquet vintage is 2025-04-07, six months behind the other
  formats.** geocode.earth's SQLite, SpatiaLite, GeoJSON-bundle and PMTiles
  builds of the same repository are from 2025-10-14 and come from a different
  WOF tree. A count from this catalog and a count from the SQLite distribution
  are two vintages, not a discrepancy.
- **44 geometries were invalid upstream and rebuilt here** with `ST_MakeValid`.
  The `geometry_repaired` column flags them. `ST_Intersection` against an
  invalid polygon raises `TopologyException` and takes the whole query with it,
  which is why this is a repair and not a note.
- **`parent_id` carries WOF's negative sentinels.** `-2`, `-3` and `-4` are not
  identifiers; see the column description. `-1` is mapped to null by this
  build.
- **The full `wof:hierarchy` and `wof:concordances` are not in the
  GeoParquet.** The upstream build flattens them to three ancestor-id columns
  and a single concordance key/id pair. Read the SQLite or GeoJSON distribution
  for the complete structures.
- **The temporal and deprecation fields are absent.** `mz:is_current`,
  `edtf:cessation`, `edtf:deprecated` and `wof:superseded_by` are not carried
  by the GeoParquet build, so this collection cannot tell you whether a place
  is still a going concern. Pelias's own active-record filter needs all four
  and reads them from the SQLite distribution.

## Example queries

Every one of these was run against the published files before this file was
written.

Read it in place over HTTPS, with no credentials:

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

SELECT placetype, count(*) AS places
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/localadmin/wof_localadmin.parquet'
GROUP BY 1 ORDER BY 2 DESC;
```
```
localadmin  164756
```

The ten largest places here, by geodesic area:

```sql
SELECT name, country, placetype, round(area_km2) AS km2
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/localadmin/wof_localadmin.parquet'
ORDER BY area_km2 DESC LIMIT 10;
```
```
Gibson Desert South  AUS  localadmin  328,733
Marree  AUS  localadmin  258,128
Glendambo  AUS  localadmin  198,535
Wiluna  AUS  localadmin  181,295
Telfer  AUS  localadmin  178,059
Tanami  AUS  localadmin  141,978
Mount Burges  AUS  localadmin  125,257
Menzies  AUS  localadmin  124,572
Tanami East  AUS  localadmin  115,005
Gibson Desert North  AUS  localadmin  114,005
```

The country sort is what makes a country filter cheap: it prunes row groups
rather than scanning.

```sql
SELECT name, placetype, round(area_km2, 1) AS km2
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/localadmin/wof_localadmin.parquet'
WHERE country = 'NLD'
ORDER BY area_km2 DESC LIMIT 5;
```
```
Sudwest-Fryslan  localadmin  505.5
Noordoostpolder  localadmin  468.0
De Fryske Marren  localadmin  417.8
Hollands Kroon  localadmin  374.0
Emmen  localadmin  346.3
```

Which sources the outlines came from, which is also which licenses apply:

```sql
SELECT geom_src, count(*) AS places
FROM 'https://data.source.coop/portolan-mirrors/whosonfirst-catalog/localadmin/wof_localadmin.parquet'
GROUP BY 1 ORDER BY 2 DESC LIMIT 5;
```
```
quattroshapes  37812
frgov  35282
qs_pg  27628
uscensus  23494
esp-cnig  8211
```

## More

- [Agent guide](AGENTS.md) — the join keys and the traps.
- [geocode.earth's download
  page](https://geocode.earth/data/whosonfirst/combined/) — the upstream
  distribution, and the per-country and per-placetype alternatives.
- [Who's On First placetypes](https://whosonfirst.org/docs/placetypes/) — the
  project's own definitions.
- [Catalog README](../README.md) and [catalog agent guide](../AGENTS.md).

