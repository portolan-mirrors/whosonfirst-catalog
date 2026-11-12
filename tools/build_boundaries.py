#!/usr/bin/env python3
"""Build one optimized GeoParquet per admin level from the staged upstream file.

    python3 tools/build_boundaries.py            # every level
    python3 tools/build_boundaries.py -l 0 -l 1  # just these

Run `tools/fetch_sources.py` first.

Why these files exist at all
----------------------------
This catalog links to geocode.earth's combined GeoParquet for bulk work, and
that is the right file for a scan, an export or a spatial query: it is
GeoParquet 1.1 with a `covering` bbox, it is spatially clustered, and
geocode.earth serves it with range requests and permissive CORS.

It is the wrong file for fetching **one** feature, and the numbers are in
`docs/upstream-measurements.md`. It has 83 row groups of 65,536 rows, no
declared sort, and 89% of its bytes in the `geometry` column, so one row
group's geometry chunk is a median of 38 MiB and as much as 285 MiB. A
row-group-granular reader -- which is every Parquet reader, including the
hyparquet a browser uses -- pays that to decode one row. `placetype`
statistics span most of the alphabet in most row groups, so filtering to one
level prunes nothing either.

These files fix exactly that, and nothing else:

* **One file per level**, so a level filter is a file choice.
* **Sorted by `(country, wof_id)`** with `sorting_columns` declared, which is
  what the index contract (design doc §6.4) asks of a boundary mirror: a
  country predicate prunes row groups, and a `wof_id` lookup inside a country
  is a binary search over row group statistics.
* **Small, exactly-full row groups**, sized per level from the measured
  compressed bytes per row so that one group is roughly 1-2 MB. Every group is
  exactly `ROW_GROUP_ROWS[level]` rows, so a row number alone says which group
  a row is in -- which is what makes the index's `geometry_ref` a single
  range read.
* **zstd** rather than the upstream's snappy, and a Parquet page index, so a
  reader can fetch one page of one column chunk.
* **A `bbox` covering column and `cnmw:catalog_version` footer metadata**, so
  a client can prune spatially without decoding geometry and can detect a
  version skew between these files and the search index.

What changes from upstream, and what does not
---------------------------------------------
No row is dropped except by placetype: the non-administrative placetypes
(`campus`, `postalregion`, `timezone`, `marinearea`, `marketarea`, `ocean`,
`continent`, `empire`) are out of scope and `PLACETYPE_EXCLUDED` says why for
each. No coordinate is moved. No attribute value is edited.

Columns change in three ways, all of them recorded in
`catalog/changes-from-upstream.md`:

1. **The 25 `name_*` language columns are not carried here.** The `names`
   collection carries every one of them as its own row, which is the view a
   search wants, and repeating 11,280,783 language strings beside the geometry
   would add them to the bytes a map draw has to fetch. The primary `name`
   stays.
2. **Identifiers are carried as strings.** `id`, `parent_id`, `country_id`,
   `region_id`, `county_id` and `gn_id` arrive as a mix of INT32 and
   JSON-typed strings; they are all WOF integer ids, and they are published as
   decimal strings so that this catalog's files join to each other and to the
   search index with no cast. Empty strings become nulls.
3. **Five columns are added**: `level`, `country` (ISO 3166-1 alpha-3 derived
   from WOF's alpha-2), `area_km2` and `perimeter_km` (geodesic), `vertices`,
   and the `bbox` covering struct.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from wofcommon import (  # noqa: E402
    COLLECTIONS,
    COLLECTION_LEVEL,
    PUBLISH,
    ROW_GROUP_ROWS,
    SOURCES,
    UPSTREAM_PARQUET_NAME,
    WORK,
    boundary_path,
    connect,
    copy_ordered,
    footer_metadata,
    geo_metadata,
    human,
    register_iso3166,
    stream_write,
)

SOURCE = SOURCES / UPSTREAM_PARQUET_NAME

# Everything carried through from upstream, in the order it is published.
# `NULLIF(x, '')` throughout: the upstream file stores an absent value as the
# empty string, not as null, in every one of its JSON-typed string columns.
SELECT = """
SELECT
  s.id::VARCHAR                                    AS wof_id,
  NULLIF(s.parent_id::VARCHAR, '-1')               AS parent_id,
  s.name                                           AS name,
  s.placetype                                      AS placetype,
  {level}::TINYINT                                 AS level,
  coalesce(iso.alpha_3, upper(s.country))          AS country,
  NULLIF(s.country, '')                            AS country_iso2,
  NULLIF(s.placelocal, '')                         AS placetype_local,
  s.repo                                           AS repo,
  s.lat                                            AS lat,
  s.lon                                            AS lon,
  TRY_CAST(NULLIF(s.min_zoom, '') AS FLOAT)        AS min_zoom,
  TRY_CAST(NULLIF(s.max_zoom, '') AS FLOAT)        AS max_zoom,
  TRY_CAST(NULLIF(s.min_label, '') AS FLOAT)       AS min_label,
  TRY_CAST(NULLIF(s.max_label, '') AS FLOAT)       AS max_label,
  TRY_CAST(NULLIF(s.population, '') AS BIGINT)     AS population,
  TRY_CAST(NULLIF(s.is_funky, '') AS TINYINT)      AS is_funky,
  s.modified                                       AS modified,
  NULLIF(s.country_id, '')                         AS country_wof_id,
  NULLIF(s.region_id, '')                          AS region_wof_id,
  NULLIF(s.county_id, '')                          AS county_wof_id,
  NULLIF(s.iso_code, '')                           AS iso_code,
  NULLIF(s.hasc_id, '')                            AS hasc_id,
  NULLIF(s.gn_id, '')                              AS geonames_id,
  NULLIF(s.wd_id, '')                              AS wikidata_id,
  NULLIF(s.concord_ke, '')                         AS concordance_keys,
  NULLIF(s.concord_id, '')                         AS concordance_ids,
  NULLIF(s.geom_src, '')                           AS geom_src,
  round(ST_Area_Spheroid(s.geometry) / 1e6, 6)     AS area_km2,
  round(ST_Perimeter_Spheroid(s.geometry) / 1e3, 6) AS perimeter_km,
  ST_NPoints(s.geometry)::INTEGER                  AS vertices,
  {{
    xmin: ST_XMin(s.geometry), ymin: ST_YMin(s.geometry),
    xmax: ST_XMax(s.geometry), ymax: ST_YMax(s.geometry)
  }}                                               AS bbox,
  ST_AsWKB(s.geometry)                             AS geometry
