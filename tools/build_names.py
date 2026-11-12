#!/usr/bin/env python3
"""Build the gazetteer name index and its manifest.

    python3 tools/build_names.py

Run `tools/build_boundaries.py` first, and `tools/build_display.py` if the
display companions are wanted in the manifest. This script reads the published
boundary files for everything except the language columns, so the index and
the boundaries cannot disagree about a place's level, country, parent or row
offset.

What this file is
-----------------
The one artifact in this catalog with no upstream equivalent. Who's On First
is a gazetteer, and geocode.earth distributes it as a 5.5 GiB GeoParquet, a
42 GiB SQLite database and a 2 GiB PMTiles archive -- none of which answers
"what places are called something like *this*" without reading all of it.
This file does, from a static host, with no server:

* **One row per place, plus one row per distinct alternative spelling of its
  name**, drawn from the 25 language columns geocode.earth's parquet build
  carries.
* **Sorted by `name_norm`**, a folded form of the name, so a typed prefix
  lives in a contiguous run of row groups that a client finds by binary
  search over the Parquet row group statistics and fetches with HTTP range
  requests.
* **Every row carries what a result list needs** without a second fetch: the
  display spelling, the level, the country, the parent's name, the
  population, WOF's own `min_zoom` label-importance signal, a bbox to fly to,
  a point to pin, and an advisory `geometry_ref` that turns the geometry fetch
  into a single range read.

This is place-name and boundary lookup, not address geocoding: there is no
street or house number anywhere in Who's On First's admin distribution.

How the alternative-spelling rows are chosen
--------------------------------------------
The upstream file carries 25 fixed language columns (`name_ara` through
`name_zho`) holding 11,280,783 non-empty values across the placetypes this
catalog carries. Most of them are not new information: `name_eng` usually
repeats the primary name, and several languages often agree on one spelling.

So a language value becomes a row only when its **folded** form differs from
the folded primary name and from every other language's folded form for the
same place. Where several languages agree, one row is kept carrying the
first language code in alphabetical order, and `name_lang_count` says how
many agreed. The build reports how many rows survived.

The folding is the index contract's: NFD, combining marks dropped, everything
outside Unicode letters, digits, space, hyphen and apostrophe replaced by a
space, whitespace collapsed, trimmed, lowercased. It is Unicode-aware, so a
Han or Arabic spelling folds to itself and is findable in its own script
rather than collapsing to the empty string.

`geometry_ref` -- the fast path, and why it is only advisory
-----------------------------------------------------------
Every row carries a `{file, row_group, row}` pointer into its level's
boundary file. `row` is the physical row offset the place sits at in that
file, captured with DuckDB's `file_row_number` straight off the published
file this script reads, so it cannot drift from what a range read will land
on. `row_group` is that offset floor-divided by the level's fixed row group
size, which is how `tools/build_boundaries.py` wrote the file.

A client reads the referenced row group, decodes the one row, and **must
verify that row's `wof_id` equals the result's own `feature_id`** before
trusting its geometry. On any mismatch -- a stale pointer, a rebuilt boundary
file, a version-skewed cache -- it falls back to locating the row by
`wof_id`, which the boundary files' `(country, wof_id)` sort and row group
statistics make cheap. Because the display companion holds the same rows at
the same offsets, one pointer resolves against either file.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyarrow as pa  # noqa: E402
import pyarrow.compute as pc  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from wofcommon import (  # noqa: E402
    ATTRIBUTION_BLOCKS,
    CATALOG_VERSION,
    COLLECTIONS,
    COLLECTION_LEVEL,
    DISPLAY_LEVELS,
    EXTRACTION_DATE,
    NAME_LANGS,
    NAMES_MANIFEST_NAME,
    NAMES_PATH,
    NAMES_ROW_GROUP_ROWS,
    NAMES_ROW_GROUP_TARGET_KIB,
    PLACETYPE_LEVEL,
    ROW_GROUP_ROWS,
    UPSTREAM_PARQUET,
    WORK,
    boundary_path,
    connect,
    copy_ordered,
    display_path,
    footer_metadata,
    geo_metadata,
    human,
    normalize_name,
    pycountry_version,
    shrink_bbox_float32,
    staged_source,
    stream_write,
)

SOURCE_NAME = "whosonfirst-admin"

# The only columns a client prunes row groups on. The footer carries one
# thrift record per column per row group, and a range client reads the whole
# footer before it reads anything, so statistics on the other 17 columns are
# cost with no benefit. Measured: statistics on everything made the footer
# 4,541,351 bytes of a 580 MB file, which a cold first lookup paid in full.
STATISTICS_COLUMNS = ["name_norm", "level", "country", "feature_id"]
LONG = WORK / "names.long.parquet"
NORMED = WORK / "names.normed.parquet"
SORTED = WORK / "names.sorted.parquet"

# Stage 1: the authoritative per-place facts, read from the published boundary
# files, with the physical row offset each place sits at. `file_row_number` is
# the only way to get that offset without assuming anything about the write.
PLACES_SQL = """
SELECT * EXCLUDE (file_row_number),
       file_row_number AS row_index,
       '{collection}' AS collection
