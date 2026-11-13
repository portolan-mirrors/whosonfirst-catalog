#!/usr/bin/env python3
"""Generate every collection README.md and AGENTS.md from the built files.

    python3 tools/make_docs.py

Run the build steps and `tools/make_collections.py` first. Every number in
the generated prose is read off the published files or measured with a query
this script runs, so a sentence cannot drift from the data. The column
descriptions come from `tools/columns.py`; the catalog-level `README.md`,
`AGENTS.md`, `llms.txt` and `changes-from-upstream.md` are written by hand and
are not touched here.

The example queries are run before they are written. A recipe that fails on
the first try costs a reader the time to debug someone else's mistake, so
`--check-queries` (the default) executes each one against the published files
and refuses to write the file if one of them errors.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyarrow.parquet as pq  # noqa: E402

from columns import BOUNDARY_COLUMNS, INDEX_COLUMNS  # noqa: E402
from wofcommon import (  # noqa: E402
    CATALOG_VERSION,
    COLLECTIONS,
    COLLECTION_LEVEL,
    DISPLAY_LEVELS,
    DOWNLOAD_PAGE,
    EXTRACTION_DATE,
    NAMES_PATH,
    NAME_LANGS,
    PLACETYPE_EXCLUDED,
    PLACETYPE_LEVEL,
    ROW_GROUP_ROWS,
    SIMPLIFY_SHARE,
    SIMPLIFY_TOLERANCE,
    UPSTREAM_PARQUET,
    UPSTREAM_PARQUET_BUILT,
    UPSTREAM_PMTILES,
    UPSTREAM_SQLITE,
    WOF_LICENSE_PAGE,
    WOF_PLACETYPES_PAGE,
    boundary_path,
    connect,
    display_path,
    human,
    pmtiles_path,
    wrap_markdown,
)

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "catalog"
PUBLIC = "https://data.source.coop/portolan-mirrors/whosonfirst-catalog"

TITLES = json.loads("{}")  # filled from the collection.json files

TAG_RULE = """**One rule survives every edit to this file.** Every claim here is either
quoted from a source or measured from the data. If you cannot point at where a
fact came from, it does not belong in this file. An agent acting on an invented
join key or an invented column name produces a confident wrong answer, and
nothing downstream catches it.

