#!/usr/bin/env python3
"""The published column descriptions, with a provenance tag on every one.

One canonical home, read by `make_collections.py` for `table:columns` and by
`make_docs.py` for the schema tables in the READMEs and agent guides. A
description written twice is a description that will disagree with itself.

Each entry carries a tag saying how its meaning was established:

* **attested** -- Who's On First or geocode.earth states it, and the `cite`
  field is where. Quoted wording is in double quotes.
* **researched** -- found outside the source's own metadata, with the URL in
  `cite`.
* **derived** -- computed by this catalog's build, which the description says
  how to reproduce.

A column with no tag does not get published. Where research failed, the
description says so rather than guessing; `wof:name`'s own documentation calls
it "UTF-7 transliterated", which is plainly a typo for UTF-8, and this file
records that rather than quietly correcting the quote.
"""
from __future__ import annotations

WOF_PROPS = "https://whosonfirst.org/docs/properties"
WOF_PLACETYPES = "https://github.com/whosonfirst/whosonfirst-placetypes"
WOF_SOURCES = "https://github.com/whosonfirst/whosonfirst-sources"
WOF_NAMES = "https://whosonfirst.org/docs/names/"
WOF_CONCORDANCES = "https://whosonfirst.org/docs/concordances/"

# (name, type, tag, description)
BOUNDARY_COLUMNS: list[tuple[str, str, str, str]] = [
    (
        "wof_id", "string", "attested",
        "The Who's On First identifier, and the key everything in this "
        "catalog joins on. WOF documents `wof:id` as \"The record's unique "
        "numeric integer identifier that are typically derived from Brooklyn "
        f"Integers\" ([wof properties]({WOF_PROPS}/wof/)). It is published "
        "here as a decimal string rather than an integer so that this file, "
        "the gazetteer index and `parent_id` all join without a cast; "
        "upstream it is an INT32.",
    ),
    (
        "parent_id", "string", "attested",
        "The `wof_id` of the direct parent record, as a string. WOF reserves "
        "four negative values, and **they are not ids**: `-1` \"unknown "
        "parent, record needs review\", `-2` \"shrug, this feature is "
        "complicated\", `-3` \"contested, but not disputed.. used for "
        "placetypes below the locality level\", `-4` \"multiple 'legal' "
        f"parents.. used for placetypes at the locality level or above\" "
        f"([wof properties]({WOF_PROPS}/wof/)). This build maps `-1` to null; "
        "the other three are carried through, so a join on `parent_id` has to "
        "exclude them.",
    ),
    (
        "name", "string", "attested",
        "The display name. WOF documents `wof:name` as \"An English UTF-7 "
        "transliterated representation of the name\" — the encoding name is a "
        "typo in WOF's own documentation for UTF-8, and the values are UTF-8. "
        "Its names documentation is the useful statement: \"`wof:name` is "
        "English by default and is a string (rather than a list of strings) "
        f"that can be used for labels\" ([wof names]({WOF_NAMES})). Every "
        "other language lives in the `names` collection, one row per "
        "spelling.",
    ),
    (
        "placetype", "string", "attested",
        "The WOF placetype, which is what WOF has instead of an "
        "administrative level. The canonical list, each one's role and its "
        f"permitted parents are in [whosonfirst-placetypes]({WOF_PLACETYPES}); "
        "the project's own website page for them is out of date. WOF's "
        "definitions are blunt and worth reading: a `region` holds \"places "
        "that would have a bone in a 'states rights' argument\", a `locality` "
        "is \"Towns and cities, independent of size or population. Things "
        "with neighbourhoods, basically\", a `borough` is \"A local "
        "government unit, below the `locality` placetype. Think Brooklyn\".",
    ),
    (
        "level", "int8", "derived",
        "This catalog's mapping of `placetype` onto the 0-based "
        "administrative ladder a name search needs: 0 country, dependency and "
        "disputed; 1 macroregion and region; 2 macrocounty and county; 3 "
        "localadmin; 4 locality and borough; 5 macrohood, neighbourhood and "
        "microhood. **Who's On First publishes no such number.** A level here "
        "is a tier, and a tier can hold a unit and its own subdivision, "
        "because WOF inserts `macroregion` above `region` and `microhood` "
        "below `neighbourhood` without adding a rung anyone else recognizes. "
        "The mapping is defined once, in `PLACETYPE_LEVEL` in "
        "`tools/wofcommon.py`.",
    ),
    (
        "country", "string", "derived",
        "ISO 3166-1 alpha-3, mapped from WOF's own two-letter code through "
        "the official ISO 3166-1 table packaged with pycountry, so this "
        "catalog and its two sibling gazetteer catalogs can be filtered with "
        "one code system. WOF's six synthetic codes have no alpha-3 and are "
        "carried through unchanged: see `country_iso2`.",
    ),
    (
        "country_iso2", "string", "attested",
        "WOF's own code, byte for byte. Documented as \"A two-letter country "
        f"code from ISO 3166\" ([wof properties]({WOF_PROPS}/wof/)), with six "
        "codes WOF mints itself and ISO does not have "
        f"([whosonfirst-placetypes]({WOF_PLACETYPES})): `XK` Kosovo (\"We "
        "just followed Geonames' lead\"), `XN` Null Island, `XS` Somaliland, "
        "`XX` \"a place disputed by two or more (ISO) countries\", `XY` \"an "
        "ISO country that has yet to be determined (by us)\", `XZ` \"the ISO "
        "country code equivalent of `wof:parent_id=-2`\".",
    ),
    (
        "placetype_local", "string", "attested",
        "\"What locals consider the placetype to be (string value)\" "
        f"([wof properties]({WOF_PROPS}/wof/), `wof:placetype_local`). Free "
        "text and in the local language or English depending on the record: "
        "`district`, `voivodeship`, `département`. Useful for a label, not "
        "for a filter.",
    ),
    (
        "repo", "string", "attested",
        "The `whosonfirst-data-admin-{cc}` GitHub repository this record "
        "comes from. geocode.earth's combined distribution is the union of "
        "260 of them, and this column is what says which. The members of the "
        "build are listed in its sidecar manifest, "
        "`whosonfirst-data-admin-latest.parquet.json`.",
    ),
    (
        "lat", "double", "attested",
        "\"The latitude of a feature's geometric centroid\" "
        f"([geom properties]({WOF_PROPS}/geom/), `geom:latitude`). It is a "
        "centroid, so for a concave or multipart feature it can fall outside "
        "the feature. WOF publishes a separate hand-placed label point under "
        "`lbl:latitude`, which geocode.earth's parquet build does not carry.",
    ),
    (
        "lon", "double", "attested",
        "\"The longitude of a feature's geometric centroid\" "
        f"([geom properties]({WOF_PROPS}/geom/), `geom:longitude`). See "
        "`lat`.",
    ),
    (
        "min_zoom", "float", "attested",
        "WOF's own answer to how early a place should appear on a map. "
        "`mz:min_zoom` and `mz:max_zoom` are \"Float values (though in "
        "practice mosts are integer values) that match to web map zoom "
        "schema. Common range is 0.0 to 18.0, though they can be greater\" "
        f"([mz properties]({WOF_PROPS}/mz/)). For a gazetteer this is a "
        "better prominence signal than area, and no other catalog in this "
        "family has it.",
    ),
    (
        "max_zoom", "float", "attested",
        "The upper end of the same pair. See `min_zoom`.",
    ),
    (
        "min_label", "float", "researched",
        "The zoom at which a label for this place should first be drawn. "
        "**WOF publishes no definition for `mz:min_label` or "
        f"`mz:max_label`** — neither appears on the [mz properties page]"
        f"({WOF_PROPS}/mz/), which documents `min_zoom` and `max_zoom` only. "
        "Pelias reads the pair for label placement, and the values here sit "
        "slightly above the matching `min_zoom`, which is consistent with "
        "\"draw the shape at min_zoom, the label at min_label\". Treat the "
        "meaning as inferred rather than stated.",
    ),
    (
        "max_label", "float", "researched",
        "The upper end of the same undocumented pair. See `min_label`.",
    ),
    (
        "population", "int64", "attested",
        "\"An integer value to represent the most current, known population "
        f"of a place\" ([wof properties]({WOF_PROPS}/wof/), "
        "`wof:population`). Present only where a source supplied one, which "
        "is a minority of records at every level; the per-level coverage is "
        "in this collection's README. WOF also publishes `wof:population_rank` "
        "on a 0-to-14 band scale, which geocode.earth's parquet build does "
        "not carry.",
    ),
    (
        "is_funky", "int8", "attested",
        "WOF's own \"needs a human\" flag. `mz:is_funky`: \"-1 is unknown, or "
        "TBD (needs the love and care of a human) / 0 is false / 1 is true\" "
        f"([mz properties]({WOF_PROPS}/mz/)). Almost always absent, so a null "
        "means \"not flagged\", not \"fine\".",
    ),
    (
        "modified", "date", "attested",
        "When the WOF record last changed. WOF stores `wof:lastmodified` as "
        f"\"A Unix epoch timestamp integer\" ([wof properties]"
        f"({WOF_PROPS}/wof/)); geocode.earth's build converts it to a date. "
        "It is the record's date, not this distribution's: the GeoParquet "
        "build itself is from 2025-04-07.",
    ),
    (
        "country_wof_id", "string", "researched",
        "The `wof_id` of the country this record sits in, flattened out of "
        f"WOF's `wof:hierarchy` ([wof properties]({WOF_PROPS}/wof/): \"A list "
        "of hashes, where each object is the list of ancestors\") by "
        "geocode.earth's parquet build. The full hierarchy, including records "
        "with several parents, is **not** in the GeoParquet; it is in the "
        "SQLite and GeoJSON distributions.",
    ),
    (
        "region_wof_id", "string", "researched",
        "The `wof_id` of the containing region, from the same flattened "
        "hierarchy. See `country_wof_id`.",
    ),
    (
        "county_wof_id", "string", "researched",
        "The `wof_id` of the containing county, from the same flattened "
        "hierarchy. See `country_wof_id`.",
    ),
    (
        "iso_code", "string", "derived",
        "An ISO 3166-2 subdivision code, such as `AL-01`. Measured: present "
        "on 4,082 of 4,362 level-1 features and almost nowhere else. It "
        "arrives from WOF's `iso:code` concordance, so it is the same value a "
        "`concordance_keys = 'iso:code'` row carries.",
    ),
    (
        "hasc_id", "string", "researched",
        "A Hierarchical Administrative Subdivision Code, such as `AR.CT`. One "
        "of the identifier systems WOF keeps concordances against "
        f"([concordances]({WOF_CONCORDANCES})). Mostly populated at level 1.",
    ),
    (
        "geonames_id", "string", "researched",
        "The [GeoNames](https://www.geonames.org/) identifier for the same "
        "place, from WOF's `gn:id` concordance. This is the most useful "
        "column in the file for cross-referencing, because GeoNames is also "
        "where most of the geometry came from: 3,843,415 of this "
        "distribution's records carry `geom_src = 'geonames'`.",
    ),
    (
        "wikidata_id", "string", "researched",
        "The [Wikidata](https://www.wikidata.org/) Q-identifier, from WOF's "
        "`wd:id` concordance.",
    ),
    (
        "concordance_keys", "string", "derived",
        "**One** concordance key, not the set. WOF's `wof:concordances` is \"A "
        f"hash containing identifiers from other data sources\" ([wof "
        f"properties]({WOF_PROPS}/wof/)) and a record often holds several; "
        "geocode.earth's parquet build flattens it to a single key/id pair "
        "beside the separate `gn_id`, `wd_id` and `hasc_id` columns. Measured "
        "at level 1: 30 distinct keys over 4,282 populated rows, led by "
        "`iso:code` (2,830), `qs:local_id` (491) and `os:census_code` (178). "
        "If you need the whole concordance set, read the SQLite or GeoJSON "
        "distribution instead.",
    ),
    (
        "concordance_ids", "string", "derived",
        "The identifier belonging to `concordance_keys`. See that column for "
        "why there is only one.",
    ),
    (
        "geom_src", "string", "attested",
        "**The provenance and licensing key, and the most important column "
        "here.** WOF documents `src:geom` as \"The data source of a record's "
        "geometry. Valid property values are listed in the "
        f"whosonfirst-sources repository\" ([src properties]({WOF_PROPS}/src/)). "
        f"Join it to [sources-spec-latest.json]({WOF_SOURCES}) and a specific "
        "feature's license is a fact rather than an average. Measured over "
        "the whole distribution: `geonames` 3,843,415, `karmashapes` 866,821, "
        "`quattroshapes` 180,884, `qs_pg` 144,246, `frgov` 69,118, `mz` "
        "51,832, `whosonfirst` 45,222, `uscensus` 36,472.",
    ),
    (
        "area_km2", "double", "derived",
        "Geodesic area in square kilometres, from DuckDB's "
        "`ST_Area_Spheroid`. Reproducible, not official: it is measured on "
        "the geometry in this file, which for a feature whose outline was "
        "carried up from a coarser source is not that place's surveyed area. "
        "A point feature is 0.",
    ),
    (
        "perimeter_km", "double", "derived",
        "Geodesic perimeter in kilometres, from `ST_Perimeter_Spheroid`. "
        "Paired with `area_km2` it gives a compactness measure without "
        "reprojecting anything.",
    ),
    (
        "vertices", "int32", "derived",
        "Coordinates in the geometry, from `ST_NPoints`. This is the number "
        "behind this catalog's display files: a median country is 4,866 "
        "coordinates and a median locality is 1. A value of 1 means the "
        "geometry is a point, not a polygon.",
    ),
    (
        "geometry_repaired", "boolean", "derived",
        "True where the upstream geometry failed `ST_IsValid` and this build "
        "rebuilt it with `ST_MakeValid` and `ST_CollectionExtract(..., 3)`. "
        "480 of 5,405,294 features across the catalog: 29 regions, 74 "
        "counties, 44 local administrative units, 307 localities, 26 "
        "neighbourhoods. Every other geometry is written through unchanged. "
        "The repair exists because `ST_Intersection` against an invalid "
        "polygon raises `TopologyException` and takes the whole query with "
        "it; geocode.earth's own file is where to read the unrepaired shape.",
    ),
    (
        "geometry_flattened", "boolean", "derived",
        "True where the upstream geometry carried a Z coordinate and this "
        "build dropped it with `ST_Force2D`. Exactly two features in the "
        "whole distribution do: the Swiss counties Arbon (`wof_id` "
        "102062959) and Neuch\u00e2tel (unincorporated) (`wof_id` "
        "1394237543), whose Z values are elevations in metres. That is why "
        "the upstream file's GeoParquet metadata declares a six-element bbox "
        "with a `zmin` of 394.915 for the whole planet. A Z coordinate means "
        "nothing for an administrative boundary and mixing 2D and 3D in one "
        "column breaks readers — `gpq validate` rejects such a file with "
        "\"wkb: unsupported geometry\" — so every geometry here is 2D.",
    ),
    (
        "bbox", "struct", "derived",
        "The feature's bounding box in EPSG:4326 degrees, as four doubles "
        "declared in the GeoParquet 1.1 `covering` metadata, so a reader can "
        "prune row groups spatially without decoding any geometry.",
    ),
    (
        "geometry", "byte_array", "attested",
        "WKB, EPSG:4326 (OGC:CRS84), exactly the coordinates WOF publishes "
        "except for the 480 rows `geometry_repaired` flags and the 2 rows "
        "`geometry_flattened` flags. A point where `vertices = 1`, otherwise "
        "a Polygon or MultiPolygon, always 2D.",
    ),
]

