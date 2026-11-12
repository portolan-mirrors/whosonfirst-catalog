#!/usr/bin/env python3
"""Build the display-simplified companion for the polygon-heavy levels.

    python3 tools/build_display.py              # every level that gets one
    python3 tools/build_display.py -c county    # one or more

Run `tools/build_boundaries.py` first. Each display file holds the same rows,
in the same order, in the same row groups, as the boundary file beside it, so
a consumer that knows a feature sits at row *i* of one reads row *i* of the
other without a join. That is also what makes the search index's
`geometry_ref` valid against both files.

Which levels get one, and why only those
----------------------------------------
Measured vertex counts per feature (`tools/distributions.sql`):

| level | features | median | p95 | max | point geometries |
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
add a fetch. That is a measurement, not an omission, and `DISPLAY_LEVELS` in
`tools/wofcommon.py` is where it is recorded.

What the geometry is, and why it is bigger than the truth
---------------------------------------------------------
Two steps, in this order, and only for a feature that is not already a point.

1. `ST_SimplifyPreserveTopology` at a tolerance chosen **per feature**: 0.4%
   of that feature's own bounding-box diagonal, capped at the level's
   ceiling. It keeps the ring topology, so a simplified outline stays a valid
   polygon and does not self-intersect.

2. `ST_Buffer` **outward** by the same per-feature tolerance.

The tolerance is per feature because a flat one cannot serve both Russia and
Monaco: at a flat tolerance the small feature's outline moves by most of its
own width and the simplification collapses it to a sliver the buffer cannot
recover.

Step 2 is the point. Simplification moves a vertex by up to the tolerance in
*either* direction, so a simplified outline cuts corners *inside* the true
boundary as often as outside it. A consumer that uses the display geometry to
decide what to download would then silently miss features in the slivers the
simplification cut away. Buffering outward pushes the whole outline back out
past the original, so the display shape is a superset of the truth and the
error is always inclusive. A spatial filter drawn against it over-selects,
which a later exact pass removes, rather than under-selecting, which nothing
recovers.

**Point geometries are carried through untouched.** Buffering a point by the
tolerance would turn a place marker into a circle a kilometre across and
change the geometry type of the row, which is a worse answer than the point.
Level 3 alone has 35,741 of them.

The buffer costs vertices, so it is drawn with two segments per quarter
circle rather than the default eight. The containment check at the end is what
decides whether that is enough, and it runs on every polygon of every level.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyarrow.parquet as pq  # noqa: E402

from wofcommon import (  # noqa: E402
    COLLECTIONS,
    COLLECTION_LEVEL,
    DISPLAY_LEVELS,
    DISPLAY_ROW_GROUP_ROWS,
    SIMPLIFY_SHARE,
    SIMPLIFY_TOLERANCE,
    WORK,
    boundary_path,
    connect,
    copy_ordered,
    display_path,
    footer_metadata,
    geo_metadata,
    geom_expr,
    human,
    stream_write,
)

CONTAINMENT_REPORT = WORK / "display-containment.json"

# Two segments per quarter circle. A buffer's rounded corner is approximated
# by a polygon inscribed in the true offset circle, so fewer segments means
# the corner sits slightly closer than the nominal distance. The containment
# check measures whether that matters; at these tolerances it does not.
BUFFER_SEGMENTS = 2

BUILD_SQL = """
WITH scaled AS (
  SELECT
    (row_number() OVER () - 1)::BIGINT AS ord,
    wof_id, name, placetype, country,
    {geom} AS geom,
    least(
      {tol},
      sqrt(power(bbox.xmax - bbox.xmin, 2) + power(bbox.ymax - bbox.ymin, 2))
        * {share}
    ) AS tol
  FROM read_parquet('{src}')
)
SELECT
  ord, wof_id, name, placetype, country, tol,
  CASE WHEN ST_GeometryType(geom) = 'POINT' THEN geom
       ELSE ST_Buffer(ST_SimplifyPreserveTopology(geom, tol), tol, {segs})
  END AS geometry
FROM scaled
"""

FINALIZE_SQL = """
SELECT
  wof_id, name, placetype, country,
  tol::FLOAT AS simplify_tolerance_deg,
  ST_NPoints({geom})::INTEGER AS vertices,
  {{
    xmin: ST_XMin({geom}), ymin: ST_YMin({geom}),
    xmax: ST_XMax({geom}), ymax: ST_YMax({geom})
  }} AS bbox,
  ST_AsWKB({geom}) AS geometry