FROM read_parquet('{src}', file_row_number=true)
"""

# Stage 2: one row per (place, name variant), ordered by place so that the
# normalizer can dedupe a place's variants in one pass without holding the
# whole index in memory. The primary row sorts first within a place because
# `lang` is null and nulls sort first.
LONG_SQL = """
WITH langs AS (
  SELECT s.id::VARCHAR AS wof_id, u.lang, u.v AS raw
  FROM read_parquet('{source}') s,
       UNNEST([{structs}]) AS t(u)
  WHERE s.placetype IN ({placetypes})
    AND u.v IS NOT NULL AND u.v <> ''
),
variants AS (
  SELECT wof_id, NULL::VARCHAR AS name_lang, name AS raw FROM places
  UNION ALL
  SELECT l.wof_id, l.lang, l.raw
  FROM langs l JOIN places p USING (wof_id)
)
SELECT
  v.wof_id AS feature_id,
  v.name_lang,
  v.raw,
  p.name AS primary_name,
  p.level,
  p.placetype,
  p.country,
  p.country_iso2,
  p.parent_id,
  p.population,
  p.min_zoom,
  p.lat,
  p.lon,
  p.is_point,
  p.collection,
  p.row_index,
  p.xmin, p.ymin, p.xmax, p.ymax
FROM variants v JOIN places p USING (wof_id)
ORDER BY v.wof_id, v.name_lang
"""

# Stage 4: the facts that need the whole index in one place -- how many places
# share a folded name, and what a place's parent is called -- plus the sort
# the file's whole design rests on.
FINAL_SQL = """
WITH dupes AS (
  SELECT name_norm, count(DISTINCT feature_id)::INTEGER AS name_dupes
  FROM read_parquet('{normed}')
  GROUP BY 1
),
parents AS (
  SELECT wof_id, name FROM read_parquet([{boundaries}])
)
SELECT
  n.raw AS name,
  n.name_norm,
  n.level::TINYINT AS level,
  n.placetype,
  n.country,
  n.country_iso2,
  n.feature_id,
  '{source_name}' AS source,
  n.name_lang,
  n.name_lang_count::SMALLINT AS name_lang_count,
  n.alt_of,
  par.name AS parent_name,
  n.parent_id,
  n.population,
  n.min_zoom::FLOAT AS min_zoom,
  d.name_dupes,
  n.is_point,
  {{
    xmin: n.xmin, ymin: n.ymin, xmax: n.xmax, ymax: n.ymax
  }} AS bbox,
  {{
    file: n.collection, row_group: n.row_group, row: n.row_index
  }} AS geometry_ref,
  ST_AsWKB(ST_Point(n.lon, n.lat)) AS geometry