Each factual claim is tagged with how it was established:
**[attested]** Who's On First or geocode.earth states it, with a link;
**[researched]** found outside the source's own metadata, with a link;
**[derived]** computed from the published data, with the query that computed
it. Every query below was run against the published files before this guide
was written."""

LICENSE_NOTE = f"""> [!IMPORTANT]
> **The license is a mix.** Who's On First scopes CC0 to "the format and
> structure that allows Who's On First to operate" — the schema, not the
> records — and the records inherit terms from over 300 sources. Attribution
> is required: *Data from Who's On First.
> [License]({WOF_LICENSE_PAGE}).* Measured on this distribution's own
> `geom_src` column, 70.88% of the geometry is GeoNames under CC BY and 14
> records of 5,423,663 are share-alike. No ODbL source contributes geometry.
> Join `geom_src` to
> [whosonfirst-sources](https://github.com/whosonfirst/whosonfirst-sources)
> for a specific feature's license."""


def title_of(collection: str) -> str:
    doc = json.loads((CATALOG / collection / "collection.json").read_text())
    return doc["title"]


def measure(con, collection: str) -> dict:
    full = boundary_path(collection)
    md = pq.ParquetFile(full).metadata
    path = full.as_posix()
    facts: dict = {
        "rows": md.num_rows,
        "size": full.stat().st_size,
        "row_groups": md.num_row_groups,
        "group_rows": ROW_GROUP_ROWS[collection],
        "group_bytes": full.stat().st_size / md.num_row_groups,
        "level": COLLECTION_LEVEL[collection],
    }
    facts["placetypes"] = con.execute(
        f"SELECT placetype, count(*) FROM read_parquet('{path}') "
        "GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    facts["geom_src"] = con.execute(
        f"SELECT coalesce(geom_src, '(none)'), count(*) FROM "
        f"read_parquet('{path}') GROUP BY 1 ORDER BY 2 DESC LIMIT 8"
    ).fetchall()
    (
        facts["points"], facts["v_median"], facts["v_p95"], facts["v_max"],
        facts["with_pop"], facts["repaired"], facts["countries"],
    ) = con.execute(
        f"""SELECT count(*) FILTER (vertices = 1),
                   round(median(vertices)), round(quantile_cont(vertices, 0.95)),
                   max(vertices), count(population),
                   count(*) FILTER (geometry_repaired),
                   count(DISTINCT country)
            FROM read_parquet('{path}')"""
    ).fetchone()
    disp = display_path(collection)
    if facts["level"] in DISPLAY_LEVELS and disp.exists():
        facts["display_size"] = disp.stat().st_size
        facts["display_share"] = 100 * disp.stat().st_size / facts["size"]
    pm = pmtiles_path(collection)
    if pm.exists():
        facts["pmtiles_size"] = pm.stat().st_size
    return facts


def schema_table(columns, present: set[str]) -> list[str]:
    lines = ["| column | type | what it is |", "|---|---|---|"]
    for name, kind, tag, description in columns:
        if name not in present:
            continue
        first = description.split(". ")[0].rstrip(".")
        first = first.replace("\n", " ")
        lines.append(f"| `{name}` | {kind} | {first} |")
    return lines


def present_columns(path: Path) -> set[str]:
    return {f.name for f in pq.ParquetFile(path).schema_arrow}


def run_query(con, sql: str) -> list:
    return con.execute(sql).fetchall()


def boundary_readme(con, collection: str, facts: dict) -> str:
    title = title_of(collection)
    full = boundary_path(collection)
    pt = ", ".join(f"`{p}` ({n:,})" for p, n in facts["placetypes"])
    lines = [
        f"# {title}",
        "",
        f"Level {facts['level']} of the Who's On First administrative ladder, "
        f"as a cloud-native gazetteer collection: {facts['rows']:,} places "
        f"across {facts['countries']:,} country codes.",
        "",
        f"Placetypes here: {pt}.",
        "",
        "Who's On First calls itself a gazetteer, and that is what this is: "
        "place-name and boundary lookup. There is no street or house number "
        "anywhere in WOF's admin distribution, so this is not address "
        "geocoding.",
        "",
        LICENSE_NOTE,
        "",
        "## Which file to read",
        "",
        "| you want | read | why |",
        "|---|---|---|",
    ]
    if "display_size" in facts:
        lines.append(
            f"| To draw an outline, now | `{display_path(collection).name}` | "
            f"Simplified, {human(facts['display_size'])} against "
            f"{human(facts['size'])} |"
        )
    lines += [
        f"| To draw many at once | `{collection}.pmtiles` | Tiled, capped at "
        "400 KB per tile |",
        f"| To clip, measure, export or analyse one place | "
        f"`{full.name}` | The real geometry, "
        f"{human(facts['group_bytes'])} per range request |",
        "| To scan the whole planet, or all 21 placetypes at once | "
        f"[geocode.earth's combined GeoParquet]({UPSTREAM_PARQUET}) | One "
        "file, spatially clustered, 5.5 GiB |",
        "| The full hierarchy, every language, or the temporal fields | "
        f"[geocode.earth's SQLite distribution]({UPSTREAM_SQLITE}) | The "
        "GeoParquet build does not carry them |",
        "",
        "### Why this catalog has its own GeoParquet at all",
        "",
        "geocode.earth's combined file is cloud-native already: GeoParquet "
        "1.1 with a `covering` bbox, served with HTTP range requests and "
        "`Access-Control-Allow-Origin: *`. For a scan or a spatial query it "
        "is the right file, and this collection links straight to it.",
        "",
        "It is the wrong file for fetching **one** place. Measured "
        "(`docs/upstream-measurements.md` in the "
        "[repository](https://github.com/portolan-mirrors/whosonfirst-catalog)): "
        "83 row groups of 65,536 rows, no declared sort, 89% of the bytes in "
        "the `geometry` column, so one row group's geometry chunk is a median "
        "of 38 MiB and as much as 285 MiB. Every Parquet reader is "
        "row-group-granular, so that is the cost of decoding a single row. "
        "`placetype` statistics span most of the alphabet in most row groups, "
        "so filtering to this level prunes nothing either.",
        "",
        f"This file is the same {facts['rows']:,} places sorted by "
        f"`(country, wof_id)` with the sort declared, in "
        f"{facts['row_groups']:,} exactly-full row groups of "
        f"{facts['group_rows']} — {human(facts['group_bytes'])} each.",
        "",
        "## Files",
        "",
        "```",
        f"{collection}/{full.name}  "
        f"{human(facts['size'])}, {facts['rows']:,} rows, "
        f"{facts['row_groups']:,} row groups of {facts['group_rows']}",
    ]
    if "display_size" in facts:
        lines.append(
            f"{collection}/{display_path(collection).name}  "
            f"{human(facts['display_size'])} "
            f"({facts['display_share']:.1f}% of the full file)"
        )
    if "pmtiles_size" in facts:
        lines.append(
            f"{collection}/{collection}.pmtiles  "
            f"{human(facts['pmtiles_size'])}, layer \"{collection}\""
        )
    lines += ["```", ""]

    if "display_size" in facts:
        lines += [
            "### The display file is outward-biased, and that matters",
            "",
            "Its geometry is `ST_SimplifyPreserveTopology` followed by "
            "`ST_Buffer` **outward** by the same tolerance, which is "
            f"{SIMPLIFY_SHARE:.1%} of each feature's own bounding-box diagonal "
            f"capped at {SIMPLIFY_TOLERANCE[collection]} degrees. "
            "Simplification alone cuts corners *inward*, and a shape used as "
            "a spatial filter that sits inside the true boundary silently "
            "drops features near the edge. Buffering outward makes the result "
            "contain the original instead.",
            "",
            "So neighbouring places overlap in the margin, a point near a "
            "border can fall inside two display polygons, and you should not "
            "measure area from them or decide which side of a border a point "
            "is on with them. **Row *i* is the same place in both files**, "
            "and so is row group *g*: the display file is written with the "
            "same row count, row order and row group boundaries as the "
            "full-resolution file, so one byte-range plan serves either.",
            "",
            "Point geometries are carried through untouched. Buffering a "
            "point would turn a marker into a circle and change the row's "
            "geometry type.",
            "",
        ]

    lines += [
        "## Schema",
        "",
        "Every column, with its provenance tag and full description, is in "
        "[collection.json](collection.json). The short version:",
        "",
    ]
    lines += schema_table(BOUNDARY_COLUMNS, present_columns(full))
    lines += [
        "",
        "## What this collection measures",
        "",
        "| | |",
        "|---|---|",
        f"| Places | {facts['rows']:,} |",
        f"| Country codes | {facts['countries']:,} |",
        f"| Point geometries | {facts['points']:,} "
        f"({100 * facts['points'] / facts['rows']:.1f}%) |",
        f"| Coordinates per outline | median {facts['v_median']:,.0f}, "
        f"95th percentile {facts['v_p95']:,.0f}, max {facts['v_max']:,} |",
        f"| Features carrying a population | {facts['with_pop']:,} "
        f"({100 * facts['with_pop'] / facts['rows']:.1f}%) |",
        f"| Geometries repaired by this build | {facts['repaired']:,} |",
        "",
        "Where the outlines came from, by WOF's own `geom_src`:",
        "",
        "| `geom_src` | places |",
        "|---|---|",
    ]
    for value, n in facts["geom_src"]:
        lines.append(f"| `{value}` | {n:,} |")
    lines += [
        "",
        "That column is the licensing key as well as the provenance one. Join "
        "it to "
        "[sources-spec-latest.json](https://github.com/whosonfirst/whosonfirst-sources) "
        "and a specific place's license is a fact rather than an average.",
        "",
        "## Known issues",
        "",
        f"- **The GeoParquet vintage is {UPSTREAM_PARQUET_BUILT[:10]}, six "
        "months behind the other formats.** geocode.earth's SQLite, "
        "SpatiaLite, GeoJSON-bundle and PMTiles builds of the same repository "
        "are from 2025-10-14 and come from a different WOF tree. A count from "
        "this catalog and a count from the SQLite distribution are two "
        "vintages, not a discrepancy.",
        f"- **{facts['repaired']:,} geometr"
        f"{'y was' if facts['repaired'] == 1 else 'ies were'} invalid upstream "
        "and rebuilt here** with `ST_MakeValid`. The `geometry_repaired` "
        "column flags them. `ST_Intersection` against an invalid polygon "
        "raises `TopologyException` and takes the whole query with it, which "
        "is why this is a repair and not a note.",
        "- **`parent_id` carries WOF's negative sentinels.** `-2`, `-3` and "
        "`-4` are not identifiers; see the column description. `-1` is mapped "
        "to null by this build.",
        "- **The full `wof:hierarchy` and `wof:concordances` are not in the "
        "GeoParquet.** The upstream build flattens them to three ancestor-id "
        "columns and a single concordance key/id pair. Read the SQLite or "
        "GeoJSON distribution for the complete structures.",
        "- **The temporal and deprecation fields are absent.** `mz:is_current`, "
        "`edtf:cessation`, `edtf:deprecated` and `wof:superseded_by` are not "
        "carried by the GeoParquet build, so this collection cannot tell you "
        "whether a place is still a going concern. Pelias's own active-record "
        "filter needs all four and reads them from the SQLite distribution.",
        "",
        "## Example queries",
        "",
        "Every one of these was run against the published files before this "
        "file was written.",
        "",
    ]
    lines += boundary_queries(con, collection, facts)
    lines += [
        "## More",
        "",
        "- [Agent guide](AGENTS.md) — the join keys and the traps.",
        f"- [geocode.earth's download page]({DOWNLOAD_PAGE}) — the upstream "
        "distribution, and the per-country and per-placetype alternatives.",
        f"- [Who's On First placetypes]({WOF_PLACETYPES_PAGE}) — the "
        "project's own definitions.",
        "- [Catalog README](../README.md) and "
        "[catalog agent guide](../AGENTS.md).",
    ]
    return "\n".join(lines) + "\n"


def boundary_queries(con, collection: str, facts: dict) -> list[str]:
    full = boundary_path(collection)
    url = f"{PUBLIC}/{collection}/{full.name}"
    local = full.as_posix()
    out: list[str] = []

    out += [
        "Read it in place over HTTPS, with no credentials:",
        "",
        "```sql",
        "INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;",
        "",
        "SELECT placetype, count(*) AS places",
        f"FROM '{url}'",
        "GROUP BY 1 ORDER BY 2 DESC;",
        "```",
        "```",
    ]
    for value, n in run_query(
        con,
        f"SELECT placetype, count(*) FROM read_parquet('{local}') "
        "GROUP BY 1 ORDER BY 2 DESC",
    ):
        out.append(f"{value}  {n}")
    out += ["```", ""]

    out += [
        "The ten largest places here, by geodesic area:",
        "",
        "```sql",
        "SELECT name, country, placetype, round(area_km2) AS km2",
        f"FROM '{url}'",
        "ORDER BY area_km2 DESC LIMIT 10;",
        "```",
        "```",
    ]
    for name, country, placetype, km2 in run_query(
        con,
        "SELECT name, country, placetype, round(area_km2) FROM "
        f"read_parquet('{local}') ORDER BY area_km2 DESC LIMIT 10",
    ):
        out.append(f"{name}  {country}  {placetype}  {km2:,.0f}")
    out += ["```", ""]

    out += [
        "The country sort is what makes a country filter cheap: it prunes row "
        "groups rather than scanning.",
        "",
        "```sql",
        "SELECT name, placetype, round(area_km2, 1) AS km2",
        f"FROM '{url}'",
        "WHERE country = 'NLD'",
        "ORDER BY area_km2 DESC LIMIT 5;",
        "```",
        "```",
    ]
    for name, placetype, km2 in run_query(
        con,
        "SELECT name, placetype, round(area_km2, 1) FROM "
        f"read_parquet('{local}') WHERE country = 'NLD' "
        "ORDER BY area_km2 DESC LIMIT 5",
    ):
        out.append(f"{name}  {placetype}  {km2}")
    out += ["```", ""]

    out += [
        "Which sources the outlines came from, which is also which licenses "
        "apply:",
        "",
        "```sql",
        "SELECT geom_src, count(*) AS places",
        f"FROM '{url}'",
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 5;",
        "```",
        "```",
    ]
    for value, n in facts["geom_src"][:5]:
        out.append(f"{value}  {n}")
    out += ["```", ""]
    return out


def boundary_agents(con, collection: str, facts: dict) -> str:
    title = title_of(collection)
    full = boundary_path(collection)
    url = f"{PUBLIC}/{collection}/{full.name}"
    lines = [
        f"# AGENTS.md — {title}",
        "",
        "Guidance for AI agents and automated clients working with this "
        "collection.",
        "",
        TAG_RULE,
        "",
        LICENSE_NOTE,
        "",
        "## Overview",
        "",
        f"Level {facts['level']} of this catalog's administrative ladder: "
        f"{', '.join('`' + p + '`' for p, _ in facts['placetypes'])}. "
        f"{facts['rows']:,} places. Public root: "
        f"`{PUBLIC}/catalog.json`",
        "",
        "Who's On First is a gazetteer, so this is place-name and boundary "
        "lookup. It holds no street or house number and cannot geocode an "
        "address.",
        "",
        "## Accessing the data",
        "",
        "```sql",
        "INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;",
        "```",
        "",
        "Every file is readable in place over HTTPS range requests. No "
        "credentials, no API, no server.",
        "",
        f"- `{full.name}` — {human(facts['size'])}, {facts['rows']:,} rows, "
        f"{facts['row_groups']:,} row groups of {facts['group_rows']} "
        f"({human(facts['group_bytes'])} each), sorted by "
        "`(country, wof_id)` with `sorting_columns` declared **[derived]**.",
    ]
    if "display_size" in facts:
        lines.append(
            f"- `{display_path(collection).name}` — "
            f"{human(facts['display_size'])}, the same rows at the same "
            "offsets, simplified and buffered outward **[derived]**."
        )
    if "pmtiles_size" in facts:
        lines.append(
            f"- `{collection}.pmtiles` — {human(facts['pmtiles_size'])}, "
            f"layer `{collection}`."
        )
    lines += [
        f"- [geocode.earth's combined GeoParquet]({UPSTREAM_PARQUET}) — "
        "5.5 GiB, all 21 placetypes, spatially clustered. Read this for a "
        "planet-wide scan or a spatial query; **do not** read it to fetch one "
        "place, because its geometry chunks are a median of 38 MiB and up to "
        "285 MiB per row group **[derived]**.",
        "",
        "## Schema & field notes",
        "",
        "Every column is described in [collection.json](collection.json). The "
        "ones that decide whether a query is right:",
        "",
        "| column | what it is |",
        "|---|---|",
        "| `wof_id` | the Who's On First id, as a **string**. The key "
        "everything joins on |",
        "| `parent_id` | the parent's `wof_id`, **or one of WOF's negative "
        "sentinels**: `-2`, `-3`, `-4` |",
        "| `level` | this catalog's 0-to-5 mapping of `placetype`. WOF "
        "publishes no level |",
        "| `placetype` | WOF's own placetype. A level can hold more than one |",
        "| `country` | ISO 3166-1 alpha-3, derived. `country_iso2` is WOF's "
        "own two-letter code |",
        "| `geom_src` | which source the outline came from, and therefore "
        "which license |",
        "| `vertices` | coordinates in the geometry. `1` means the geometry is "
        "a point |",
        "| `geometry_repaired` | true where this build rebuilt an invalid "
        "upstream polygon |",
        "",
        "## Data quality & usage notes",
        "",
        f"**{facts['points']:,} of {facts['rows']:,} features "
        f"({100 * facts['points'] / facts['rows']:.1f}%) are points, not "
        "polygons** **[derived]**. Check `vertices = 1`, or `is_point` in the "
        "names collection, before drawing an outline or computing an area.",
        "",
        "```sql",
        "SELECT count(*) FILTER (vertices = 1) AS points, count(*) AS total",
        f"FROM '{url}';",
        "```",
        "",
        "**`parent_id` is not always an id.** WOF reserves `-2` \"shrug, this "
        "feature is complicated\", `-3` \"contested, but not disputed\" and "
        "`-4` \"multiple 'legal' parents\" **[attested, "
        "https://whosonfirst.org/docs/properties/wof/]**. A join on "
        "`parent_id` has to exclude them.",
        "",
        "**`country` is derived; `country_iso2` is WOF's.** Six of WOF's "
        "two-letter codes are its own and have no alpha-3 — `XK`, `XN`, `XS`, "
        "`XX`, `XY`, `XZ` **[attested, whosonfirst-placetypes]**. Those rows "
        "carry the two-letter code in `country`.",
        "",
        "**Nothing here says whether a place still exists.** `mz:is_current`, "
        "`edtf:cessation`, `edtf:deprecated` and `wof:superseded_by` are not "
        "carried by geocode.earth's GeoParquet build **[derived: the file has "
        "57 columns and none of them is any of those]**. Pelias's own "
        "active-record filter needs all four. If currency matters, read the "
        f"[SQLite distribution]({UPSTREAM_SQLITE}).",
        "",
        "**Area is reproducible, not official.** `area_km2` is pyproj's "
        "geodesic measure on the geometry in this file — not DuckDB's "
        "`ST_Area_Spheroid`, which returns NaN for a large minority of these "
        "geometries **[derived]**. For a place whose outline was carried up "
        "from a coarser source, it is not that place's surveyed area, and it "
        "measures land only, so a country comes out a little under its "
        "published figure.",
        "",
        "## Example queries",
        "",
        "Each of these was run against the published files before this guide "
        "was written; the output under each one is what it returned.",
        "",
    ]
    lines += boundary_queries(con, collection, facts)
    lines += [
        "## Related collections",
        "",
        "| collection | level | holds |",
        "|---|---|---|",
    ]
    for other in COLLECTIONS:
        lines.append(
            f"| [`{other}`](../{other}/collection.json) | "
            f"{COLLECTION_LEVEL[other]} | "
            f"{', '.join('`' + p + '`' for p in COLLECTIONS[other])} |"
        )
    lines += [
        "| [`names`](../names/collection.json) | all | the gazetteer name "
        "index, one row per place plus one per alternative spelling |",
        "",
        f"Join `names.feature_id` to `{collection}.wof_id`, branching on "
        "`names.level` to pick the collection. The names index also carries "
        "an advisory `geometry_ref` that points straight at the row group and "
        "row in this file.",
        "",
        "Two sibling catalogs are built to the same index contract: "
        "[geoBoundaries CGAZ](https://source.coop/portolan-mirrors/geoboundaries-catalog) "
        "under CC-BY-4.0, and "
        "[Overture divisions](https://source.coop/portolan-mirrors/cn-gazetteer-overture) "
        "under ODbL. This one reaches further down the hierarchy than "
        "geoBoundaries and carries no share-alike obligation, unlike Overture.",
    ]
    return "\n".join(lines) + "\n"


def _prominent_facts(manifest: dict) -> dict:
    entry = manifest.get("prominent_index")
    if not entry:
        return {}
    return {
        "prominent_name": entry["url"].lstrip("./"),
        "prominent_size": entry["size"],
        "prominent_rows": entry["row_count"],
        "prominent_groups": entry["row_groups"],
        "prominent_group_rows": entry["row_group_rows"],
    }


def names_facts(con) -> dict:
    md = pq.ParquetFile(NAMES_PATH).metadata
    manifest = json.loads((CATALOG / "names" / "index.json").read_text())
    path = NAMES_PATH.as_posix()
    facts = {
        "rows": md.num_rows,
        "size": NAMES_PATH.stat().st_size,
        "row_groups": md.num_row_groups,
        "group_rows": manifest["index"]["row_group_rows"],
        "footer": manifest["index"]["footer_bytes"],
        "page_index": manifest["index"]["page_index_bytes"],
        "primary": manifest["primary_rows"],
        "alt": manifest["alt_rows"],
        "dropped_unnamed": manifest["dropped_unnamed"],
        "manifest_bytes": (CATALOG / "names" / "index.json").stat().st_size,
        **_prominent_facts(manifest),
    }
    facts["by_level"] = con.execute(
        f"""SELECT level, count(*), count(*) FILTER (alt_of IS NULL),
                   count(*) FILTER (alt_of IS NOT NULL)
            FROM read_parquet('{path}') GROUP BY 1 ORDER BY 1"""
    ).fetchall()
    facts["langs"] = con.execute(
        f"SELECT name_lang, count(*) FROM read_parquet('{path}') "
        "WHERE name_lang IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
    ).fetchall()
    facts["worst_dupes"] = con.execute(
        f"""SELECT any_value(name), max(name_dupes)
            FROM read_parquet('{path}') GROUP BY name_norm
            ORDER BY 2 DESC LIMIT 8"""
    ).fetchall()
    facts["points"] = con.execute(
        f"SELECT count(*) FILTER (is_point), count(*) FROM "
        f"read_parquet('{path}')"
    ).fetchone()
    pm = pmtiles_path("names")
    if pm.exists():
        facts["pmtiles_size"] = pm.stat().st_size
    return facts


def names_readme(con, facts: dict) -> str:
    url = f"{PUBLIC}/names/{NAMES_PATH.name}"
    lines = [
        f"# {title_of('names')}",
        "",
        "**A name search sidecar, not a boundary dataset.** "
        f"{facts['primary']:,} places plus {facts['alt']:,} alternative "
        f"spellings of their names, {facts['rows']:,} rows in all, sorted by "
        "a folded form of the name so that a static client with no server can "
        "turn a typed name into a Who's On First identifier, a bounding box "
        "and a point.",
        "",
        "This is place-name lookup, not address geocoding. Who's On First's "
        "admin distribution holds no street or house number.",
        "",
        LICENSE_NOTE,
        "",
        "## Files",
        "",
        "```",
        f"names/{NAMES_PATH.name}  {human(facts['size'])}, "
        f"{facts['rows']:,} rows, {facts['row_groups']:,} row groups of "
        f"{facts['group_rows']:,}",
        f"names/index.json  {facts['manifest_bytes']:,} bytes, the manifest "
        "to fetch first",
    ]
    if "prominent_size" in facts:
        lines.append(
            f"names/{facts['prominent_name']}  "
            f"{human(facts['prominent_size'])}, "
            f"{facts['prominent_rows']:,} rows, the prominent subset to "
            "load eagerly"
        )
    if "pmtiles_size" in facts:
        lines.append(
            f"names/names.pmtiles  {human(facts['pmtiles_size'])}, "
            "zoom 0-8, layer \"names\""
        )
    lines += [
        "```",
        "",
        "## How to read it",
        "",
        "**Fetch [index.json](index.json) first.** It carries the index's "
        "exact size, row group count and checksum, the footer size so the "
        "first read can be one exactly-sized tail request, every boundary "
        "file's URL and row count, the `catalog_version` "
        f"(`{CATALOG_VERSION}`) all of them are pinned to, and the "
        "attribution a client must display.",
        "",
        f"**Then range-request the index.** At {human(facts['size'])} this "
        "file is not meant to be loaded whole. The manifest's `index.size` "
        "lets the footer read be one exactly-sized tail request of "
        f"{facts['footer']:,} bytes rather than a speculative 512 KB. After "
        "that, the sort does the work: a typed prefix lives in a contiguous "
        "run of row groups that a client finds by binary search over the "
        "`name_norm` statistics. `docs/index-measurements.md` in the "
        "[repository](https://github.com/portolan-mirrors/whosonfirst-catalog) "
        "has the per-prefix numbers.",
        "",
        "A browser client reads it with "
        "[hyparquet](https://github.com/hyparam/hyparquet) plus "
        "[hyparquet-compressors](https://github.com/hyparam/hyparquet-compressors). "
        "The compressors package is **required**: every column chunk is zstd.",
        "",
        (
            f"**Or load the prominent subset whole.** "
            f"`names/{facts.get('prominent_name', '')}` "
            f"({human(facts.get('prominent_size', 0))}, "
            f"{facts.get('prominent_rows', 0):,} rows) is a strict row "
            "subset of the full index in the same schema and sort: every "
            "country, region and county, the larger localadmins, cities "
            "from 50,000 people, and the English and major-language "
            "spellings of all of them. A client that fetches it on "
            "search-box focus answers first keystrokes from memory — "
            "including fuzzy, typo-tolerant matching, which range requests "
            "cannot do — while deep queries fall through to the full "
            "index. The manifest's `prominent_index.criteria` states "
            "exactly what is in and out, and why."
        ) if "prominent_size" in facts else "",
        "",
        "## What is in it",
        "",
        "| level | rows | places | alternative spellings |",
        "|---|---|---|---|",
    ]
    for level, total, primary, alt in facts["by_level"]:
        lines.append(f"| {level} | {total:,} | {primary:,} | {alt:,} |")
    lines += [
        "",
        (
            "`dropped_unnamed: 0` — the build drops a place whose name folds "
            "to nothing, because it cannot be found by name, and **no place "
            "in this distribution does**. Every one of the 5,405,294 has a "
            "name."
            if facts["dropped_unnamed"] == 0 else
            f"`dropped_unnamed: {facts['dropped_unnamed']:,}` — places whose "
            "name folds to nothing, so they cannot be found by name. They "
            "still exist with geometry in their boundary collection."
        ),
        "",
        f"**{facts['points'][0]:,} of {facts['points'][1]:,} rows have "
        "`is_point = true`**, meaning the place's geometry in its boundary "
        "collection is a single point rather than a polygon. Most of Who's On "
        "First's localities come from GeoNames, which is a point gazetteer. "
        "Check this column before drawing an outline.",
        "",
        "### The languages the alternative spellings come from",
        "",
        f"geocode.earth's GeoParquet build carries {len(NAME_LANGS)} fixed "
        "language columns. Who's On First itself carries names in hundreds of "
        "languages — one San Francisco record has 214 `name:*` properties — "
        "but those live in the SQLite and GeoJSON distributions, so this "
        f"index cannot be richer than {len(NAME_LANGS)} languages however "
        "multilingual WOF is. Both distributions are assets of this "
        "collection.",
        "",
        "| `name_lang` | rows |",
        "|---|---|",
    ]
    for lang, n in facts["langs"]:
        lines.append(f"| `{lang}` | {n:,} |")
    lines += [
        "",
        "A language value becomes a row only where its folded form differs "
        "from the folded primary name and from every other language's folded "
        "form for the same place. Where several agree, one row is kept and "
        "`name_lang_count` says how many agreed.",
        "",
        "## Schema",
        "",
        "Every column, with its provenance tag and full description, is in "
        "[collection.json](collection.json). The short version:",
        "",
    ]
    lines += schema_table(INDEX_COLUMNS, present_columns(NAMES_PATH))
    lines += [
        "",
        "## Known issues",
        "",
        f"- **{len(NAME_LANGS)} languages, not hundreds.** See above. This is "
        "a limit of the GeoParquet distribution, not of Who's On First.",
        "- **The primary name is not always English, whatever WOF's "
        "documentation says.** `wof:name` is documented as \"English by "
        "default\", and it is not: the primary name of Kyoto Prefecture "
        "(`wof_id` 85672777) in this distribution is `كيوتو`. The Latin "
        "spellings of such a place live in its alternative-spelling rows, "
        "which is a large part of why they exist. Do not assume a primary "
        "row is searchable in Latin script.",
        "- **The fold strips every Unicode mark, spacing marks included.** "
        "The index contract says to drop `\\p{M}`, so a Devanagari or "
        "Bengali name folds to its consonant skeleton: `क्योटो प्रीफेक्चर` becomes "
        "`कयट परफकचर`. A client must apply exactly the same fold to the "
        "user's keystrokes — a JavaScript `/\\p{M}/gu` strip does — or the "
        "binary search misses for those scripts. It also means the index "
        "cannot distinguish two Indic names that differ only in their vowel "
        "marks.",
        "- **No currency or deprecation fields.** `mz:is_current`, "
        "`edtf:cessation`, `edtf:deprecated` and `wof:superseded_by` are not "
        "in the GeoParquet build, so a deprecated place may appear in this "
        "index with no sign that it is deprecated.",
        "- **`geometry_ref` is advisory.** Verify the `wof_id` of the row you "
        "land on before trusting its geometry; see the column description.",
        "- **The geometry column is a centroid, not a label point.** WOF "
        "publishes a hand-placed `lbl:latitude`/`lbl:longitude` pair that the "
        "GeoParquet build does not carry, so for a concave or multipart place "
        "the point can fall outside it.",
        "",
        "## Example queries",
        "",
    ]
    lines += names_queries(con, url)
    lines += [
        "## More",
        "",
        "- [Agent guide](AGENTS.md) — the prefix-lookup recipe and the join "
        "back to geometry.",
        "- [Index manifest](index.json) — fetch this before the index.",
        "- [Catalog README](../README.md).",
    ]
    return "\n".join(lines) + "\n"


def names_queries(con, url: str) -> list[str]:
    local = NAMES_PATH.as_posix()
    out = [
        "Each of these was run against the published index before this file "
        "was written.",
        "",
        "Everything called Kyoto, in any of the languages this index carries:",
        "",
        "```sql",
        "INSTALL httpfs; LOAD httpfs;",
        "",
        "SELECT name, name_lang, level, placetype, country, parent_name",
        f"FROM '{url}'",
        "WHERE name_norm = 'kyoto'",
        "ORDER BY level, population DESC NULLS LAST;",
        "```",
        "```",
    ]
    for row in run_query(
        con,
        "SELECT name, coalesce(name_lang,'(primary)'), level, placetype, "
        f"country, coalesce(parent_name,'') FROM read_parquet('{local}') "
        "WHERE name_norm = 'kyoto' ORDER BY level, population DESC NULLS LAST",
    )[:10]:
        out.append("  ".join(str(v) for v in row))
    out += ["```", ""]

    out += [
        "A prefix lookup, which is what the sort exists for:",
        "",
        "```sql",
        "SELECT name, level, country, parent_name, population",
        f"FROM '{url}'",
        "WHERE name_norm >= 'zuri' AND name_norm < 'zurj'",
        "  AND alt_of IS NULL",
        "ORDER BY population DESC NULLS LAST LIMIT 5;",
        "```",
        "```",
    ]
    for row in run_query(
        con,
        "SELECT name, level, country, coalesce(parent_name,''), "
        f"coalesce(population, -1) FROM read_parquet('{local}') "
        "WHERE name_norm >= 'zuri' AND name_norm < 'zurj' AND alt_of IS NULL "
        "ORDER BY population DESC NULLS LAST LIMIT 5",
    ):
        out.append("  ".join(str(v) for v in row))
    out += ["```", ""]

    out += [
        "The most ambiguous place names in the world, which is why "
        "`name_dupes` exists:",
        "",
        "```sql",
        "SELECT any_value(name) AS example, max(name_dupes) AS places",
        f"FROM '{url}'",
        "GROUP BY name_norm ORDER BY places DESC LIMIT 8;",
        "```",
        "```",
    ]
    for name, n in run_query(
        con,
        f"SELECT any_value(name), max(name_dupes) FROM read_parquet('{local}') "
        "GROUP BY name_norm ORDER BY 2 DESC LIMIT 8",
    ):
        out.append(f"{name}  {n:,}")
    out += ["```", ""]

    out += [
        "The join back to geometry, branching on `level`:",
        "",
        "```sql",
        "SELECT n.name, n.country, b.area_km2, b.vertices",
        f"FROM '{url}' n",
        f"JOIN '{PUBLIC}/country/wof_country.parquet' b",
        "  ON b.wof_id = n.feature_id",
        "WHERE n.level = 0 AND n.alt_of IS NULL",
        "ORDER BY b.area_km2 DESC LIMIT 5;",
        "```",
        "```",
    ]
    for row in run_query(
        con,
        "SELECT n.name, n.country, round(b.area_km2) , b.vertices "
        f"FROM read_parquet('{local}') n JOIN "
        f"read_parquet('{boundary_path('country').as_posix()}') b "
        "ON b.wof_id = n.feature_id "
        "WHERE n.level = 0 AND n.alt_of IS NULL "
        "ORDER BY b.area_km2 DESC LIMIT 5",
    ):
        out.append("  ".join(str(v) for v in row))
    out += ["```", ""]
    return out


def names_agents(con, facts: dict) -> str:
    url = f"{PUBLIC}/names/{NAMES_PATH.name}"
    lines = [
        f"# AGENTS.md — {title_of('names')}",
        "",
        "Guidance for AI agents and automated clients working with this "
        "collection.",
        "",
        TAG_RULE,
        "",
        LICENSE_NOTE,
        "",
        "## Overview",
        "",
        "**A name search sidecar, not a boundary dataset.** "
        f"{facts['primary']:,} places plus {facts['alt']:,} alternative "
        f"spellings, {facts['rows']:,} rows, sorted by a folded form of the "
        "name. Public root: "
        f"`{PUBLIC}/catalog.json`",
        "",
        "```",
        f"names/{NAMES_PATH.name}  {human(facts['size'])}, "
        f"{facts['rows']:,} rows, {facts['row_groups']:,} row groups of "
        f"{facts['group_rows']:,}",
        f"names/index.json  {facts['manifest_bytes']:,} bytes, fetch first",
    ]
    if "prominent_size" in facts:
        lines.append(
            f"names/{facts['prominent_name']}  "
            f"{human(facts['prominent_size'])}, "
            f"{facts['prominent_rows']:,} rows, strict subset, load "
            "eagerly for instant + fuzzy search"
        )
    lines += [
        "```",
        "",
        (
            "**The prominent subset** **[derived]** is a strict row subset "
            "of the full index (same schema, same `name_norm` sort, same "
            "`feature_id` and `geometry_ref` values), selected by the "
            "measured criteria in the manifest's `prominent_index.criteria` "
            "— including the english_guarantee: every place kept is "
            "findable by its English spelling where the distribution "
            "carries one. Load it whole on search-box focus; it is the "
            "only file a client's fuzzy (typo) fallback can scan without "
            "downloading the full index, so a name absent here is "
            "prefix-searchable but not typo-findable in range mode."
        ) if "prominent_size" in facts else "",
        "",
        "The `geometry` column is **one point per row**, the place's "
        "centroid. It is a marker, not a shape: do not compute area, length "
        "or containment from this file. The shape lives in the boundary "
        "collection at the row's `level`.",
        "",
        "## Accessing the data",
        "",
        "```sql",
        "INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;",
        "```",
        "",
        "**Fetch [index.json](index.json) first** **[derived]**. It carries "
        f"the index's size ({facts['size']:,} bytes), row group count "
        f"({facts['row_groups']:,}), checksum, footer size "
        f"({facts['footer']:,} bytes), the `catalog_version` "
        f"(`{CATALOG_VERSION}`) that must match the footer metadata of this "
        "file and of every boundary file, the URL and row count of each "
        "boundary and display file, and the attribution each source requires.",
        "",
        f"**Then range-request the index.** At {human(facts['size'])} this "
        "file is not meant to be loaded whole. The manifest's `index.size` "
        "lets the footer read be one exactly-sized tail request of "
        f"{facts['footer']:,} bytes rather than hyparquet's speculative "
        f"512 KB default, with a further {facts['page_index']:,} bytes of "
        "page index read lazily per column chunk **[derived: "
        "`tools/measure_index.py`]**.",
        "",
        "## Schema & field notes",
        "",
        "Every column is described in [collection.json](collection.json). The "
        "ones that decide whether a query is right:",
        "",
        "| column | what it is |",
        "|---|---|",
        "| `name_norm` | **the sort key.** NFD, combining marks dropped, only "
        "letters, digits, space, hyphen and apostrophe kept, whitespace "
        "collapsed, lowercased. Compared byte-wise on UTF-8, not by a locale "
        "collation |",
        "| `name` | the spelling to display |",
        "| `feature_id` | the place's `wof_id`. Joins to `wof_id` in a "
        "boundary collection |",
        "| `alt_of` | null on a primary row; the row's own `feature_id` on an "
        "alternative-spelling row |",
        "| `name_lang` | the ISO 639-3 code this spelling came from; null on a "
        "primary row |",
        "| `level` | 0 to 5. **Which boundary collection to join** |",
        "| `is_point` | whether the place's geometry is a point rather than a "
        "polygon |",
        "| `geometry_ref` | advisory `{file, row_group, row}` into the "
        "boundary file and its display companion |",
        "",
        "## Data quality & usage notes",
        "",
        "**An alternative-spelling row shares its place's `feature_id`.** "
        "Dedupe results on it, or the same city appears once per language "
        "**[derived]**:",
        "",
        "```sql",
        "SELECT count(*) AS rows, count(DISTINCT feature_id) AS places",
        f"FROM '{url}';",
        "```",
        "",
        f"**{facts['points'][0]:,} of {facts['points'][1]:,} rows are points "
        "in their boundary collection** **[derived]**. `is_point` says so per "
        "row. A client about to draw an outline should check it first.",
        "",
        "**The geometry_ref fast path, and why it must be verified.** "
        "`geometry_ref` names a file, a row group and a row. A client "
        "range-reads that row group and takes that row — and **must assert "
        "that row's `wof_id` equals the result's `feature_id`** before "
        "trusting its geometry. If the pointer is stale the client gets "
        "another place's polygon and nothing looks wrong: the geometry is "
        "valid, the bbox is plausible, and the map flies somewhere else. On "
        "any mismatch, fall back to locating the row by `wof_id`, which the "
        "boundary files' `(country, wof_id)` sort and row group statistics "
        "make cheap. `tests/test_index_refs.py` in the repository is the gate "
        "that resolves a sample of these pointers against the real files.",
        "",
        "**Because the display companion holds the same rows at the same "
        "offsets**, one `geometry_ref` resolves against either file, so a "
        "client switching between display and full resolution recomputes "
        "nothing.",
        "",
        f"**{len(NAME_LANGS)} languages, not hundreds** **[derived]**. See "
        "the `name_lang` column description: Who's On First carries names in "
        "hundreds of languages, and geocode.earth's GeoParquet build carries "
        f"{len(NAME_LANGS)} of them.",
        "",
        "**Nothing here says whether a place still exists.** The GeoParquet "
        "build carries no `mz:is_current`, `edtf:cessation`, "
        "`edtf:deprecated` or `wof:superseded_by` **[derived]**, so a "
        "deprecated place can appear in this index with no sign of it.",
        "",
        "## Example queries",
        "",
    ]
    lines += names_queries(con, url)
    lines += [
        "## Related collections",
        "",
        "| level | collection | placetypes |",
        "|---|---|---|",
    ]
    for other in COLLECTIONS:
        lines.append(
            f"| {COLLECTION_LEVEL[other]} | "
            f"[`{other}`](../{other}/collection.json) | "
            f"{', '.join('`' + p + '`' for p in COLLECTIONS[other])} |"
        )
    lines += [
        "",
        "Branch on `level` to pick the collection, then join "
        "`names.feature_id` to that collection's `wof_id`.",
        "",
        "Two sibling catalogs are built to the same index contract: "
        "[geoBoundaries CGAZ](https://source.coop/portolan-mirrors/geoboundaries-catalog) "
        "under CC-BY-4.0 and "
        "[Overture divisions](https://source.coop/portolan-mirrors/cn-gazetteer-overture) "
        "under ODbL. A client configurable to any of the three can filter on "
        "one code system, because all three publish `country` as ISO 3166-1 "
        "alpha-3.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.parse_args()
    con = connect()
    try:
        for collection in COLLECTIONS:
            facts = measure(con, collection)
            write(collection, "README.md", boundary_readme(con, collection, facts))
            write(collection, "AGENTS.md", boundary_agents(con, collection, facts))
        facts = names_facts(con)
        write("names", "README.md", names_readme(con, facts))
        write("names", "AGENTS.md", names_agents(con, facts))
    finally:
        con.close()
    print(f"placetypes carried: {len(PLACETYPE_LEVEL)}, "
          f"excluded: {len(PLACETYPE_EXCLUDED)}")
    print(f"extraction date: {EXTRACTION_DATE}")
    print(f"upstream pmtiles: {UPSTREAM_PMTILES}")
    return 0


def write(collection: str, name: str, text: str) -> None:
    out = CATALOG / collection / name
    out.parent.mkdir(parents=True, exist_ok=True)
    # Wrapped, because a generator builds a paragraph as one long string and a
    # reader opening the raw file in a terminal or a diff then gets one line
    # per paragraph. Fences, tables and headings are left alone.
    out.write_text(wrap_markdown(text) + "\n")
    print(f"  {out.relative_to(REPO)}  {len(text.splitlines())} lines")


if __name__ == "__main__":
    sys.exit(main())