FROM read_parquet('{src}')
ORDER BY ord
"""

# What fraction of each true polygon's area the display polygon covers. 1.0
# means the display shape contains the true one completely, which is the
# design intent. ST_Area is planar on degrees here, which is fine because it
# is a ratio of two areas over the same small patch of the globe. Point rows
# have no area and are excluded.
#
# Both sides go through ST_MakeValid first. The boundary files are already
# repaired, but ST_Buffer can return a self-touching ring of its own, and
# ST_Intersection against an invalid input does not return a wrong number --
# it raises `TopologyException: side location conflict` and takes the whole
# check with it. Repairing inside the check keeps it honest about area while
# letting it finish; verify_validity below is what reports whether the
# published display geometry needed it.
CONTAINMENT_SQL = """
WITH pair AS (
  SELECT b.wof_id, b.name, b.placetype, b.country,
         ST_Area(ST_MakeValid({bgeom})) AS true_area,
         ST_Area(ST_Intersection(ST_MakeValid({bgeom}),
                                 ST_MakeValid({dgeom}))) AS kept_area
  FROM read_parquet('{boundary}') b
  JOIN read_parquet('{display}') d USING (wof_id)
  WHERE ST_Area(ST_MakeValid({bgeom})) > 0
)
SELECT wof_id, name, placetype, country, kept_area / true_area AS contained
FROM pair ORDER BY contained
"""


def build(collection: str) -> dict:
    tol = SIMPLIFY_TOLERANCE[collection]
    src = boundary_path(collection)
    if not src.exists():
        sys.exit(f"missing {src}; run tools/build_boundaries.py first")
    print(
        f"[{collection}] simplifying at {SIMPLIFY_SHARE:.1%} of each "
        f"feature's bbox diagonal, capped at {tol} deg, then buffering out "
        "by the same amount"
    )

    con = connect()
    raw = WORK / f"{collection}.display.raw.parquet"
    copy_ordered(
        con,
        BUILD_SQL.format(
            tol=tol, share=SIMPLIFY_SHARE, segs=BUFFER_SEGMENTS,
            src=src.as_posix(), geom=geom_expr(con, src),
        ),
        raw,
    )
    ordered = WORK / f"{collection}.display.ordered.parquet"
    copy_ordered(
        con,
        FINALIZE_SQL.format(
            src=raw.as_posix(), geom=geom_expr(con, raw),
        ),
        ordered,
    )
    rows, tol_lo, tol_hi, *bbox = con.execute(
        f"""SELECT count(*), min(simplify_tolerance_deg),
                   max(simplify_tolerance_deg),
                   min(bbox.xmin), min(bbox.ymin),
                   max(bbox.xmax), max(bbox.ymax)
            FROM read_parquet('{ordered.as_posix()}')"""
    ).fetchone()
    con.close()
    raw.unlink(missing_ok=True)
    print(f"  tolerance used: {tol_lo:.3g} to {tol_hi:.3g} deg")

    src_rows = pq.ParquetFile(src).metadata.num_rows
    if rows != src_rows:
        sys.exit(
            f"{collection}: {rows:,} display rows against {src_rows:,} "
            "boundary rows. The two files must hold the same rows in the "
            "same order; do not publish."
        )

    write_optimized(collection, ordered, bbox)
    ordered.unlink(missing_ok=True)
    verify_alignment(collection)
    invalid = verify_validity(collection)
    result = verify_containment(collection)
    result["invalid_display_geometries"] = invalid
    return result


def write_optimized(collection: str, ordered: Path, bbox: list[float]) -> None:
    meta = footer_metadata(
        {
            "cnmw:collection": collection,
            "cnmw:role": "display",
            "cnmw:simplify_tolerance_ceiling_deg": str(
                SIMPLIFY_TOLERANCE[collection]
            ),
            "cnmw:simplify_share_of_diagonal": str(SIMPLIFY_SHARE),
            "cnmw:buffer_segments": str(BUFFER_SEGMENTS),
        }
    )
    meta[b"geo"] = geo_metadata(
        bbox=bbox, geometry_types=["Point", "Polygon", "MultiPolygon"]
    )
    out = display_path(collection)
    md = stream_write(
        ordered, out,
        row_group_rows=DISPLAY_ROW_GROUP_ROWS[collection],
        footer_meta=meta,
    )
    size = out.stat().st_size
    full = pq.ParquetFile(boundary_path(collection)).metadata
    print(
        f"  {out.name}: {human(size)}, {md.num_rows:,} rows, "
        f"{md.num_row_groups:,} row groups, "
        f"{size / md.num_rows / 1024:.1f} KiB per feature, "
        f"{100 * size / boundary_path(collection).stat().st_size:.1f}% of the "
        "full-resolution file"
    )
    if md.num_row_groups != full.num_row_groups:
        sys.exit(
            f"{collection}: {md.num_row_groups} display row groups against "
            f"{full.num_row_groups} boundary row groups; they must match"
        )


def verify_alignment(collection: str) -> None:
    """Assert row i of the display file is row i of the boundary file.

    Not a formality. The search index publishes a row number, and a consumer
    reads the same row number out of either file, so a single transposed pair
    would hand somebody another place's outline.
    """
    a = pq.read_table(
        boundary_path(collection), columns=["wof_id"]
    ).column("wof_id").to_pylist()
    b = pq.read_table(
        display_path(collection), columns=["wof_id"]
    ).column("wof_id").to_pylist()
    mismatched = sum(1 for x, y in zip(a, b) if x != y)
    if mismatched:
        sys.exit(
            f"{collection}: {mismatched:,} of {len(a):,} rows sit at a "
            "different offset in the display file than in the boundary file"
        )
    print(f"  aligned: all {len(a):,} rows at the same offset in both files")


def verify_validity(collection: str) -> int:
    """How many published display geometries fail ST_IsValid.

    The boundary files are repaired, but simplifying and then buffering can
    still produce a self-touching ring, and a consumer running a spatial join
    against one gets an exception rather than a wrong answer. This number
    belongs in the collection's known issues, not in a comment.
    """
    con = connect()
    path = display_path(collection)
    invalid = con.execute(
        f"SELECT count(*) FILTER (NOT ST_IsValid({geom_expr(con, path)})) "
        f"FROM read_parquet('{path.as_posix()}')"
    ).fetchone()[0]
    con.close()
    print(f"  validity: {invalid:,} display geometr"
          f"{'y' if invalid == 1 else 'ies'} fail ST_IsValid")
    return invalid


def verify_containment(collection: str) -> dict:
    con = connect()
    rows = con.execute(
        CONTAINMENT_SQL.format(
            boundary=boundary_path(collection).as_posix(),
            display=display_path(collection).as_posix(),
            bgeom=geom_expr(con, boundary_path(collection), alias="b"),
            dgeom=geom_expr(con, display_path(collection), alias="d"),
        )
    ).fetchall()
    con.close()
    contained = [r[4] for r in rows]
    below = [r for r in rows if r[4] < 0.99]
    complete = sum(1 for c in contained if c >= 0.999999)
    worst = min(contained) if contained else 1.0
    print(
        f"  containment: {complete:,} of {len(contained):,} polygons contain "
        f"their full-resolution shape completely, {len(below)} below 99%, "
        f"worst {worst:.4f}"
    )
    if below:
        for wof_id, name, placetype, country, value in below[:10]:
            print(f"    {value:.4f}  {name} ({placetype}, {country}, {wof_id})")
    return {
        "collection": collection,
        "polygons": len(contained),
        "complete": complete,
        "below_99": [
            {"wof_id": r[0], "name": r[1], "placetype": r[2],
             "country": r[3], "contained": r[4]}
            for r in below
        ],
        "worst": worst,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    eligible = [
        name for name in COLLECTIONS
        if COLLECTION_LEVEL[name] in DISPLAY_LEVELS
    ]
    ap.add_argument(
        "-c", "--collection", action="append", choices=eligible,
        help="build only this collection; repeatable",
    )
    args = ap.parse_args()
    results = [build(name) for name in (args.collection or eligible)]
    CONTAINMENT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    CONTAINMENT_REPORT.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\ncontainment report: {CONTAINMENT_REPORT}")
    worst = min(r["worst"] for r in results)
    below = sum(len(r["below_99"]) for r in results)
    print(f"{below} feature(s) below 99% containment, worst {worst:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
