#!/usr/bin/env python3
"""Render each collection's thumbnail from its own default style.

    python3 tools/make_thumbnails.py            # all seven
    python3 tools/make_thumbnails.py locality   # one

The canonical way to build a Portolan thumbnail is to render
`styles/default.json` server-side with chiitiler, through MapLibre GL Native.
That needs a clone of chiitiler, which was not available in the environment
this catalog was built in, so this script renders the same style's colours
from the GeoParquet instead: it parses the `step` or `match` expression out of
`styles/default.json` and colours every feature by it. The image a reader sees
therefore agrees with the legend the browser derives from the same expression,
which is the property that matters. It is not a MapLibre render: there is no
basemap, and line widths are matplotlib's.

Framing. Each image is 3:2, matching the browser card. Seven world maps in a
card grid would be seven indistinguishable cards, so only the country level is
framed to the full extent and the others are framed on a region that shows
what that level actually looks like. The window for each is in WINDOWS below,
and each was chosen by eye from the rendered image, which is the only way to
choose a frame.

Levels 4 and 5 are mostly points, so their frames are tighter: a world view of
4.8 million markers is a grey smear. The `names` frame is tighter still,
because that collection is one point per place *and* per alternative spelling.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from wofcommon import (  # noqa: E402
    COLLECTION_LEVEL,
    DISPLAY_LEVELS,
    GEOM_SRC_GROUPS,
    NAMES_PATH,
    boundary_path,
    display_path,
)

# A style field that no published file carries, and the column it is derived
# from. `geom_src_group` is materialized into the PMTiles by
# tools/build_pmtiles.py from one definition in tools/wofcommon.py; this is
# the same definition applied in Python, so the thumbnail shows the classes
# the legend lists.
_GROUP_OF = {
    prefix: name
    for name, (_, prefixes) in GEOM_SRC_GROUPS.items()
    for prefix in prefixes
}
DERIVED = {
    "geom_src_group": (
        "geom_src",
        lambda v: "unknown" if not v else _GROUP_OF.get(v, "official"),
    )
}

CATALOG = Path(__file__).resolve().parents[1] / "catalog"

WINDOWS: dict[str, dict] = {
    "country": {
        "window": (-180.0, -90.0, 180.0, 90.0), "aspect": 2.0,
        "simplify": 0.05, "edge": 0.15,
        "label": "the whole world, the only full-extent frame",
    },
    "region": {
        "window": (-82.0, -56.0, -34.0, 13.0), "aspect": 1.5,
        "simplify": 0.01, "edge": 0.15,
        "label": "South America",
    },
    "county": {
        "window": (-11.0, 35.0, 31.0, 61.0), "aspect": 1.5,
        "simplify": 0.004, "edge": 0.08,
        "label": "Europe",
    },
    "localadmin": {
        "window": (-10.0, 36.0, 12.0, 52.0), "aspect": 1.5,
        "simplify": 0.002, "edge": 0.05,
        "label": "France and Iberia, where localadmin coverage is densest",
    },
    "locality": {
        "window": (-11.0, 49.5, 3.0, 59.0), "aspect": 1.5,
        "simplify": 0.0, "edge": 0.0, "markersize": 0.9, "alpha": 0.75,
        "label": "Britain and Ireland, where the towns still separate",
    },
    "neighbourhood": {
        "window": (-125.0, 25.0, -67.0, 50.0), "aspect": 1.5,
        "simplify": 0.0, "edge": 0.0, "markersize": 1.0, "alpha": 0.8,
        "label": "the contiguous United States",
    },
    "names": {
        "window": (122.0, 29.0, 148.0, 46.0), "aspect": 1.5,
        "simplify": 0.0, "edge": 0.0, "markersize": 0.6, "alpha": 0.6,
        "label": "Japan and Korea",
    },
}

WATER = "#eef1f3"
WIDTH_PX = 1200
DPI = 100


def eval_step(expr: list, value) -> str:
    fallback = expr[2]
    if value is None:
        return fallback
    colour = fallback
    for i in range(3, len(expr), 2):
        if value >= expr[i]:
            colour = expr[i + 1]
        else:
            break
    return colour


def eval_match(expr: list, value) -> str:
    pairs = expr[2:-1]
    for i in range(0, len(pairs), 2):
        if pairs[i] == value:
            return pairs[i + 1]
    return expr[-1]


def style_colours(style_path: Path):
    """The field, the colour function, and the layer kind of a default style."""
    style = json.loads(style_path.read_text())
    layer = next(
        layer for layer in style["layers"]
        if layer["type"] in {"fill", "circle"}
    )
    key = "fill-color" if layer["type"] == "fill" else "circle-color"
    expr = layer["paint"][key]
    getter = expr[1]
    field = getter[1][1] if getter[0] == "coalesce" else getter[1]
    if expr[0] == "step":
        return field, (lambda v: eval_step(expr, v)), layer["type"]
    if expr[0] == "match":
        return field, (lambda v: eval_match(expr, v)), layer["type"]
    raise SystemExit(f"{style_path}: default style is neither step nor match")


def frame(bounds, window, target: float):
    west, south, east, north = window or bounds
    cx, cy = (west + east) / 2, (south + north) / 2
    width, height = east - west, north - south
    if width / height < target:
        width = height * target
    else:
        height = width / target
    return (cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)


def source_for(name: str, field: str) -> Path:
    """The lightest published file that carries the field being painted.

    The display companion is the same rows with lighter geometry, so it is
    both faster to read and the thing a reader would actually be shown — but
    it carries only the columns that identify a row, so a style painting an
    attribute has to come from the full file instead.
    """
    if name == "names":
        return NAMES_PATH
    disp = display_path(name)
    if COLLECTION_LEVEL[name] in DISPLAY_LEVELS and disp.exists():
        import pyarrow.parquet as pq

        if field in {f.name for f in pq.ParquetFile(disp).schema_arrow}:
            return disp
    return boundary_path(name)


def render(name: str) -> None:
    spec = WINDOWS[name]
    field, colour_of, kind = style_colours(
        CATALOG / name / "styles" / "default.json"
    )
    derive = None
    if field in DERIVED:
        field, derive = DERIVED[field]
    src = source_for(name, field)
    if not src.exists():
        sys.exit(f"missing {src}; run the build tools first")

    west, south, east, north = frame(None, spec["window"], spec["aspect"])
    # The GeoParquet carries a `covering` bbox, so geopandas prunes row groups
    # spatially instead of reading 1.4 GiB to draw one region. That is the same
    # property this catalog's files exist to give a browser.
    try:
        gdf = gpd.read_parquet(
            src, columns=[field, "geometry"],
            bbox=(west, south, east, north),
        )
    except (TypeError, ValueError):
        gdf = gpd.read_parquet(src, columns=[field, "geometry"])
        gdf = gdf.cx[west:east, south:north]
    if spec["simplify"]:
        gdf = gdf.set_geometry(gdf.geometry.simplify(spec["simplify"]))
    values = gdf[field]
    if derive is not None:
        values = [derive(v) for v in values]
    colours = [colour_of(v) for v in values]

    height_px = int(WIDTH_PX / spec["aspect"])
    fig, ax = plt.subplots(
        figsize=(WIDTH_PX / DPI, height_px / DPI), dpi=DPI
    )
    fig.patch.set_facecolor(WATER)
    if kind == "fill":
        gdf.plot(ax=ax, color=colours, linewidth=spec["edge"],
                 edgecolor="#2b2b2b", antialiased=True)
    else:
        gdf.plot(ax=ax, color=colours,
                 markersize=spec.get("markersize", 2.2),
                 linewidth=0, alpha=spec.get("alpha", 0.9))
    ax.set_facecolor(WATER)
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect("auto")
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    out = CATALOG / name / f"{name}.thumb.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=fig.get_facecolor(), pad_inches=0)
    plt.close(fig)
    print(
        f"  {out.relative_to(CATALOG.parent)}: {out.stat().st_size:,} bytes, "
        f"{len(gdf):,} features coloured by {field}, {spec['label']}, "
        f"bbox {west:.1f},{south:.1f},{east:.1f},{north:.1f}"
    )


def main(argv: list[str]) -> int:
    for name in argv or list(WINDOWS):
        if name not in WINDOWS:
            sys.exit(f"unknown collection {name}")
        render(name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