FROM read_parquet('{normed}') n
JOIN dupes d USING (name_norm)
LEFT JOIN parents par ON par.wof_id = n.parent_id
ORDER BY n.name_norm, n.level, n.country, n.feature_id
"""


def stage_long(con) -> int:
    """Write the one-row-per-variant intermediate."""
    structs = ", ".join(
        f"{{lang:'{lang}', v:s.name_{lang}}}" for lang in NAME_LANGS
    )
    placetypes = ", ".join(f"'{p}'" for p in PLACETYPE_LEVEL)

    parts = []
    for collection in COLLECTIONS:
        src = boundary_path(collection)
        if not src.exists():
            sys.exit(f"missing {src}; run tools/build_boundaries.py first")
        parts.append(
            PLACES_SQL.format(collection=collection, src=src.as_posix())
        )
    con.execute(
        "CREATE OR REPLACE TEMP VIEW places AS "
        "SELECT wof_id, name, level, placetype, country, country_iso2, "
        "       parent_id, population, min_zoom, lat, lon, collection, "
        "       row_index, (vertices = 1) AS is_point, "
        "       bbox.xmin AS xmin, bbox.ymin AS ymin, "
        "       bbox.xmax AS xmax, bbox.ymax AS ymax "
        "FROM (" + " UNION ALL ".join(parts) + ")"
    )
    places = con.execute("SELECT count(*) FROM places").fetchone()[0]
    print(f"  places: {places:,} across {len(COLLECTIONS)} boundary files")

    copy_ordered(
        con,
        LONG_SQL.format(
            source=staged_source().as_posix(),
            structs=structs,
            placetypes=placetypes,
        ),
        LONG,
    )
    rows = pq.ParquetFile(LONG).metadata.num_rows
    print(
        f"  variants: {rows:,} rows "
        f"({rows - places:,} language values on {places:,} places)"
    )
    return places


def _fold(name: str | None) -> str | None:
    """normalize_name, inlined for the hot loop."""
    return normalize_name(name)


def stage_normalize() -> dict:
    """Fold every variant, drop the empty ones, and dedupe within a place.

    Streamed, with a carry buffer, because the intermediate is ordered by
    `feature_id` but a batch boundary can split a place's variants.
    """
    reader = pq.ParquetFile(LONG)
    schema = pa.schema(
        [
            ("feature_id", pa.string()),
            ("raw", pa.string()),
            ("name_norm", pa.string()),
            ("name_lang", pa.string()),
            ("name_lang_count", pa.int32()),
            ("alt_of", pa.string()),
            ("level", pa.int8()),
            ("placetype", pa.string()),
            ("country", pa.string()),
            ("country_iso2", pa.string()),
            ("parent_id", pa.string()),
            ("population", pa.int64()),
            ("min_zoom", pa.float64()),
            ("lat", pa.float64()),
            ("lon", pa.float64()),
            ("is_point", pa.bool_()),
            ("collection", pa.string()),
            ("row_index", pa.int64()),
            ("row_group", pa.int32()),
            ("xmin", pa.float64()),
            ("ymin", pa.float64()),
            ("xmax", pa.float64()),
            ("ymax", pa.float64()),
        ]
    )
    counts = {
        "primary": 0, "alt": 0, "dropped_unnamed": 0,
        "alt_same_as_primary": 0, "alt_duplicate_spelling": 0,
    }
    NORMED.parent.mkdir(parents=True, exist_ok=True)
    NORMED.unlink(missing_ok=True)
    writer = pq.ParquetWriter(NORMED, schema, compression="zstd",
                              compression_level=3)
    carry: list[dict] = []

    def flush(place_rows: list[dict], out: list[dict]) -> None:
        """Resolve one place's variants into the rows that get published."""
        primary = place_rows[0]
        norm = _fold(primary["raw"])
        if not norm:
            counts["dropped_unnamed"] += 1
            return
        primary["name_norm"] = norm
        primary["name_lang"] = None
        primary["name_lang_count"] = 1
        primary["alt_of"] = None
        out.append(primary)
        counts["primary"] += 1

        seen: dict[str, dict] = {}
        for row in place_rows[1:]:
            folded = _fold(row["raw"])
            if not folded:
                continue
            if folded == norm:
                counts["alt_same_as_primary"] += 1
                continue
            existing = seen.get(folded)
            if existing is not None:
                existing["name_lang_count"] += 1
                counts["alt_duplicate_spelling"] += 1
                continue
            row["name_norm"] = folded
            row["name_lang_count"] = 1
            row["alt_of"] = row["feature_id"]
            seen[folded] = row
            out.append(row)
            counts["alt"] += 1

    def emit(rows: list[dict]) -> None:
        if not rows:
            return
        arrays = []
        for field in schema:
            arrays.append(
                pa.array([r.get(field.name) for r in rows], field.type)
            )
        writer.write_table(pa.Table.from_arrays(arrays, schema=schema))

    try:
        for batch in reader.iter_batches(batch_size=200_000):
            rows = batch.to_pylist()
            if carry:
                rows = carry + rows
                carry = []
            # Hold back the trailing place: the next batch may continue it.
            last = rows[-1]["feature_id"]
            cut = len(rows)
            while cut > 0 and rows[cut - 1]["feature_id"] == last:
                cut -= 1
            carry = rows[cut:]
            out: list[dict] = []
            start = 0
            for i in range(1, cut + 1):
                if i == cut or rows[i]["feature_id"] != rows[start]["feature_id"]:
                    prepare(rows[start:i])
                    flush(rows[start:i], out)
                    start = i
            emit(out)
        if carry:
            out = []
            start = 0
            for i in range(1, len(carry) + 1):
                if (
                    i == len(carry)
                    or carry[i]["feature_id"] != carry[start]["feature_id"]
                ):
                    prepare(carry[start:i])
                    flush(carry[start:i], out)
                    start = i
            emit(out)
    finally:
        writer.close()

    print(
        f"  normalized: {counts['primary']:,} primary + {counts['alt']:,} "
        f"alternative spellings"
    )
    print(
        f"    {counts['alt_same_as_primary']:,} language values folded to the "
        f"primary name, {counts['alt_duplicate_spelling']:,} agreed with "
        "another language"
    )
    print(f"    dropped_unnamed: {counts['dropped_unnamed']:,}")
    return counts