FROM read_parquet('{source}') s
LEFT JOIN iso3166 iso ON iso.alpha_2 = upper(s.country)
WHERE s.placetype IN ({placetypes})
ORDER BY country, wof_id
"""

GEOMETRY_TYPES = ["Point", "Polygon", "MultiPolygon"]


def build(con, collection: str) -> dict:
    level = COLLECTION_LEVEL[collection]
    placetypes = ", ".join(f"'{p}'" for p in COLLECTIONS[collection])
    intermediate = WORK / f"{collection}_ordered.parquet"

    print(f"[{collection}] level {level}, placetypes {placetypes}", flush=True)
    copy_ordered(
        con,
        SELECT.format(
            level=level, source=SOURCE.as_posix(), placetypes=placetypes
        ),
        intermediate,
    )
    rows = pq.ParquetFile(intermediate).metadata.num_rows
    print(f"  ordered {rows:,} rows -> {human(intermediate.stat().st_size)}")

    out = boundary_path(collection)
    bbox = whole_bbox(intermediate)
    meta = footer_metadata({"wof:level": str(level)})
    meta[b"geo"] = geo_metadata(bbox=bbox, geometry_types=GEOMETRY_TYPES)
    md = stream_write(
        intermediate,
        out,
        row_group_rows=ROW_GROUP_ROWS[collection],
        footer_meta=meta,
        sorting_columns=sorting_columns(intermediate),
    )
    intermediate.unlink()

    size = out.stat().st_size
    per_group = size / md.num_row_groups
    print(
        f"  {out.name}: {size:,} bytes, {md.num_rows:,} rows, "
        f"{md.num_row_groups} groups of {ROW_GROUP_ROWS[collection]} "
        f"({human(per_group)} per group)"
    )
    if not 0.5e6 <= per_group <= 4e6:
        print(
            f"  WARNING: {human(per_group)} per row group is outside the "
            "0.5-4 MB band; retune ROW_GROUP_ROWS in tools/wofcommon.py"
        )
    print(f"  bbox: {[round(v, 6) for v in bbox]}")
    return {
        "collection": collection,
        "level": level,
        "rows": md.num_rows,
        "row_groups": md.num_row_groups,
        "size": size,
        "bbox": bbox,
    }


def sorting_columns(src: Path):
    """`(country, wof_id)` ascending, nulls first, as Parquet sorting columns."""
    schema = pq.ParquetFile(src).schema_arrow
    return [
        pq.SortingColumn(schema.get_field_index(name), descending=False,
                         nulls_first=True)
        for name in ("country", "wof_id")
    ]


def whole_bbox(src: Path) -> list[float]:
    """The union of the bbox struct, read from the file's own statistics."""
    md = pq.ParquetFile(src).metadata
    names = {"bbox.xmin": [], "bbox.ymin": [], "bbox.xmax": [], "bbox.ymax": []}
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        for i in range(rg.num_columns):
            col = rg.column(i)
            if col.path_in_schema in names and col.statistics is not None:
                names[col.path_in_schema].append(
                    (col.statistics.min, col.statistics.max)
                )
    return [
        min(lo for lo, _ in names["bbox.xmin"]),
        min(lo for lo, _ in names["bbox.ymin"]),
        max(hi for _, hi in names["bbox.xmax"]),
        max(hi for _, hi in names["bbox.ymax"]),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "-c", "--collection", action="append", choices=sorted(COLLECTIONS),
        help="build only this collection; repeatable",
    )
    args = ap.parse_args()
    if not SOURCE.exists():
        sys.exit(f"missing {SOURCE}; run tools/fetch_sources.py first")

    wanted = args.collection or [
        name for name, _ in sorted(COLLECTION_LEVEL.items(), key=lambda kv: kv[1])
    ]
    PUBLISH.mkdir(parents=True, exist_ok=True)
    con = connect()
    count = register_iso3166(con)
    print(f"iso3166: {count} alpha-2 to alpha-3 pairs from pycountry")
    try:
        results = [build(con, name) for name in wanted]
    finally:
        con.close()

    total = sum(r["size"] for r in results)
    print(f"\n{len(results)} file(s), {human(total)} total")
    assert pa  # the import is what gives stream_write its writer
    return 0


if __name__ == "__main__":
    sys.exit(main())
