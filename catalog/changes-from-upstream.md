# What changed from geocode.earth's distribution

This catalog is not a byte-for-byte mirror, and it is not a replacement. It
**links** to geocode.earth's own files and **adds** a few of its own. This
document is the complete record of both: what was left out, what was changed,
what was added, and the measurement behind each decision.

Everything here is reproducible from the
[source repository](https://github.com/portolan-mirrors/whosonfirst-catalog).
`tools/distributions.sql` reruns every count.

## What this catalog links rather than copies

geocode.earth's combined administrative distribution, in five formats, is an
asset of every collection here, at its original URL, with the size and sha256
their inventory records:

| file | size | built |
|---|---|---|
| [`parquet/whosonfirst-data-admin-latest.parquet`](https://data.geocode.earth/wof/dist/parquet/whosonfirst-data-admin-latest.parquet) | 5,948,636,588 | 2025-04-07 |
| [`protomaps/whosonfirst-data-admin-latest.pmtiles`](https://data.geocode.earth/wof/dist/protomaps/whosonfirst-data-admin-latest.pmtiles) | 2,130,846,508 | 2025-10-14 |
| [`sqlite/whosonfirst-data-admin-latest.db.bz2`](https://data.geocode.earth/wof/dist/sqlite/whosonfirst-data-admin-latest.db.bz2) | 8,596,204,210 | 2025-10-14 |
| [`spatial/whosonfirst-data-admin-latest.spatial.db.bz2`](https://data.geocode.earth/wof/dist/spatial/whosonfirst-data-admin-latest.spatial.db.bz2) | 9,827,339,205 | 2025-10-14 |
| [`bundles/whosonfirst-data-admin-latest.tar.bz2`](https://data.geocode.earth/wof/dist/bundles/whosonfirst-data-admin-latest.tar.bz2) | 4,592,915,438 | 2025-10-14 |

Plus the inventory itself and the sidecar manifest naming the 260 member
repositories of the GeoParquet build.

**This catalog is built from the GeoParquet**, which is the oldest of the five.
Everything counted below is a count of that vintage.

## What is left out

### Eight placetypes

The upstream combined administrative file holds 21 placetypes and 5,423,663
rows. This catalog carries 13 of them and 5,405,294 rows — 99.66%. What is
left out, with its count and its reason:

| placetype | rows | why not |
|---|---|---|
| `campus` | 14,514 | a university, airport or military base, not an administrative unit |
| `postalregion` | 2,841 | a postal-service region; postcodes are a separate upstream distribution |
| `marinearea` | 402 | a body of water, not land administration |
| `timezone` | 376 | a timezone polygon, not an administrative unit |
| `marketarea` | 210 | a media market, not administration |
| `continent` | 8 | above the country rung, so it has no level on a 0-based ladder |
| `empire` | 11 | a historical polity, above the country rung and not current |
| `ocean` | 7 | a body of water, not land administration |

18,369 rows in all. Every one of them is in geocode.earth's file, which every
collection links.

### The 25 language columns, from the boundary files

The upstream file carries `name_ara` through `name_zho`, 25 fixed language
columns holding 11,280,783 non-empty values across the placetypes carried
here. The boundary files do not repeat them, because the `names` collection
carries every one of them as its own row — which is the view a search wants —
and repeating 11 million strings beside the geometry would add them to what a
map draw has to fetch. The primary `name` stays on every row.

### Nothing else

No place is dropped for any other reason. No row with a null name is dropped:
`dropped_unnamed` in the index manifest is **0**, because every place in this
distribution has a name.

## What is changed

### 480 invalid geometries are repaired, and flagged

480 of 5,405,294 features fail `ST_IsValid` in the upstream file:

| level | collection | invalid |
|---|---|---|
| 0 | `country` | 0 |
| 1 | `region` | 29 |
| 2 | `county` | 74 |
| 3 | `localadmin` | 44 |
| 4 | `locality` | 307 |
| 5 | `neighbourhood` | 26 |

An invalid polygon is not a cosmetic problem. `ST_Intersection` against one
raises `TopologyException: side location conflict` and takes the whole query
with it, which this build hit on its own containment check before the repair
existed.

So a row that fails `ST_IsValid` is rebuilt with `ST_MakeValid` and reduced
back to polygons with `ST_CollectionExtract(..., 3)`, and the row records that
with **`geometry_repaired = true`**. A row that passes is written through
unchanged, so 5,404,814 of 5,405,294 geometries are the upstream coordinates
exactly. To get the unrepaired shape, read geocode.earth's own file.

### Two geometries lose a Z coordinate

Exactly two features in the whole distribution carry 3D geometry, and both are
Swiss counties: Arbon (`wof_id` 102062959) and Neuchâtel (unincorporated)
(`wof_id` 1394237543). Their Z values are elevations in metres, which is why
the upstream file's GeoParquet metadata declares a six-element bbox with a
`zmin` of 394.915 and a `zmax` of 1551.4825 for the whole planet.

A Z coordinate means nothing for an administrative boundary, and mixing 2D and
3D in one column breaks readers: `gpq validate` rejects such a file outright
with "wkb: unsupported geometry", and it would make `county` the one
collection a consumer has to special-case. So every geometry goes through
`ST_Force2D`, which is a no-op for the other 5,405,292 features, and the two
affected rows say so with **`geometry_flattened = true`**. The Z values are in
geocode.earth's own file, which every collection links.

### Identifiers become strings, and empty strings become nulls

Upstream, `id` and `parent_id` are INT32 and ten further columns are
JSON-typed strings that hold an absent value as the **empty string** rather
than as null: `min_zoom`, `max_zoom`, `min_label`, `max_label`, `is_funky`,
`population`, `country_id`, `region_id`, `county_id`, `gn_id`.

Here, every identifier is a string — `wof_id`, `parent_id`,
`country_wof_id`, `region_wof_id`, `county_wof_id`, `geonames_id` — so this
catalog's files join to each other and to the index with no cast. The numeric
columns are parsed to their natural types, and an empty string becomes null.

`parent_id = -1`, which WOF documents as "unknown parent, record needs
review", becomes null. `-2`, `-3` and `-4` are carried through, because they
carry meaning a consumer should see; see the column descriptions.

### Columns are renamed

| upstream | here | why |
|---|---|---|
| `id` | `wof_id` | `id` is ambiguous beside `parent_id` and the ancestor columns |
| `placelocal` | `placetype_local` | it is WOF's `wof:placetype_local` |
| `country_id`, `region_id`, `county_id` | `country_wof_id`, `region_wof_id`, `county_wof_id` | they hold WOF ids, not ISO or census codes |
| `gn_id`, `wd_id` | `geonames_id`, `wikidata_id` | the abbreviations are not self-explanatory |
| `concord_ke`, `concord_id` | `concordance_keys`, `concordance_ids` | truncated upstream to fit a shapefile field-name limit |
| `geometry_bbox` | `bbox` | the GeoParquet `covering` name is read from the metadata either way |

Nothing else is renamed, and no value is edited.

## What is added

### Seven derived columns on every boundary file

| column | what it is |
|---|---|
| `level` | this catalog's 0-to-5 mapping of `placetype`. WOF publishes no level |
| `country` | ISO 3166-1 alpha-3, from WOF's two-letter code through pycountry's ISO table |
| `area_km2` | geodesic, `ST_Area_Spheroid` |
| `perimeter_km` | geodesic, `ST_Perimeter_Spheroid` |
| `vertices` | `ST_NPoints`. A value of 1 means the geometry is a point |
| `geometry_repaired` | whether this build rebuilt the geometry |
| `geometry_flattened` | whether this build dropped a Z coordinate |

Plus the `bbox` covering struct, declared in GeoParquet 1.1 `covering`
metadata so a reader can prune row groups spatially without decoding any
geometry.

### One GeoParquet per level, laid out for a single-place fetch

**The measurement that justifies it.** The upstream combined file has 83 row
groups of 65,536 rows, no declared sort order in any of them, and 89% of its
5.5 GiB in the `geometry` column. One row group's geometry chunk is:

| | compressed geometry chunk |
|---|---|
| minimum | 1.0 MiB |
| median | 38.4 MiB |
| 95th percentile | 196.3 MiB |
| maximum | 284.6 MiB |

Every Parquet reader is row-group-granular, so that is what decoding one row
costs. `placetype` statistics span most of the placetype alphabet in most row
groups, so filtering to one level prunes nothing either. The file *is*
spatially clustered — GDAL wrote it in bounding-box order and the
`geometry_bbox` covering lets a spatial predicate skip most row groups — but a
name lookup and a single-place fetch both fall back to a whole 65,536-row
group.

**What the files here do instead:** one per level, sorted by
`(country, wof_id)` with `sorting_columns` declared, in exactly-full row
groups sized per level from the measured bytes per row, zstd compressed, with
a Parquet page index and a `cnmw:catalog_version` footer pin.

| collection | rows | row groups | rows per group | per group |
|---|---|---|---|---|
| `country` | 353 | 89 | 4 | 708 KB |
| `region` | 4,362 | 273 | 16 | 795 KB |
| `county` | 42,115 | 659 | 64 | 785 KB |
| `localadmin` | 164,756 | 644 | 256 | 1.3 MB |
| `locality` | 4,796,292 | 2,342 | 2,048 | 642 KB |
| `neighbourhood` | 397,416 | 98 | 4,096 | 1.0 MB |

Every group is exactly full, so a row number alone says which group a row is
in — which is what makes the index's `geometry_ref` a single range read.

### A display-simplified companion for levels 0 to 3, and not for 4 and 5

**The measurement that justifies it**, and the measurement that stops it:

| level | features | median vertices | p95 | max | point geometries |
|---|---|---|---|---|---|
| 0 | 353 | 4,866 | 77,813 | 778,840 | 0 |
| 1 | 4,362 | 1,150 | 25,717 | 927,196 | 26 |
| 2 | 42,115 | 490 | 5,254 | 283,374 | 443 |
| 3 | 164,756 | 210 | 1,721 | 226,232 | 35,741 |
| 4 | 4,796,292 | **1** | 157 | 240,740 | 4,031,001 (84%) |
| 5 | 397,416 | **1** | 75 | 65,832 | 334,785 (84%) |

Levels 0 to 3 get a companion: a median country is 4,866 coordinates and the
95th percentile is 77,813, so drawing one from full resolution is slow enough
to feel. Levels 4 and 5 do not: their median feature is a **single point**,
84% of their features are points, and their 95th percentile is 157 and 75
coordinates. There is nothing there to simplify, and a second file would only
add a fetch.

The geometry is `ST_SimplifyPreserveTopology` followed by `ST_Buffer`
**outward** by the same tolerance, which is 0.4% of each feature's own
bounding-box diagonal capped per level. Simplification alone cuts corners
*inward*, and a shape used as a spatial filter that sits inside the true
boundary silently drops features near the edge; buffering outward makes the
result contain the original instead. Point geometries are carried through
untouched, because buffering a point would turn a marker into a circle.

Measured containment, per feature, against the full-resolution polygon:

| collection | size | share of the full file | polygons fully contained | below 99% | worst |
|---|---|---|---|---|---|
| `country` | 5.1 MB | 8.3% | 295 of 353 | 0 | 0.9971 |
| `region` | 21.8 MB | 10.3% | 4,126 of 4,336 | 1 | 0.9890 |
| `county` | 107.2 MB | 21.2% | 40,813 of 41,672 | 0 | 0.9985 |
| `localadmin` | 219.9 MB | 26.2% | 126,759 of 129,015 | 0 | 0.9978 |

The one feature below 99% is **Chuuk**, a region of the Federated States of
Micronesia made of scattered small islands, where the simplification drops
islands the buffer cannot recover. It is recorded rather than chased.

### Vector tiles, capped

**The measurement that justifies it.** geocode.earth publishes a combined
PMTiles archive, 2.0 GiB over zoom 0 to 9 with one layer per placetype, built
with `tippecanoe -zg --no-tile-size-limit`. Measured tile sizes:

| zoom | tile | bytes |
|---|---|---|
| 0 | 0/0 | 15,671,392 |
| 1 | 0/0 | 12,705,958 |
| 2 | 2/1 | 24,260,389 |
| 3 | 4/2 | 25,954,206 |
| 4 | 8/5 | 24,769,395 |
| 5 | 16/10 | 9,255,247 |
| 8 | 133/86 | 460,379 |
| 9 | 267/172 | 153,862 |

A whole-world first view that costs 15.7 MB is not something a browser tab
opens, and the archive also reports dropping 4,412,845 features by rate at
zoom 0 to fit what it does carry — so the low zooms are heavy *and*
incomplete.

The archives here are one per level, capped at 400 KB per tile. They also
carry one derived attribute, `geom_src_group`, which folds the long tail of
`geom_src` — 66 distinct values at one level — into eight classes so that the
provenance style has a legend a reader can read. The raw `geom_src` travels
into the tiles too, and into the GeoParquet untouched.

geocode.earth's archive is still linked from every collection, because it is
the one that carries all 21 placetypes in a single file.

### The gazetteer name index

No upstream equivalent exists in any format. One row per place plus one row
per distinct alternative spelling of its name, sorted by a folded form of the
name so a static client can resolve a typed prefix with range requests.

The alternative spellings come from the 25 language columns. A language value
becomes a row only where its folded form is new:

| | rows |
|---|---|
| language values in the upstream file | 11,280,783 |
| folded to the same string as the primary name | 4,945,656 |
| agreed with another language's folded form | 2,261,642 |
| **kept as an alternative-spelling row** | **4,073,485** |
| primary rows | 5,405,294 |
| **index rows** | **9,478,779** |

Where several languages agree on a spelling, one row is kept carrying the
first language code alphabetically, and `name_lang_count` says how many
agreed.

## What is *not* here, and where to get it

geocode.earth's GeoParquet build is a flattened projection of Who's On First,
and this catalog cannot add back what the projection dropped.

| missing | where it is |
|---|---|
| The full `wof:hierarchy` | the SQLite, SpatiaLite and GeoJSON distributions |
| The full `wof:concordances` — this distribution keeps **one** key/id pair per record | the same |
| `mz:is_current`, `edtf:cessation`, `edtf:deprecated`, `edtf:superseded`, `wof:supersedes`, `wof:superseded_by` | the same. **Nothing in this catalog says whether a place still exists.** |
| Names in languages other than the 25 carried | the same. One San Francisco record has 214 `name:*` properties |
| `wof:population_rank`, the 0-to-14 band scale | the same |
| `lbl:latitude` / `lbl:longitude`, WOF's hand-placed label point | the same. `lat`/`lon` here are the geometric centroid, which for a concave place can fall outside it |
| Postcodes, constituencies | separate combined files under `https://data.geocode.earth/wof/dist/` |
| Venues, addresses, buildings, intersections | not distributed by geocode.earth at all |

All five upstream distributions are assets of every collection, so none of
this requires leaving the catalog to find.
