# Who's On First Gazetteer Name Index

**A name search sidecar, not a boundary dataset.** 5,405,294 places plus
4,073,485 alternative spellings of their names, 9,478,779 rows in all, sorted
by a folded form of the name so that a static client with no server can turn a
typed name into a Who's On First identifier, a bounding box and a point.

This is place-name lookup, not address geocoding. Who's On First's admin
distribution holds no street or house number.

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

## Files

```
names/wof_names.parquet  575.9 MiB, 9,478,779 rows, 741 row groups of 12,800
names/index.json  8,167 bytes, the manifest to fetch first
names/names.pmtiles  173.9 MiB, zoom 0-8, layer "names"
```

## How to read it

**Fetch [index.json](index.json) first.** It carries the index's exact size,
row group count and checksum, the footer size so the first read can be one
exactly-sized tail request, every boundary file's URL and row count, the
`catalog_version` (`whosonfirst-admin-parquet-2025-04-07`) all of them are
pinned to, and the attribution a client must display.

**Then range-request the index.** At 575.9 MiB this file is not meant to be
loaded whole. The manifest's `index.size` lets the footer read be one
exactly-sized tail request of 1,713,128 bytes rather than a speculative 512 KB.
After that, the sort does the work: a typed prefix lives in a contiguous run of
row groups that a client finds by binary search over the `name_norm`
statistics. `docs/index-measurements.md` in the
[repository](https://github.com/portolan-mirrors/whosonfirst-catalog) has the
per-prefix numbers.

A browser client reads it with
[hyparquet](https://github.com/hyparam/hyparquet) plus
[hyparquet-compressors](https://github.com/hyparam/hyparquet-compressors). The
compressors package is **required**: every column chunk is zstd.

## What is in it

| level | rows | places | alternative spellings |
|---|---|---|---|
| 0 | 6,359 | 353 | 6,006 |
| 1 | 68,821 | 4,362 | 64,459 |
| 2 | 241,266 | 42,115 | 199,151 |
| 3 | 439,276 | 164,756 | 274,520 |
| 4 | 8,093,496 | 4,796,292 | 3,297,204 |
| 5 | 629,561 | 397,416 | 232,145 |

`dropped_unnamed: 0` — the build drops a place whose name folds to nothing,
because it cannot be found by name, and **no place in this distribution does**.
Every one of the 5,405,294 has a name.

**7,221,629 of 9,478,779 rows have `is_point = true`**, meaning the place's
geometry in its boundary collection is a single point rather than a polygon.
Most of Who's On First's localities come from GeoNames, which is a point
gazetteer. Check this column before drawing an outline.

### The languages the alternative spellings come from

geocode.earth's GeoParquet build carries 25 fixed language columns. Who's On
First itself carries names in hundreds of languages — one San Francisco record
has 214 `name:*` properties — but those live in the SQLite and GeoJSON
distributions, so this index cannot be richer than 25 languages however
multilingual WOF is. Both distributions are assets of this collection.

| `name_lang` | rows |
|---|---|
| `rus` | 475,906 |
| `zho` | 366,124 |
| `ukr` | 292,766 |
| `fas` | 283,846 |
| `jpn` | 244,955 |
| `deu` | 181,152 |
| `kor` | 169,291 |
| `urd` | 166,478 |
| `heb` | 155,847 |
| `hin` | 121,491 |

A language value becomes a row only where its folded form differs from the
folded primary name and from every other language's folded form for the same
place. Where several agree, one row is kept and `name_lang_count` says how many
agreed.

## Schema

Every column, with its provenance tag and full description, is in
[collection.json](collection.json). The short version:

| column | type | what it is |
|---|---|---|
| `name` | string | The spelling to display |
| `name_norm` | string | **The column the file is sorted by.** The folding is fixed by the index contract: Unicode NFD, combining marks (category Mn) dropped, everything outside Unicode letters, digits, space, hyphen and apostrophe replaced by a space, whitespace collapsed, trimmed, lowercased |
| `level` | int8 | This catalog's 0-to-5 mapping of WOF's placetype, and the level a search filters on |
| `placetype` | string | WOF's own placetype, carried through so the placetypes sharing a level stay distinguishable: `country`, `dependency`, `disputed`, `macroregion`, `region`, `macrocounty`, `county`, `localadmin`, `locality`, `borough`, `macrohood`, `neighbourhood`, `microhood` |
| `country` | string | ISO 3166-1 alpha-3, derived as in the boundary collections |
| `country_iso2` | string | WOF's own two-letter code, byte for byte |
| `feature_id` | string | The `wof_id` of the place, which is the column of the same name in every boundary collection |
| `source` | string | Constant `whosonfirst-admin` on every row |
| `name_lang` | string | The ISO 639-3 language code this spelling came from, or null on a primary row where the language of `wof:name` is unstated |
| `name_lang_count` | int16 | How many of the 25 language columns fold to this exact spelling for this place |
| `alt_of` | string | Null on a primary row; on an alternative-spelling row it holds that row's own `feature_id`, which is the index contract's way of marking the row as another spelling of a place whose primary row is elsewhere in the file |
| `parent_name` | string | The `name` of the place's parent, resolved through `parent_id` against the boundary collections, so an autocomplete can show 'Springfield, Illinois' without a second fetch |
| `parent_id` | string | The parent's `wof_id` |
| `population` | int64 | The place's population where WOF has one, copied from its boundary row |
| `min_zoom` | float | WOF's `mz:min_zoom`, copied from the boundary row |
| `name_dupes` | int32 | How many distinct places in this index share this `name_norm`, anywhere in the world |
| `is_point` | boolean | Whether this place's geometry in its boundary collection is a single point rather than a polygon |
| `bbox` | struct | The place's bounding box in EPSG:4326 degrees, as four float32 values rounded **outward**, so the box is never narrower than the true extent |
| `geometry_ref` | struct | **Advisory** `{file, row_group, row}` pointer into the boundary collection at this row's `level`, and into its display companion where there is one |
| `geometry` | byte_array | WKB, one Point per row, from the place's `lon`/`lat` centroid, so this collection renders as a map of the gazetteer |

## Known issues

- **25 languages, not hundreds.** See above. This is a limit of the GeoParquet
  distribution, not of Who's On First.
- **The primary name is not always English, whatever WOF's documentation
  says.** `wof:name` is documented as "English by default", and it is not: the
  primary name of Kyoto Prefecture (`wof_id` 85672777) in this distribution is
  `كيوتو`. The Latin spellings of such a place live in its alternative-spelling
  rows, which is a large part of why they exist. Do not assume a primary row is
  searchable in Latin script.
- **The fold strips every Unicode mark, spacing marks included.** The index
  contract says to drop `\p{M}`, so a Devanagari or Bengali name folds to its
  consonant skeleton: `क्योटो प्रीफेक्चर` becomes `कयट परफकचर`. A client must
  apply exactly the same fold to the user's keystrokes — a JavaScript
  `/\p{M}/gu` strip does — or the binary search misses for those scripts. It
  also means the index cannot distinguish two Indic names that differ only in
  their vowel marks.
- **No currency or deprecation fields.** `mz:is_current`, `edtf:cessation`,
  `edtf:deprecated` and `wof:superseded_by` are not in the GeoParquet build, so
  a deprecated place may appear in this index with no sign that it is
  deprecated.
- **`geometry_ref` is advisory.** Verify the `wof_id` of the row you land on
  before trusting its geometry; see the column description.
- **The geometry column is a centroid, not a label point.** WOF publishes a
  hand-placed `lbl:latitude`/`lbl:longitude` pair that the GeoParquet build
  does not carry, so for a concave or multipart place the point can fall
  outside it.

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
سان أنطونيو  1,765
Сан-Антонио  1,765
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

## More

- [Agent guide](AGENTS.md) — the prefix-lookup recipe and the join back to
  geometry.
- [Index manifest](index.json) — fetch this before the index.
- [Catalog README](../README.md).