def prepare(place_rows: list[dict]) -> None:
    """Fill the one derived field every variant row of a place shares.

    `row_group` is the row offset floor-divided by the level's fixed row group
    size, which is how `tools/build_boundaries.py` wrote the file. The bbox
    comes from the boundary file's own `bbox` covering column, so a point
    place carries its degenerate point bbox and a polygon place carries its
    true extent -- neither is reconstructed here.
    """
    group = ROW_GROUP_ROWS[place_rows[0]["collection"]]
    for row in place_rows:
        row["row_group"] = row["row_index"] // group


def stage_final(con) -> pa.Table:
    boundaries = ", ".join(
        f"'{boundary_path(c).as_posix()}'" for c in COLLECTIONS
    )
    copy_ordered(
        con,
        FINAL_SQL.format(
            normed=NORMED.as_posix(),
            boundaries=boundaries,
            source_name=SOURCE_NAME,
        ),
        SORTED,
    )
    return SORTED


def narrow_bbox(table: pa.Table) -> pa.Table:
    idx = table.schema.get_field_index("bbox")
    return table.set_column(
        idx, "bbox", shrink_bbox_float32(table.column("bbox"))
    )


def write_index() -> dict:
    meta = footer_metadata({"cnmw:role": "names-index"})
    bbox = whole_bbox(SORTED)
    meta[b"geo"] = geo_metadata(bbox=bbox, geometry_types=["Point"])
    md = stream_write(
        SORTED,
        NAMES_PATH,
        row_group_rows=NAMES_ROW_GROUP_ROWS,
        footer_meta=meta,
        transform=narrow_bbox,
        statistics_columns=STATISTICS_COLUMNS,
        sorting_columns=[
            pq.SortingColumn(
                pq.ParquetFile(SORTED).schema_arrow.get_field_index("name_norm"),
                descending=False,
                nulls_first=True,
            )
        ],
    )
    size = NAMES_PATH.stat().st_size
    per_group = size / md.num_row_groups / 1024
    print(
        f"  {NAMES_PATH.name}: {size:,} bytes ({human(size)}), "
        f"{md.num_rows:,} rows, {md.num_row_groups:,} groups of "
        f"{NAMES_ROW_GROUP_ROWS} ({per_group:.0f} KiB per group)"
    )
    lo, hi = NAMES_ROW_GROUP_TARGET_KIB
    if not lo <= per_group <= hi:
        print(
            f"  note: {per_group:.0f} KiB per row group is outside the "
            f"{lo}-{hi} KiB band NAMES_ROW_GROUP_ROWS targets"
        )
    return {"rows": md.num_rows, "row_groups": md.num_row_groups,
            "size": size, "bbox": bbox}


def whole_bbox(src: Path) -> list[float]:
    md = pq.ParquetFile(src).metadata
    found = {"bbox.xmin": [], "bbox.ymin": [], "bbox.xmax": [], "bbox.ymax": []}
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        for i in range(rg.num_columns):
            col = rg.column(i)
            if col.path_in_schema in found and col.statistics is not None:
                found[col.path_in_schema].append(
                    (col.statistics.min, col.statistics.max)
                )
    return [
        min(lo for lo, _ in found["bbox.xmin"]),
        min(lo for lo, _ in found["bbox.ymin"]),
        max(hi for _, hi in found["bbox.xmax"]),
        max(hi for _, hi in found["bbox.ymax"]),
    ]


