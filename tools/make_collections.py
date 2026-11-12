#!/usr/bin/env python3
"""Generate every collection.json from the built files.

    python3 tools/make_collections.py

Run the boundary, display, names, PMTiles, style and thumbnail steps first.
Row counts, sizes, checksums, row group counts and extents are read off the
files rather than written by hand, so a collection cannot claim a number the
data does not have. The column descriptions come from `tools/columns.py`,
which is their one canonical home.

Assets, and the rule that decides which is which
------------------------------------------------
Every collection carries both: geocode.earth's own files, linked at their
original URLs with the size and digest their inventory records, and the files
this catalog builds. The `source` role marks the former. A reader who wants
the authoritative original never has to leave the catalog to find it, and a
reader checking this catalog's work can see exactly what it started from.

A file is built here only where a measurement says the upstream one cannot do
the job, and the asset's own `description` carries that measurement. See
`docs/upstream-measurements.md`.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyarrow.parquet as pq  # noqa: E402

from columns import BOUNDARY_COLUMNS, INDEX_COLUMNS, as_table_columns  # noqa: E402
from wofcommon import (  # noqa: E402
    CATALOG_VERSION,
    COLLECTIONS,
    COLLECTION_LEVEL,
    DISPLAY_LEVELS,
    DOWNLOAD_PAGE,
    EXTRACTION_DATE,
    LICENSE_LINKS,
    NAMES_PATH,
    NAME_LANGS,
    PLACETYPE_LEVEL,
    ROW_GROUP_ROWS,
    SIMPLIFY_SHARE,
    SIMPLIFY_TOLERANCE,
    STAC_LICENSE,
    UPSTREAM_ASSETS,
    UPSTREAM_PARQUET,
    UPSTREAM_PARQUET_BUILT,
    WOF_LICENSE_PAGE,
    WOF_PLACETYPES_PAGE,
    boundary_path,
    display_path,
    human,
    multihash_sha256,
    pmtiles_path,
)

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "catalog"

PORTOLAN_SCHEMA = "https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json"
EXTENSIONS = [
    PORTOLAN_SCHEMA,
    "https://stac-extensions.github.io/table/v1.2.0/schema.json",
    "https://stac-extensions.github.io/file/v2.1.0/schema.json",
    "https://stac-extensions.github.io/web-map-links/v1.3.0/schema.json",
]

CATALOG_TITLE = "Who's On First: a Cloud-Native Gazetteer"

TITLES = {
    "country": "Who's On First Countries, Dependencies and Disputed Areas",
    "region": "Who's On First Regions and Macroregions",
    "county": "Who's On First Counties and Macrocounties",
    "localadmin": "Who's On First Local Administrative Units",
    "locality": "Who's On First Localities and Boroughs",
    "neighbourhood": "Who's On First Neighbourhoods, Macrohoods and Microhoods",
    "names": "Who's On First Gazetteer Name Index",
}

BLURB = {
    "country": "The top of the ladder: 213 countries, 40 dependencies and "
               "100 disputed areas.",
    "region": "First-order subdivisions — states, provinces, regions — plus "
              "the macroregions that bundle them, which exist mostly in "
              "Europe.",
    "county": "Second-order subdivisions, and the macrocounties above them.",
    "localadmin": "WOF's placetype for \"in many countries, the lowest level "
                  "of government\", the unit that contains localities which "
                  "themselves have no authority.",
    "locality": "Towns and cities of any size, plus boroughs — \"a local "
                "government unit, below the locality placetype. Think "
                "Brooklyn.\"",
    "neighbourhood": "Neighbourhoods, the macrohoods that bundle them and the "
                     "microhoods inside them. \"One thing is certain — "
                     "neighbourhoods are things no one will completely agree "
                     "on. Ever.\"",
}

PROVIDERS = [
    {
        "name": "Who's On First",
        "description": (
            "Produces the gazetteer. A community project, originally from "
            "Mapzen, that assembles place records from over 300 open data "
            "sources with a stable numeric identifier, a placetype hierarchy "
            "and names in hundreds of languages, and publishes the per-record "
            "geometry provenance that makes its licensing checkable."
        ),
        "roles": ["producer", "licensor"],
        "url": "https://whosonfirst.org/",
    },
    {
        "name": "geocode.earth",
        "description": (
            "Builds and hosts the distributions. Who's On First lives as 260 "
            "GitHub repositories of GeoJSON; geocode.earth compiles them into "
            "combined GeoParquet, SQLite, SpatiaLite, GeoJSON-bundle and "
            "PMTiles files and serves them over HTTPS with range requests and "
            "permissive CORS, which is what makes this a metadata-first "
            "catalog rather than a copy. whosonfirst.org's own download page "
            "points here. (The Portolan `host` role names the organization "
            "serving *this catalog's* files, so it sits on Portolan Mirrors; "
            "geocode.earth hosts the upstream assets linked from every "
            "collection.)"
        ),
        "roles": ["processor"],
        "url": DOWNLOAD_PAGE,
    },
    {
        "name": "Portolan Mirrors",
        "description": (
            "Describes geocode.earth's distribution as a Portolan catalog and "
            "adds the three things a browser client cannot get from it: one "
            "GeoParquet per administrative level with small row groups, a "
            "display-simplified companion for the polygon-heavy levels, and a "
            "name index sorted for prefix search. Links to the upstream files "
            "rather than copying them wherever they already do the job. Adds "
            "no places and changes no attribute value."
        ),
        "roles": ["processor", "host"],
        "url": "https://github.com/portolan-mirrors/whosonfirst-catalog",
    },
]

KEYWORDS = [
    "gazetteer", "place names", "administrative boundaries",
    "Who's On First", "WOF", "multilingual", "GeoParquet", "PMTiles",
]

SIBLING_LINKS = [
    {
        "rel": "related",
        "href": "https://source.coop/portolan-mirrors/geoboundaries-catalog",
        "type": "text/html",
        "title": "geoBoundaries CGAZ, a CC-BY-4.0 sibling gazetteer catalog",
    },
    {
        "rel": "related",
        "href": "https://source.coop/portolan-mirrors/cn-gazetteer-overture",
        "type": "text/html",
        "title": "Overture divisions, an ODbL sibling gazetteer catalog",
    },
]


def multihash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 << 20), b""):
            digest.update(chunk)
    return "1220" + digest.hexdigest()


def file_asset(path: Path, href: str, **extra) -> dict:
    asset = {
        "href": href,
        "file:size": path.stat().st_size,
        "file:checksum": multihash(path),
    }
    asset.update(extra)
    return asset


def upstream_assets() -> dict:
    out = {}
    for spec in UPSTREAM_ASSETS:
        asset = {
            "href": spec["url"],
            "type": spec["media_type"],
            "title": spec["title"],
            "roles": spec["roles"],
        }
        if "size" in spec:
            asset["file:size"] = spec["size"]
        if "sha256" in spec:
            asset["file:checksum"] = multihash_sha256(spec["sha256"])
        if spec.get("mutable"):
            asset["description"] = (
                "No `file:size` or `file:checksum`, deliberately: this is "
                "geocode.earth's live index, which gains an entry every time "
                "a country is rebuilt. Pinning a digest to a file whose whole "
                "job is to change would be a promise this catalog cannot "
                "keep. It is also the authoritative record of what vintage "
                "every upstream file is, which no URL carries."
            )
        if "built" in spec:
            asset["description"] = (
                f"geocode.earth built this on {spec['built']}. There are no "
                "versioned URLs: every file is named `-latest` and is "
                "overwritten in place, so the date and the digest come from "
                "their inventory rather than from the URL. The HTTP "
                "`Last-Modified` header on every object under `/wof/dist/` "
                "reads 2025-10-30 because the bucket was re-copied then, and "
                "is not a vintage signal."
            )
        out[spec["key"]] = asset
    return out


def style_assets(collection: str) -> dict:
    out = {}
    folder = CATALOG / collection / "styles"
    for path in sorted(folder.glob("*.json")):
        doc = json.loads(path.read_text())
        roles = ["style"]
        if path.stem == "default":
            roles.append("default")
        out[f"style-{path.stem}"] = file_asset(
            path,
            f"./styles/{path.name}",
            type="application/vnd.mapbox.style+json",
            title=doc.get("name", path.stem),
            roles=roles,
        )
    return out


def thumbnail_asset(collection: str, title: str) -> dict:
    path = CATALOG / collection / f"{collection}.thumb.png"
    if not path.exists():
        return {}
    return {
        "thumbnail": file_asset(
            path,
            f"./{collection}.thumb.png",
            type="image/png",
            title=f"{title}, rendered from the default style",
            roles=["thumbnail"],
        )
    }


def extent(path: Path, bbox_column: str = "bbox") -> list[float]:
    """The collection's spatial extent, from the file itself.

    Preferred source is the `bbox` covering column's row group statistics.
    The gazetteer index writes statistics for only the four columns a client
    prunes on, so `bbox` has none there; its GeoParquet `geo` metadata
    carries the declared extent instead, which the build computed before
    narrowing the statistics.
    """
    reader = pq.ParquetFile(path)
    md = reader.metadata
    found = {f"{bbox_column}.{k}": [] for k in ("xmin", "ymin", "xmax", "ymax")}
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        for i in range(rg.num_columns):
            col = rg.column(i)
            if col.path_in_schema in found and col.statistics is not None:
                found[col.path_in_schema].append(
                    (col.statistics.min, col.statistics.max)
                )
    if all(found.values()):
        return [
            min(lo for lo, _ in found[f"{bbox_column}.xmin"]),
            min(lo for lo, _ in found[f"{bbox_column}.ymin"]),
            max(hi for _, hi in found[f"{bbox_column}.xmax"]),
            max(hi for _, hi in found[f"{bbox_column}.ymax"]),
        ]
    geo = (reader.schema_arrow.metadata or {}).get(b"geo")
    if geo is None:
        sys.exit(
            f"{path.name}: no bbox statistics and no GeoParquet metadata; "
            "cannot determine the extent"
        )
    doc = json.loads(geo)
    column = doc["primary_column"]
    return list(doc["columns"][column]["bbox"])


def base(collection: str, title: str, description: str, bbox: list[float],
         rows: int, extra_links: list[dict]) -> dict:
    return {
        "type": "Collection",
        "stac_version": "1.1.0",
        "stac_extensions": list(EXTENSIONS),
        "id": collection,
        "title": title,
        "description": description,
        "license": STAC_LICENSE,
        "keywords": list(KEYWORDS),
        "providers": [dict(p) for p in PROVIDERS],
        "extent": {
            "spatial": {"bbox": [[round(v, 6) for v in bbox]]},
            "temporal": {
                "interval": [[f"{UPSTREAM_PARQUET_BUILT[:10]}T00:00:00Z",
                              f"{UPSTREAM_PARQUET_BUILT[:10]}T00:00:00Z"]]
            },
        },
        "updated": f"{EXTRACTION_DATE}T00:00:00Z",
        "table:primary_geometry": "geometry",
        "table:row_count": rows,
        "links": structural_links(collection, title) + extra_links,
    }


def structural_links(collection: str, title: str) -> list[dict]:
    links = [
        {"rel": "root", "href": "../catalog.json",
         "type": "application/json", "title": CATALOG_TITLE},
        {"rel": "parent", "href": "../catalog.json",
         "type": "application/json", "title": CATALOG_TITLE},
        {"rel": "describedby", "href": "./README.md",
         "type": "text/markdown", "title": "Collection README"},
        {"rel": "agents", "href": "./AGENTS.md",
         "type": "text/markdown", "title": "Collection agent guide"},
        {"rel": "via", "href": DOWNLOAD_PAGE, "type": "text/html",
         "title": "geocode.earth combined Who's On First downloads "
                  "(upstream source)"},
        {"rel": "describedby", "href": WOF_PLACETYPES_PAGE,
         "type": "text/html",
         "title": "Who's On First placetypes, the project's own definitions"},
        {"rel": "cite-as", "href": "https://whosonfirst.org/",
         "type": "text/html", "title": "Who's On First"},
    ]
    for href, label in LICENSE_LINKS:
        links.append({"rel": "license", "href": href, "type": "text/html",
                      "title": label})
    links += [dict(link) for link in SIBLING_LINKS]
    for other in list(COLLECTIONS) + ["names"]:
        if other == collection:
            continue
        links.append({
            "rel": "related",
            "href": f"../{other}/collection.json",
            "type": "application/json",
            "title": TITLES[other],
        })
    pm = pmtiles_path(collection)
    if pm.exists():
        links.append({
            "rel": "pmtiles",
            "href": f"./{pm.name}",
            "type": "application/vnd.pmtiles",
            "title": f"{TITLES[collection]}, vector tiles",
            "pmtiles:layers": [collection],
        })
    return links


UPSTREAM_COST = (
    "geocode.earth's combined file is the right thing to read for a scan, an "
    "export or a spatial query, and this collection links straight to it. It "
    "is the wrong thing to read for **one** place: it has 83 row groups of "
    "65,536 rows, no declared sort, and 89% of its bytes in the geometry "
    "column, so one row group's geometry chunk is a median of 38 MiB and as "
    "much as 285 MiB — which is what any row-group-granular reader, including "
    "the hyparquet a browser uses, pays to decode a single row. Filtering to "
    "one placetype prunes nothing either, because `placetype` statistics span "
    "most of the alphabet in most row groups."
)


def boundary_collection(collection: str) -> dict:
    level = COLLECTION_LEVEL[collection]
    full = boundary_path(collection)
    md = pq.ParquetFile(full).metadata
    bbox = extent(full)
    title = TITLES[collection]
    placetypes = ", ".join(f"`{p}`" for p in COLLECTIONS[collection])

    description = (
        f"**Level {level} of this catalog's administrative ladder: "
        f"{placetypes}.** {BLURB[collection]}\n\n"
        f"{md.num_rows:,} features from Who's On First, the open gazetteer, as "
        "geocode.earth's combined admin distribution publishes it. This is "
        "place-name and boundary lookup, not address geocoding: there is no "
        "street or house number anywhere in Who's On First's admin "
        "distribution.\n\n"
        f"The GeoParquet here is **this catalog's own optimized copy**: the "
        f"same {md.num_rows:,} features, sorted by `(country, wof_id)` with "
        f"the sort declared, in {md.num_row_groups:,} exactly-full row groups "
        f"of {ROW_GROUP_ROWS[collection]} "
        f"({human(full.stat().st_size / md.num_row_groups)} each), zstd "
        "compressed, with a Parquet page index and a GeoParquet 1.1 "
        f"`covering` bbox. {UPSTREAM_COST}\n\n"
        "Both files are assets of this collection, and the asset descriptions "
        "say which to use when. The [agent guide](AGENTS.md) has the join "
        "keys, the traps and queries that run.\n\n"
        "**The license is a mix, and this catalog does not pretend "
        f"otherwise.** Who's On First scopes CC0 to \"the format and "
        "structure that allows Who's On First to operate\" and the records "
        "inherit terms from over 300 sources, so the `license` field is "
        f"`other` with links to [the per-source list]({WOF_LICENSE_PAGE}). "
        "Measured on this distribution's own `geom_src` column, 70.88% of the "
        "geometry is GeoNames under CC BY, 2.58% is CC0, and 14 records out "
        "of 5,423,663 are share-alike. Attribution is required: *Data from "
        f"Who's On First. [License]({WOF_LICENSE_PAGE}).*"
    )

    assets = {
        "data": file_asset(
            full, f"./{full.name}",
            type="application/vnd.apache.parquet",
            title=(
                f"{title}, full-resolution GeoParquet 1.1 "
                f"({md.num_row_groups:,} row groups of "
                f"{ROW_GROUP_ROWS[collection]}, zstd, page index, sorted by "
                "country and wof_id)"
            ),
            roles=["data"],
            description=(
                "Read this to clip, measure, export or analyse one place or a "
                "few. One row group is "
                f"{human(full.stat().st_size / md.num_row_groups)}, against "
                "a median of 38 MiB from the upstream combined file. The "
                "geometry is byte-identical to upstream except for the rows "
                "`geometry_repaired` flags."
            ),
            **{"table:primary_geometry": "geometry"},
        ),
    }

    disp = display_path(collection)
    if level in DISPLAY_LEVELS and disp.exists():
        assets["display"] = file_asset(
            disp, f"./{disp.name}",
            type="application/vnd.apache.parquet",
            title=f"{title}, display-simplified GeoParquet 1.1",
            roles=["data", "visual", "overview"],
            description=(
                "The same rows in the same order and the same row groups as "
                "the full file, simplified with "
                "`ST_SimplifyPreserveTopology` and then buffered **outward** "
                "by the same amount, so the shape always contains the true "
                "boundary rather than cutting corners off it. The tolerance "
                f"is per feature: {SIMPLIFY_SHARE:.1%} of that feature's own "
                "bounding-box diagonal, capped at "
                f"{SIMPLIFY_TOLERANCE[collection]} degrees. Point geometries "
                "are carried through untouched, because buffering a point "
                "would turn a marker into a circle. "
                f"{100 * disp.stat().st_size / full.stat().st_size:.1f}% of "
                "the full-resolution file. Draw it and filter with it; "
                "measure and clip with the full-resolution file."
            ),
            **{"table:primary_geometry": "geometry"},
        )

    pm = pmtiles_path(collection)
    if pm.exists():
        assets["pmtiles"] = file_asset(
            pm, f"./{pm.name}",
            type="application/vnd.pmtiles",
            title=f"{title}, vector tiles",
            roles=["visual", "data"],
            description=(
                "Capped at 400 KB per tile, so a first view opens. "
                "geocode.earth's own combined archive is linked below and "
                "carries all 21 placetypes in one file, but it is built with "
                "`--no-tile-size-limit` and its whole-world tile is "
                "15,671,392 bytes."
            ),
            **{"pmtiles:layers": [collection]},
        )

    assets.update(upstream_assets())
    assets.update(style_assets(collection))
    assets.update(thumbnail_asset(collection, title))

    doc = base(collection, title, description, bbox, md.num_rows, [])
    doc["assets"] = assets
    doc["table:columns"] = as_table_columns(
        [c for c in BOUNDARY_COLUMNS if c[0] in present_columns(full)]
    )
    doc["portolan:level"] = level
    return doc


def present_columns(path: Path) -> set[str]:
    return {f.name for f in pq.ParquetFile(path).schema_arrow}


def names_collection() -> dict:
    md = pq.ParquetFile(NAMES_PATH).metadata
    bbox = extent(NAMES_PATH)
    title = TITLES["names"]
    manifest = json.loads((CATALOG / "names" / "index.json").read_text())

    description = (
        "**The gazetteer index: a name search sidecar, not a boundary "
        f"dataset.** {manifest['primary_rows']:,} places plus "
        f"{manifest['alt_rows']:,} alternative spellings of their names, "
        f"{md.num_rows:,} rows in all, sorted by a folded form of the name so "
        "that a static client with no server can turn a typed name into a "
        "Who's On First identifier, a bounding box and a point.\n\n"
        "**The sort is the whole design.** Row group statistics on "
        "`name_norm` are tight, non-overlapping alphabetical ranges, the "
        "footer declares the sort, and the Parquet page index is written, so a "
        "typed prefix resolves from one or two row groups rather than a "
        f"download. The manifest at [index.json](index.json) is about "
        f"{len(json.dumps(manifest)) // 1000} KB and carries the index's "
        "exact size, row group count and checksum, the `catalog_version` the "
        "boundary files are pinned to, and the attribution a client has to "
        "show. Fetch it first.\n\n"
        "Every row carries what a result list needs without a second fetch: "
        "the display spelling, the level, the country, the parent's name, the "
        "population where WOF has one, WOF's own `min_zoom` prominence "
        "signal, a bbox to fly to, a point to pin, and an advisory "
        "`geometry_ref` that turns the geometry fetch into a single range "
        "read.\n\n"
        f"**Multilingual, within a limit worth knowing.** The alternative "
        f"spellings come from the {len(NAME_LANGS)} language columns "
        "geocode.earth's GeoParquet build carries. Who's On First itself "
        "carries names in hundreds of languages — one San Francisco record "
        "has 214 `name:*` properties — but those live in the SQLite and "
        "GeoJSON distributions, so this index cannot be richer than "
        f"{len(NAME_LANGS)} languages however multilingual WOF is. Both "
        "distributions are assets of this collection.\n\n"
        "This is place-name lookup, not address geocoding. The "
        "[agent guide](AGENTS.md) has the prefix-lookup recipe and the join "
        "back to geometry."
    )

    assets = {
        "data": file_asset(
            NAMES_PATH, f"./{NAMES_PATH.name}",
            type="application/vnd.apache.parquet",
            title=(
                f"{title}, GeoParquet 1.1 ({md.num_row_groups:,} row groups "
                f"of {manifest['index']['row_group_rows']}, zstd, page index, "
                "sorted by name_norm)"
            ),
            roles=["data"],
            description=(
                "One row per place plus one per distinct alternative "
                "spelling. The geometry column is one point per row, from the "
                "place's centroid: a marker, not a shape."
            ),
            **{"table:primary_geometry": "geometry"},
        ),
        "manifest": file_asset(
            CATALOG / "names" / "index.json", "./index.json",
            type="application/json",
            title="Index manifest: fetch this before the index",
            roles=["metadata"],
            description=(
                "The index's size, row group count, checksum and footer size, "
                "every boundary file's URL and row count, the "
                "`catalog_version` all of them are pinned to, and the "
                "attribution a client must display."
            ),
        ),
    }
    pm = pmtiles_path("names")
    if pm.exists():
        assets["pmtiles"] = file_asset(
            pm, f"./{pm.name}",
            type="application/vnd.pmtiles",
            title=f"{title}, vector tiles to zoom 8",
            roles=["visual", "data"],
            **{"pmtiles:layers": ["names"]},
        )
    assets.update(upstream_assets())
    assets.update(style_assets("names"))
    assets.update(thumbnail_asset("names", title))

    doc = base("names", title, description, bbox, md.num_rows, [])
    doc["assets"] = assets
    doc["table:columns"] = as_table_columns(
        [c for c in INDEX_COLUMNS if c[0] in present_columns(NAMES_PATH)]
    )
    doc["portolan:levels"] = manifest["levels"]
    return doc


def main() -> int:
    missing = [
        c for c in COLLECTIONS if not boundary_path(c).exists()
    ]
    if missing:
        sys.exit(
            f"missing boundary files for {', '.join(missing)}; "
            "run tools/build_boundaries.py first"
        )
    if not NAMES_PATH.exists():
        sys.exit(f"missing {NAMES_PATH}; run tools/build_names.py first")

    for collection in COLLECTIONS:
        doc = boundary_collection(collection)
        write(collection, doc)
    write("names", names_collection())
    print(f"catalog_version: {CATALOG_VERSION}")
    print(f"placetypes carried: {len(PLACETYPE_LEVEL)}")
    print(f"upstream: {UPSTREAM_PARQUET}")
    return 0


def write(collection: str, doc: dict) -> None:
    out = CATALOG / collection / "collection.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(
        f"  {out.relative_to(REPO)}  {doc['table:row_count']:,} rows, "
        f"{len(doc['table:columns'])} columns, {len(doc['assets'])} assets"
    )


if __name__ == "__main__":
    sys.exit(main())
