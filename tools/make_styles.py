#!/usr/bin/env python3
"""Generate the MapLibre styles, with every class break measured.

    python3 tools/make_styles.py

Run the boundary, display, names and PMTiles builds first. Every `match`
branch and every `step` band here carries the count of features that land in
it, measured on the built file rather than guessed, and the measurement
decides whether the class exists at all: a branch that nothing falls into is
dropped. `tests/test_styles.py` is the gate that re-reads the same expressions
back and counts the rows each branch would colour, and it fails on an empty
band or on a populated value no branch covers.

The legend rule
---------------
The data browser derives a legend only from a `fill` layer whose `fill-color`
is a `match` or `step` array expression. An `interpolate` or `case`
expression yields nothing, and a line, circle or symbol layer yields nothing.

So the six boundary collections, which are polygons, get fill-based styles
with legends. The `names` collection is one point per row, so its styles are
circle layers and carry no legend by construction. Its own README says so
rather than leaving a reader to wonder why.

Palettes
--------
One hue family per collection, none of them reused from the two sibling
catalogs, which between them took ochre, teal, violet, amber, azure, moss,
coral, slate, rose and chartreuse. Seven cards in a grid have to be seven
cards a reader can tell apart at a glance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wofcommon import (  # noqa: E402
    COLLECTIONS,
    NAMES_PATH,
    boundary_path,
    connect,
    geom_src_group_sql,
)

CATALOG = Path(__file__).resolve().parents[1] / "catalog"

# Sequential ramps, light to dark, six steps each.
MAROON = ["#fbe9e7", "#f3c0ba", "#e5897f", "#cf5546", "#a32f22", "#6b150c"]
UMBER = ["#f5ece2", "#e3cdb2", "#c7a37b", "#a67a4c", "#7d552e", "#4d3217"]
SAND = ["#faf4e2", "#eee0b3", "#ddc67c", "#c4a74c", "#9c822c", "#665216"]
PERIWINKLE = ["#eceefb", "#c8cef2", "#9aa4e4", "#6e79d0", "#4a52a6", "#2a2e6b"]
FUCHSIA = ["#fce9f6", "#f6c2e6", "#ea8ecd", "#d45aae", "#a93281", "#6e1250"]
INDIGO = ["#eaeafa", "#c6c6ef", "#9898dd", "#6e6ec6", "#4747a0", "#272763"]
BRICK = ["#fcece6", "#f4c9b5", "#e59b78", "#cb6f47", "#9f4a26", "#68290e"]

PALETTE = {
    "country": MAROON,
    "region": UMBER,
    "county": SAND,
    "localadmin": PERIWINKLE,
    "locality": FUCHSIA,
    "neighbourhood": INDIGO,
    "names": BRICK,
}

GREY = "#cfcfcf"


def fill(layer: str, color) -> dict:
    return {
        "id": f"{layer}-fill",
        "type": "fill",
        "source": "data",
        "source-layer": layer,
        "paint": {
            "fill-color": color,
            "fill-opacity": 0.85,
            "fill-outline-color": "rgba(40,40,40,0.35)",
        },
    }


def outline(layer: str) -> dict:
    return {
        "id": f"{layer}-line",
        "type": "line",
        "source": "data",
        "source-layer": layer,
        "paint": {"line-color": "rgba(30,30,30,0.55)", "line-width": 0.4},
    }


def circle(layer: str, color) -> dict:
    return {
        "id": f"{layer}-circle",
        "type": "circle",
        "source": "data",
        "source-layer": layer,
        "paint": {
            "circle-color": color,
            "circle-radius": [
                "interpolate", ["linear"], ["zoom"], 0, 1.1, 4, 2.6, 8, 5.0
            ],
            "circle-opacity": 0.85,
            "circle-stroke-width": 0.3,
            "circle-stroke-color": "rgba(30,30,30,0.5)",
        },
    }


def style(collection: str, name: str, title: str, layers: list[dict]) -> None:
    doc = {
        "version": 8,
        "name": title,
        "sources": {
            "data": {
                "type": "vector",
                "url": f"pmtiles://../{collection}.pmtiles",
            }
        },
        "layers": layers,
    }
    out = CATALOG / collection / "styles" / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"  {out.relative_to(CATALOG)}  {title}")


def match_expr(field: str, pairs, fallback=GREY) -> list:
    expr: list = ["match", ["get", field]]
    for value, color in pairs:
        expr += [value, color]
    expr.append(fallback)
    return expr


def step_expr(field: str, first: str, bands: list[tuple[float, str]]) -> list:
    expr: list = ["step", ["coalesce", ["get", field], 0], first]
    for threshold, color in bands:
        expr += [threshold, color]
    return expr


def counts(con, src: Path, field: str) -> list[tuple[str, int]]:
    rows = con.execute(
        f"SELECT coalesce({field}::VARCHAR, '(null)') AS v, count(*) AS n "
        f"FROM read_parquet('{src.as_posix()}') GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def band_counts(con, src: Path, field: str, edges: list[float]) -> list[int]:
    """How many rows fall in each band of a step expression."""
    cases = []
    for i, edge in enumerate(edges):
        lower = "" if i == 0 else f"{field} >= {edges[i - 1]} AND "
        cases.append(f"count(*) FILTER ({lower}{field} < {edge})")
    cases.append(f"count(*) FILTER ({field} >= {edges[-1]})")
    sql = (
        f"SELECT {', '.join(cases)} FROM read_parquet('{src.as_posix()}') "
        f"WHERE {field} IS NOT NULL"
    )
    return list(con.execute(sql).fetchone())


def prune_bands(
    edges: list[float], counts: list[int]
) -> tuple[list[float], list[int]]:
    """Drop every band nothing falls into.

    A legend class that no feature lands in is the most common visible defect
    in a new catalog: the browser prints the class, the map never paints it,
    and a reader concludes the data is missing. The bands are chosen as round
    numbers a human can read, so whether each one is populated depends on the
    level -- 60,815 local administrative units have a `min_zoom` of 12 or 13
    and **none** has 14 or more. So the edge that opens an empty band is
    removed and its colour goes with it, which merges the empty band into the
    one below. tests/test_styles.py re-measures and fails if one survives.
    """
    kept_edges: list[float] = []
    kept_counts: list[int] = [counts[0]]
    for edge, count in zip(edges, counts[1:]):
        if count == 0:
            continue
        kept_edges.append(edge)
        kept_counts.append(count)
    if kept_counts[0] == 0 and len(kept_counts) > 1:
        # The bottom band is empty too: the first edge becomes the floor.
        kept_edges = kept_edges[1:]
        kept_counts = kept_counts[1:]
    return kept_edges, kept_counts


def banded(
    con, src: Path, field: str, edges: list[float], colors: list[str]
) -> tuple[list, list[int], list[float]]:
    """A `step` expression over only the bands that have features in them."""
    counts = band_counts(con, src, field, edges)
    kept, kept_counts = prune_bands(edges, counts)
    if not kept:
        # Nothing to band on at all: one flat class, which still legends.
        return ["step", ["coalesce", ["get", field], 0], colors[0]], \
               kept_counts, kept
    expr = step_expr(
        field, colors[0],
        [(edge, colors[min(i + 1, len(colors) - 1)])
         for i, edge in enumerate(kept)],
    )
    return expr, kept_counts, kept


def build_boundary_styles(con, collection: str) -> None:
    src = boundary_path(collection)
    if not src.exists():
        sys.exit(f"missing {src}; run tools/build_boundaries.py first")
    ramp = PALETTE[collection]
    print(f"[{collection}]")

    # 1. Placetype. The default where a collection holds more than one, which
    #    is the first thing a reader wants to see: a level is a tier, and the
    #    tier can hold a unit and its own macro or micro variant.
    present = [
        (value, n) for value, n in counts(con, src, "placetype")
        if value in COLLECTIONS[collection]
    ]
    pairs = []
    shades = [ramp[4], ramp[2], ramp[0]]
    for i, (value, n) in enumerate(present):
        pairs.append((value, shades[min(i, len(shades) - 1)]))
        print(f"  placetype {value}: {n:,}")
    placetype_layers = [
        fill(collection, match_expr("placetype", pairs)), outline(collection)
    ]

    # 2. Geometry provenance. Unique to Who's On First and the single most
    #    useful thing a reader can see about it: `geom_src` is the per-record
    #    licensing and quality key, and it resolves to a license through
    #    whosonfirst-sources.
    #
    #    It is painted as the grouping defined in wofcommon.GEOM_SRC_GROUPS
    #    rather than raw, because raw it is long-tailed -- 66 distinct values
    #    at one level -- and because the grouping covers every row, so nothing
    #    lands in a fallback colour with no legend entry to explain it.
    group_counts = con.execute(
        f"SELECT {geom_src_group_sql()} AS g, count(*) AS n "
        f"FROM read_parquet('{src.as_posix()}') GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    shades = [ramp[5], ramp[3], ramp[1], ramp[4], ramp[2], ramp[0]]
    pairs = []
    for i, (value, n) in enumerate(group_counts):
        pairs.append((value, shades[i % len(shades)]))
        print(f"  geom_src_group {value}: {n:,}")
    provenance_layers = [
        fill(collection, match_expr("geom_src_group", pairs)),
        outline(collection),
    ]

    # 3. Population. WOF carries it where a source had one, which is far from
    #    everywhere, so the "no figure" class is real and is coloured grey.
    with_pop = con.execute(
        f"SELECT count(population), count(*) FROM "
        f"read_parquet('{src.as_posix()}')"
    ).fetchone()
    pop_expr, pop_bands, pop_kept = banded(
        con, src, "population", [1_000, 10_000, 100_000, 1_000_000], ramp[1:]
    )
    print(
        f"  population: {with_pop[0]:,} of {with_pop[1]:,} features carry one, "
        f"edges {pop_kept} bands {pop_bands}"
    )
    population_layers = [fill(collection, pop_expr), outline(collection)]

    # 4. Prominence. `min_zoom` is WOF's own answer to "how early should this
    #    place appear on a map", which is a better importance signal than area
    #    for a gazetteer and is not available in either sibling catalog.
    zoom_expr, zoom_bands, zoom_kept = banded(
        con, src, "min_zoom", [6, 9, 12, 14], list(reversed(ramp[1:])),
    )
    print(f"  min_zoom edges {zoom_kept} bands {zoom_bands}")
    prominence_layers = [fill(collection, zoom_expr), outline(collection)]

    # 5. Outline detail. How many coordinates a feature's outline has, which
    #    is the measurement behind this catalog's display files and shows a
    #    reader directly where the upstream geometry is detailed and where it
    #    was carried up from a coarser source.
    vertex_expr, vertex_bands, vertex_kept = banded(
        con, src, "vertices", [10, 100, 1_000, 10_000], ramp
    )
    print(f"  vertices edges {vertex_kept} bands {vertex_bands}")
    detail_layers = [fill(collection, vertex_expr), outline(collection)]

    chosen = [
        ("placetype", "Placetype", placetype_layers),
        ("geometry-source", "Who drew the outline", provenance_layers),
        ("population", "Population", population_layers),
        ("prominence", "How early it appears on a map", prominence_layers),
        ("outline-detail", "Coordinates per outline", detail_layers),
    ]
    # Which style leads. A legend whose classes exist but are invisible on the
    # map is as useless as an empty one, so `placetype` leads only where the
    # minority placetype is actually visible -- at least 1% of the collection.
    # Level 4 has 460 boroughs among 4,795,832 localities (0.01%) and level 5
    # has 3,396 macro- and microhoods among 397,416 (0.85%), so painting
    # placetype there would be a two-class legend over a map of one colour.
    # Those lead with prominence, which varies everywhere. A collection with
    # one placetype leads with provenance.
    minority = (
        min(n for _, n in present) / sum(n for _, n in present)
        if len(present) > 1 else 0.0
    )
    if len(present) == 1:
        default = "geometry-source"
    elif minority >= 0.01:
        default = "placetype"
    else:
        default = "prominence"
    print(f"  default style: {default} (minority placetype {minority:.2%})")
    for name, title, layers in chosen:
        style(collection, name, title, layers)
        if name == default:
            style(collection, "default", title, layers)


def build_names_styles(con) -> None:
    if not NAMES_PATH.exists():
        sys.exit(f"missing {NAMES_PATH}; run tools/build_names.py first")
    ramp = PALETTE["names"]
    print("[names]")

    dupe_expr, dupe_bands, dupe_kept = banded(
        con, NAMES_PATH, "name_dupes", [2, 6, 26, 101], ramp[1:]
    )
    print(f"  name_dupes edges {dupe_kept} bands {dupe_bands}")
    style(
        "names", "ambiguity", "How many places share this name",
        [circle("names", dupe_expr)],
    )

    # A `match` label has to be the same type as the column, or every branch
    # misses and the whole layer renders in the fallback colour while the
    # legend still lists every class. `level` is an int8 and `is_point` is a
    # boolean, so the labels here are ints and booleans, not strings.
    levels = sorted(
        int(v) for v, _ in counts(con, NAMES_PATH, "level") if v != "(null)"
    )
    print(f"  levels: {levels}")
    level_layers = [circle(
        "names",
        match_expr("level", [(i, ramp[min(i, 5)]) for i in levels]),
    )]
    style("names", "level", "Administrative level", level_layers)
    style("names", "default", "Administrative level", level_layers)

    lang_expr, lang_bands, lang_kept = banded(
        con, NAMES_PATH, "name_lang_count", [2, 4, 8, 16], ramp[1:]
    )
    print(f"  name_lang_count edges {lang_kept} bands {lang_bands}")
    style(
        "names", "languages", "Languages agreeing on this spelling",
        [circle("names", lang_expr)],
    )

    style(
        "names", "geometry-kind", "Point or polygon in the boundary file",
        [circle(
            "names",
            match_expr("is_point", [(True, ramp[2]), (False, ramp[5])]),
        )],
    )


def main() -> int:
    con = connect()
    try:
        for collection in COLLECTIONS:
            build_boundary_styles(con, collection)
        build_names_styles(con)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
