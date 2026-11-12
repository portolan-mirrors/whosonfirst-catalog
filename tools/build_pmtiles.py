#!/usr/bin/env python3
"""Build one PMTiles archive per collection, for the data browser.

    python3 tools/build_pmtiles.py              # all seven
    python3 tools/build_pmtiles.py locality     # one target

`ogr2ogr` streams the published GeoParquet to newline-delimited GeoJSON on
stdout and tippecanoe reads it from a pipe, so no intermediate GeoJSON is
written. The styles read the attributes carried here, so the `-select` list in
each target and the expressions in `tools/make_styles.py` have to stay in
step; `tests/test_styles.py` is the gate that catches a drift.

Why not just point at geocode.earth's PMTiles?
----------------------------------------------
Because its tiles are too big to open. geocode.earth publishes a combined
archive, `protomaps/whosonfirst-data-admin-latest.pmtiles`, 2.0 GiB over
zoom 0 to 9, with one vector layer per placetype. It is built with
`tippecanoe -zg --no-tile-size-limit`, and that shows
(`docs/upstream-measurements.md`):

| zoom | tile | bytes |
|---|---|---|
| 0 | 0/0 | 15,671,392 |
| 2 | 2/1 | 24,260,389 |
| 3 | 4/2 | 25,954,206 |
| 5 | 16/10 | 9,255,247 |
| 8 | 133/86 | 460,379 |

A whole-world first view that costs 15.7 MB, and mid zooms that cost 24 to
26 MB, is not something a browser tab opens. The archive also reports
dropping 4,412,845 features by rate at zoom 0 to fit what it does carry, so
the low zooms are heavy *and* incomplete.

The archives here are capped per tile and tiled per level, so a first view is
tens of kilobytes. geocode.earth's archive is still linked from every
collection, because it is the one that carries all 21 placetypes in one file
and because a reader comparing the two should be able to.

Where the geometry comes from
-----------------------------
Levels 0 to 3 are tiled from the **display** geometry, not the
full-resolution one. Tippecanoe simplifies per zoom anyway, and the display
geometry is already a topology-preserving simplification of the same rings;
feeding it the full-resolution outline instead means streaming gigabytes of
WKB to produce the same tiles. The display geometry is an outward-buffered
superset of the truth, so a tile boundary sits a fraction of a tolerance
outside the real one, which at these zoom levels is well under a pixel.

Levels 4 and 5 have no display companion, because their median feature is a
single point, so they are tiled from the boundary file directly.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wofcommon import (  # noqa: E402
    COLLECTIONS,
    COLLECTION_LEVEL,
    DISPLAY_LEVELS,
    NAMES_PATH,
    WORK,
    boundary_path,
    connect,
    display_path,
    geom_src_group_sql,
    human,
    pmtiles_path,
    run,
)

# Attributes carried into the tiles. Only what a style or a popup reads: every
# extra field is repeated in every tile. tools/make_styles.py reads these same
# names, and tests/test_styles.py catches a drift between the two.
FEATURE_FIELDS = [
    "wof_id",
    "name",
    "placetype",
    "country",
    "geom_src",
    "population",
    "min_zoom",
    "area_km2",
    "vertices",
    "is_funky",
]

# Derived into the tiles rather than into the published GeoParquet. `geom_src`
# is long-tailed -- one level has 66 distinct values -- so the provenance
# style paints a grouping of it instead, defined once in
# wofcommon.GEOM_SRC_GROUPS. The raw column travels into the tiles too, for a
# popup.
DERIVED_FIELDS = ["geom_src_group"]

MAX_ZOOM = {
    "country": 6,
    "region": 8,
    "county": 9,
    "localadmin": 10,
    "locality": 11,
    "neighbourhood": 12,
}

# Polygon tiling. --detect-shared-borders keeps a shared edge between two
# neighbours simplified identically, so the coverage stays seamless instead of
# opening hairline gaps as it simplifies. --coalesce-smallest-as-needed merges
# the smallest features rather than dropping them when a tile runs over the
# size limit, which keeps the fill continuous.
POLYGON_ARGS = [
    "--detect-shared-borders",
    "--coalesce-smallest-as-needed",
    "--simplification=4",
    "--simplify-only-low-zooms",
]

# The cap that geocode.earth's own archive does not set. 400 KB per tile is
# what keeps a first view openable; the measured upstream alternative is
# 15.7 MB.
DENSE_ARGS = ["--drop-densest-as-needed", "--maximum-tile-bytes=400000"]

NAMES_FIELDS = [
    "name", "name_lang", "level", "placetype", "country",
    "name_dupes", "name_lang_count", "population", "is_point",
]
NAMES_MAX_ZOOM = 8


def tile(src: Path, out: Path, *, layer: str, name: str, maxzoom: int,
         fields: list[str], extra: list[str]) -> None:
    ogr = [
        "ogr2ogr", "-f", "GeoJSONSeq", "/vsistdout/", str(src),
        "-select", ",".join(fields),
    ]
    tip = [
        "tippecanoe", "-o", str(out), "-f", "-q",
        "-l", layer, "-n", name,
        "-z", str(maxzoom), "-Z", "0",
        *extra,
    ]
    print(f"  $ {' '.join(ogr)} | {' '.join(tip)}", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    with subprocess.Popen(ogr, stdout=subprocess.PIPE) as reader:
        subprocess.run(tip, stdin=reader.stdout, check=True)
        reader.stdout.close()
        if reader.wait() != 0:
            raise SystemExit(f"{out.name}: ogr2ogr failed")
    print(f"  {out.name}: {human(out.stat().st_size)}")
    run(["pmtiles", "show", str(out)])


def build(target: str) -> None:
    print(f"[{target}] tiling", flush=True)
    if target == "names":
        if not NAMES_PATH.exists():
            sys.exit(f"missing {NAMES_PATH}; run tools/build_names.py first")
        tile(
            NAMES_PATH,
            pmtiles_path("names"),
            layer="names",
            name="Who's On First gazetteer index",
            maxzoom=NAMES_MAX_ZOOM,
            fields=NAMES_FIELDS,
            extra=["-r1", *DENSE_ARGS],
        )
        return

    level = COLLECTION_LEVEL[target]
    full = boundary_path(target)
    if not full.exists():
        sys.exit(f"missing {full}; run tools/build_boundaries.py first")

    con = connect()
    present = set(
        con.sql(f"SELECT * FROM read_parquet('{full.as_posix()}') LIMIT 0").columns
    )
    fields = [f for f in FEATURE_FIELDS if f in present]
    cols = ", ".join(f"f.{f}" for f in fields)
    cols += f", {geom_src_group_sql('f.geom_src')} AS geom_src_group"
    fields = fields + DERIVED_FIELDS
    scratch = WORK / f"{target}.tiles.parquet"
    scratch.unlink(missing_ok=True)

    if level in DISPLAY_LEVELS:
        disp = display_path(target)
        if not disp.exists():
            sys.exit(f"missing {disp}; run tools/build_display.py first")
        sql = (
            f"SELECT {cols}, d.geometry "
            f"FROM read_parquet('{full.as_posix()}') f "
            f"JOIN read_parquet('{disp.as_posix()}') d USING (wof_id)"
        )
        source = "display geometry"
    else:
        sql = (
            f"SELECT {cols}, f.geometry "
            f"FROM read_parquet('{full.as_posix()}') f"
        )
        source = "full-resolution geometry (no display companion at this level)"

    con.execute(
        f"COPY ({sql}) TO '{scratch.as_posix()}' "
        "(FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 3)"
    )
    rows = con.execute(
        f"SELECT count(*) FROM read_parquet('{scratch.as_posix()}')"
    ).fetchone()[0]
    con.close()
    print(f"  {rows:,} rows, {len(fields)} attribute(s), from the {source}")

    extra = list(POLYGON_ARGS)
    if target in ("county", "localadmin", "locality", "neighbourhood"):
        extra += DENSE_ARGS
    try:
        tile(
            scratch,
            pmtiles_path(target),
            layer=target,
            name=f"Who's On First {target}",
            maxzoom=MAX_ZOOM[target],
            fields=fields,
            extra=extra,
        )
    finally:
        scratch.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    targets = list(COLLECTIONS) + ["names"]
    for target in argv or targets:
        if target not in targets:
            sys.exit(f"unknown target {target}; one of {', '.join(targets)}")
        build(target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