# (name, type, tag, description)
INDEX_COLUMNS: list[tuple[str, str, str, str]] = [
    (
        "name", "string", "attested",
        "The spelling to display. On a primary row it is WOF's `wof:name`; on "
        "an alternative row it is the value one of the 25 language columns "
        "holds. Display this; search `name_norm`.",
    ),
    (
        "name_norm", "string", "derived",
        "**The column the file is sorted by.** The folding is fixed by the "
        "index contract: Unicode NFD, combining marks (category Mn) dropped, "
        "everything outside Unicode letters, digits, space, hyphen and "
        "apostrophe replaced by a space, whitespace collapsed, trimmed, "
        "lowercased. So `zurich` finds `Zürich` and `koln` finds `Köln`. A "
        "script with no Latin decomposition, such as Han or Arabic, is "
        "lowercased and otherwise unchanged, so it is findable in its own "
        "script. The sort is byte-wise on the UTF-8 encoding and not a locale "
        "collation, which is what lets a JavaScript `a < b` on the same "
        "folded strings agree with the file's order.",
    ),
    (
        "level", "int8", "derived",
        "This catalog's 0-to-5 mapping of WOF's placetype, and the level a "
        "search filters on. It also says which boundary collection holds the "
        "row's geometry: the one at the same level.",
    ),
    (
        "placetype", "string", "attested",
        "WOF's own placetype, carried through so the placetypes sharing a "
        "level stay distinguishable: `country`, `dependency`, `disputed`, "
        "`macroregion`, `region`, `macrocounty`, `county`, `localadmin`, "
        "`locality`, `borough`, `macrohood`, `neighbourhood`, `microhood`.",
    ),
    (
        "country", "string", "derived",
        "ISO 3166-1 alpha-3, derived as in the boundary collections. A "
        "country row carries its own code. WOF's six synthetic two-letter "
        "codes have no alpha-3 and appear unchanged.",
    ),
    (
        "country_iso2", "string", "attested",
        "WOF's own two-letter code, byte for byte.",
    ),
    (
        "feature_id", "string", "attested",
        "The `wof_id` of the place, which is the column of the same name in "
        "every boundary collection. A logical key and never a row offset, "
        "which is what makes a version skew between this index and the "
        "boundary files recoverable rather than silently wrong. An "
        "alternative-spelling row repeats its place's `feature_id`, so a "
        "result list dedupes on it.",
    ),
    (
        "source", "string", "derived",
        "Constant `whosonfirst-admin` on every row. The index contract allows "
        "one index to hold several sources and requires a result to be able "
        "to say where it came from; this index holds one.",
    ),
    (
        "name_lang", "string", "attested",
        "The ISO 639-3 language code this spelling came from, or null on a "
        "primary row where the language of `wof:name` is unstated. The 25 "
        "codes are the fixed set geocode.earth's parquet build carries: "
        "`ara`, `ben`, `deu`, `eng`, `ell`, `fas`, `fra`, `heb`, `hin`, "
        "`hun`, `ind`, `ita`, `jpn`, `kor`, `nld`, `pol`, `por`, `rus`, "
        "`spa`, `swe`, `tur`, `ukr`, `urd`, `vie`, `zho`. **Who's On First "
        "itself carries far more**: one San Francisco record has 214 `name:*` "
        f"properties across 197 languages ([wof names]({WOF_NAMES})). Those "
        "live in the SQLite and GeoJSON distributions, not in the "
        "GeoParquet, so this index cannot be richer than 25 languages however "
        "multilingual WOF is.",
    ),
    (
        "name_lang_count", "int16", "derived",
        "How many of the 25 language columns fold to this exact spelling for "
        "this place. 1 on a primary row. It is high where a name travels "
        "unchanged between languages, which is a usable signal that a "
        "spelling is widely recognized.",
    ),
    (
        "alt_of", "string", "derived",
        "Null on a primary row; on an alternative-spelling row it holds that "
        "row's own `feature_id`, which is the index contract's way of marking "
        "the row as another spelling of a place whose primary row is "
        "elsewhere in the file. Filter `alt_of IS NULL` for one row per "
        "place.",
    ),
    (
        "parent_name", "string", "derived",
        "The `name` of the place's parent, resolved through `parent_id` "
        "against the boundary collections, so an autocomplete can show "
        "'Springfield, Illinois' without a second fetch. Null where the "
        "parent is outside the placetypes this catalog carries, or where "
        "`parent_id` is one of WOF's negative sentinels.",
    ),
    (
        "parent_id", "string", "attested",
        "The parent's `wof_id`. WOF's negative sentinels are carried through "
        "except `-1`, which becomes null; see the boundary collections' "
        "`parent_id`.",
    ),
    (
        "population", "int64", "attested",
        "The place's population where WOF has one, copied from its boundary "
        "row. A ranking signal, and null far more often than not.",
    ),
    (
        "min_zoom", "float", "attested",
        "WOF's `mz:min_zoom`, copied from the boundary row. The best "
        "prominence signal in this index: a lower number means WOF thinks the "
        "place should appear on a map earlier.",
    ),
    (
        "name_dupes", "int32", "derived",
        "How many distinct places in this index share this `name_norm`, "
        "anywhere in the world. An autocomplete needs it, because a bare name "
        "is often not an answer.",
    ),
    (
        "is_point", "boolean", "derived",
        "Whether this place's geometry in its boundary collection is a single "
        "point rather than a polygon. True for 84% of localities and "
        "neighbourhoods, because most of them come from GeoNames, which is a "
        "point gazetteer. A client that is about to draw an outline should "
        "check this first.",
    ),
    (
        "bbox", "struct", "derived",
        "The place's bounding box in EPSG:4326 degrees, as four float32 "
        "values rounded **outward**, so the box is never narrower than the "
        "true extent. float32 keeps about 1e-5 degrees, roughly a metre. For "
        "a point place it is the degenerate box at that point. Signed: "
        "`xmin > xmax` means the extent crosses the antimeridian.",
    ),
    (
        "geometry_ref", "struct", "derived",
        "**Advisory** `{file, row_group, row}` pointer into the boundary "
        "collection at this row's `level`, and into its display companion "
        "where there is one. `row` is the physical row offset captured with "
        "DuckDB's `file_row_number` off the published file; `row_group` is "
        "that offset floor-divided by the level's fixed row group size. A "
        "client reads the referenced row group, decodes the one row, and "
        "**must verify that row's `wof_id` equals this row's `feature_id`** "
        "before trusting the geometry. On any mismatch it falls back to "
        "locating the row by `wof_id`, which the boundary files' "
        "`(country, wof_id)` sort makes cheap. Never authoritative.",
    ),
    (
        "geometry", "byte_array", "derived",
        "WKB, one Point per row, from the place's `lon`/`lat` centroid, so "
        "this collection renders as a map of the gazetteer. It is a marker, "
        "not a shape: do not compute area, length or containment from it. The "
        "shape lives in the boundary collection at the row's `level`.",
    ),
]


def as_table_columns(columns) -> list[dict]:
    """`table:columns` entries, tag folded into the description."""
    return [
        {
            "name": name,
            "type": kind,
            "description": f"{tag.capitalize()}. {description}",
        }
        for name, kind, tag, description in columns
    ]