def multihash(path: Path) -> str:
    """A sha2-256 multihash, matching what `file:checksum` carries."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 << 20), b""):
            digest.update(chunk)
    return "1220" + digest.hexdigest()


def stats_truncated() -> bool:
    """Whether the writer truncated any `name_norm` statistic.

    The contract widens a client's binary search by one group on each side
    when this is true, so it has to be measured rather than assumed.
    """
    md = pq.ParquetFile(NAMES_PATH).metadata
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        for i in range(rg.num_columns):
            col = rg.column(i)
            if col.path_in_schema != "name_norm":
                continue
            if col.is_stats_set and not (
                col.statistics.has_min_max
            ):
                return True
    return False


def manifest(index: dict, counts: dict) -> dict:
    boundaries = []
    for collection in COLLECTIONS:
        level = COLLECTION_LEVEL[collection]
        full = boundary_path(collection)
        full_md = pq.ParquetFile(full).metadata
        entry = {
            "level": level,
            "collection": collection,
            "feature_id_column": "wof_id",
            "country_column": "country",
            "geometry_column": "geometry",
            "row_group_rows": ROW_GROUP_ROWS[collection],
            "full": {
                "url": f"../{collection}/{full.name}",
                "size": full.stat().st_size,
                "row_count": full_md.num_rows,
                "row_groups": full_md.num_row_groups,
            },
        }
        disp = display_path(collection)
        if level in DISPLAY_LEVELS and disp.exists():
            disp_md = pq.ParquetFile(disp).metadata
            entry["display"] = {
                "url": f"../{collection}/{disp.name}",
                "size": disp.stat().st_size,
                "row_count": disp_md.num_rows,
                "row_groups": disp_md.num_row_groups,
            }
        boundaries.append(entry)

    footer, page_index = footer_bytes(NAMES_PATH)
    return {
        "spec": "cnmw-index/1.0",
        "source": SOURCE_NAME,
        "index_version": f"{EXTRACTION_DATE}T00:00:00Z",
        "catalog_version": CATALOG_VERSION,
        "rows": index["rows"],
        "primary_rows": counts["primary"],
        "alt_rows": counts["alt"],
        "levels": sorted(COLLECTION_LEVEL.values()),
        "level_names": {
            str(COLLECTION_LEVEL[c]): list(COLLECTIONS[c]) for c in COLLECTIONS
        },
        "stats_truncated": stats_truncated(),
        "dropped_unnamed": counts["dropped_unnamed"],
        "index": {
            "url": f"./{NAMES_PATH.name}",
            "size": index["size"],
            "checksum": multihash(NAMES_PATH),
            "row_groups": index["row_groups"],
            "row_group_rows": NAMES_ROW_GROUP_ROWS,
            "footer_bytes": footer,
            "page_index_bytes": page_index,
            "sorted_by": ["name_norm", "level", "country", "feature_id"],
            "feature_id_column": "feature_id",
        },
        "boundaries": boundaries,
        "attribution": list(ATTRIBUTION_BLOCKS),
        "share_alike": False,
        "upstream": {
            "url": UPSTREAM_PARQUET,
            "built": "2025-04-07T13:07:59Z",
        },
        "build": {"pycountry": pycountry_version()},
    }


def footer_bytes(path: Path) -> tuple[int, int]:
    """The footer, and the page index that sits before it.

    A range client reads the footer before it can read any row group, and the
    manifest declares `index.size` so that read can be one exactly-sized tail
    request. This is what that request has to fetch.
    """
    md = pq.ParquetFile(path).metadata
    last = md.row_group(md.num_row_groups - 1)
    end_of_data = 0
    for i in range(last.num_columns):
        col = last.column(i)
        start = col.dictionary_page_offset or col.data_page_offset
        end_of_data = max(end_of_data, start + col.total_compressed_size)
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(-8, 2)
        metadata_len = int.from_bytes(fh.read(8)[:4], "little")
    footer = metadata_len + 8
    return footer, size - end_of_data - footer


def main() -> int:
    con = connect()
    try:
        print("stage 1/4: places and their row offsets")
        stage_long(con)
        print("stage 2/4: folding and deduping the name variants")
        counts = stage_normalize()
        LONG.unlink(missing_ok=True)
        print("stage 3/4: name_dupes, parent names, and the sort")
        stage_final(con)
    finally:
        con.close()
    NORMED.unlink(missing_ok=True)

    print("stage 4/4: writing the index")
    index = write_index()
    SORTED.unlink(missing_ok=True)

    # The manifest is metadata, not data: it is a kilobyte of JSON a client
    # fetches before the index, so it lives in git under `catalog/` and
    # publishes with the rest of the catalog rather than through
    # tools/upload_data.py.
    doc = manifest(index, counts)
    out = (
        Path(__file__).resolve().parents[1] / "catalog" / "names"
        / NAMES_MANIFEST_NAME
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"  {out.relative_to(Path(__file__).resolve().parents[1])}: "
          f"{out.stat().st_size:,} bytes")
    print(f"  bbox: {[round(v, 6) for v in index['bbox']]}")
    assert pc  # used by shrink_bbox_float32 through pyarrow.compute
    return 0


if __name__ == "__main__":
    sys.exit(main())
