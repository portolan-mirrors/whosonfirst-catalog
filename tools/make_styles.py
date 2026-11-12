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


def match_expr(field: str, pairs: list[tuple[str, str]], fallback=GREY) -> list:
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
    src_counts = [
        (value, n) for value, n in counts(con, src, "geom_src")
        if value != "(null)"
    ][:5]
    pairs = [
        (value, ramp[5 - min(i, 4)]) for i, (value, n) in enumerate(src_counts)
    ]
    for value, n in src_counts:
        print(f"  geom_src {value}: {n:,}")
    provenance_layers = [
        fill(collection, match_expr("geom_src", pairs)), outline(collection)
    ]

    # 3. Population. WOF carries it where a source had one, which is far from
    #    everywhere, so the "no figure" class is real and is coloured grey.
    pop_edges = [1_000, 10_000, 100_000, 1_000_000]
    pop_bands = band_counts(con, src, "population", pop_edges)
    with_pop = con.execute(
        f"SELECT count(population), count(*) FROM "
        f"read_parquet('{src.as_posix()}')"
    ).fetchone()
    print(
        f"  population: {with_pop[0]:,} of {with_pop[1]:,} features carry one, "
        f"bands {pop_bands}"
    )
    population_layers = [
        fill(
            collection,
            step_expr(
                "population", ramp[1],
                [(edge, ramp[i + 2]) for i, edge in enumerate(pop_edges)],
            ),
        ),
        outline(collection),
    ]

    # 4. Prominence. `min_zoom` is WOF's own answer to "how early should this
    #    place appear on a map", which is a better importance signal than area
    #    for a gazetteer and is not available in either sibling catalog.
    zoom_edges = [6, 9, 12, 14]
    zoom_bands = band_counts(con, src, "min_zoom", zoom_edges)
    print(f"  min_zoom bands {zoom_edges}: {zoom_bands}")
    prominence_layers = [
        fill(
            collection,
            step_expr(
                "min_zoom", ramp[5],
                [(edge, ramp[4 - i]) for i, edge in enumerate(zoom_edges)],
            ),
        ),
        outline(collection),
    ]

    # 5. Outline detail. How many coordinates a feature's outline has, which
    #    is the measurement behind this catalog's display files and shows a
    #    reader directly where the upstream geometry is detailed and where it
    #    was carried up from a coarser source.
    vertex_edges = [10, 100, 1_000, 10_000]
    vertex_bands = band_counts(con, src, "vertices", vertex_edges)
    print(f"  vertices bands {vertex_edges}: {vertex_bands}")
    detail_layers = [
        fill(
            collection,
            step_expr(
                "vertices", ramp[0],
                [(edge, ramp[i + 1]) for i, edge in enumerate(vertex_edges)],
            ),
        ),
        outline(collection),
    ]

    chosen = [
        ("placetype", "Placetype", placetype_layers),
        ("geometry-source", "Where the outline came from", provenance_layers),
        ("population", "Population", population_layers),
        ("prominence", "How early it appears on a map", prominence_layers),
        ("outline-detail", "Coordinates per outline", detail_layers),
    ]
    # One placetype means a one-class legend, which says nothing; that
    # collection leads with provenance instead.
    default = "placetype" if len(present) > 1 else "geometry-source"
    for name, title, layers in chosen:
        style(collection, name, title, layers)
        if name == default:
            style(collection, "default", title, layers)


def build_names_styles(con) -> None:
    if not NAMES_PATH.exists():
        sys.exit(f"missing {NAMES_PATH}; run tools/build_names.py first")
    ramp = PALETTE["names"]
    print("[names]")

    dupe_edges = [2, 6, 26, 101]
    dupe_bands = band_counts(con, NAMES_PATH, "name_dupes", dupe_edges)
    print(f"  name_dupes bands {dupe_edges}: {dupe_bands}")
    style(
        "names", "ambiguity", "How many places share this name",
        [circle(
            "names",
            step_expr(
                "name_dupes", ramp[1],
                [(edge, ramp[i + 2]) for i, edge in enumerate(dupe_edges)],
            ),
        )],
    )

    level_counts = counts(con, NAMES_PATH, "level")
    print(f"  levels: {level_counts}")
    style(
        "names", "level", "Administrative level",
        [circle(
            "names",
            match_expr(
                "level",
                [(str(i), ramp[min(i, 5)]) for i in range(6)],
            ),
        )],
    )
    style("names", "default", "Administrative level",
          [circle(
              "names",
              match_expr(
                  "level", [(str(i), ramp[min(i, 5)]) for i in range(6)]
              ),
          )])

    lang_edges = [2, 4, 8, 16]
    lang_bands = band_counts(con, NAMES_PATH, "name_lang_count", lang_edges)
    print(f"  name_lang_count bands {lang_edges}: {lang_bands}")
    style(
        "names", "languages", "Languages agreeing on this spelling",
        [circle(
            "names",
            step_expr(
                "name_lang_count", ramp[1],
                [(edge, ramp[i + 2]) for i, edge in enumerate(lang_edges)],
            ),
        )],
    )

    style(
        "names", "geometry-kind", "Point or polygon in the boundary file",
        [circle(
            "names",
            match_expr("is_point", [("true", ramp[2]), ("false", ramp[5])]),
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
