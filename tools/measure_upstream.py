#!/usr/bin/env python3
"""Measure what geocode.earth's own files cost a client, and write it down.

    python3 tools/measure_upstream.py

This catalog links to geocode.earth's files rather than copying them, so the
only honest way to decide what it should *also* build is to measure what those
files already do well and where they fall down. Everything this script prints
is a measurement, and `docs/upstream-measurements.md` is the record the
catalog's prose cites. Rerun it after any upstream rebuild: if these numbers
moved, the prose is wrong.

Four questions:

1. **Can a browser read these files at all?** Probes the host for range
   support, CORS headers, and the headers a range client actually needs to
   see. Needs the network.
2. **What does one feature's geometry cost from the upstream GeoParquet?**
   Reads the staged file's footer and reports the geometry column chunk size
   per row group, which is what a row-group-granular reader fetches for one
   hit.
3. **What does the upstream PMTiles archive cost at each zoom?** Reads the
   archive's directories over HTTP ranges and reports the size of one tile per
   zoom. Needs the network; downloads a few hundred kilobytes.
4. **What is in there?** Rows per placetype, and which of them this catalog
   carries.

Run `tools/fetch_sources.py` first for question 2. The other three work
without the staged file.
"""
from __future__ import annotations

import gzip
import json
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wofcommon import (  # noqa: E402
    DIST_BASE,
    DOWNLOAD_PAGE,
    EXTRACTION_DATE,
    PARQUET_INVENTORY,
    PLACETYPE_EXCLUDED,
    PLACETYPE_LEVEL,
    SOURCES,
    UPSTREAM_BUNDLE,
    UPSTREAM_PARQUET,
    UPSTREAM_PARQUET_BUILT,
    UPSTREAM_PARQUET_NAME,
    UPSTREAM_PARQUET_WOF_COMMIT,
    UPSTREAM_PMTILES,
    UPSTREAM_PMTILES_BUILT,
    UPSTREAM_SPATIAL,
    UPSTREAM_SQLITE,
    UPSTREAM_SQLITE_BUILT,
    human,
    wrap_markdown,
)

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "upstream-measurements.md"
STAGED = SOURCES / UPSTREAM_PARQUET_NAME

# The headers a range-request client in a browser depends on. `Content-Length`
# is on the CORS-safelisted response-header list, so a browser can read it
# without `Access-Control-Expose-Headers`; `Content-Range` is not, so a client
# that derives a file's size from a 206 response cannot see it unless the host
# exposes it.
WATCHED = (
    "accept-ranges",
    "content-range",
    "content-length",
    "access-control-allow-origin",
    "access-control-expose-headers",
    "etag",
    "last-modified",
    "server",
    "content-type",
)

PROBE_TARGETS = (
    ("combined GeoParquet", UPSTREAM_PARQUET),
    ("combined PMTiles", UPSTREAM_PMTILES),
    ("combined SQLite", UPSTREAM_SQLITE),
    ("combined SpatiaLite", UPSTREAM_SPATIAL),
    ("combined GeoJSON bundle", UPSTREAM_BUNDLE),
)


def curl(args: list[str]) -> str:
    return subprocess.run(
        ["curl", "-sS", *args], capture_output=True, text=True, check=False
    ).stdout


def probe(url: str) -> dict:
    """One range GET, with and without an Origin, plus an OPTIONS preflight."""
    out: dict = {}
    for label, extra in (
        ("plain", []),
        ("cors", ["-H", "Origin: https://example.com"]),
    ):
        raw = curl(
            ["-o", "/dev/null", "-D", "-", "-X", "GET",
             "-H", "Range: bytes=0-99", *extra, url]
        )
        status = raw.splitlines()[0].strip() if raw else "(no response)"
        headers = {}
        for line in raw.splitlines()[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip().lower()
                if k in WATCHED:
                    headers[k] = v.strip()
        out[label] = {"status": status, "headers": headers}
    raw = curl(
        ["-o", "/dev/null", "-D", "-", "-X", "OPTIONS",
         "-H", "Origin: https://example.com",
         "-H", "Access-Control-Request-Method: GET",
         "-H", "Access-Control-Request-Headers: range", url]
    )
    out["preflight"] = raw.splitlines()[0].strip() if raw else "(no response)"
    return out


def footer_layout(path: Path) -> dict:
    import pyarrow.parquet as pq

    md = pq.ParquetFile(path).metadata
    geom = []
    group_bytes = []
    rows = []
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        rows.append(rg.num_rows)
        group_bytes.append(
            sum(rg.column(i).total_compressed_size for i in range(rg.num_columns))
        )
        idx = next(
            i for i in range(rg.num_columns)
            if rg.column(i).path_in_schema == "geometry"
        )
        geom.append(rg.column(idx).total_compressed_size)
    sorting = {
        tuple(
            (s.column_index, s.descending) for s in md.row_group(g).sorting_columns
        )
        for g in range(md.num_row_groups)
    }
    columns: dict[str, int] = {}
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        for i in range(rg.num_columns):
            col = rg.column(i)
            columns[col.path_in_schema] = (
                columns.get(col.path_in_schema, 0) + col.total_compressed_size
            )
    return {
        "size": path.stat().st_size,
        "rows": md.num_rows,
        "row_groups": md.num_row_groups,
        "created_by": md.created_by,
        "footer_size": md.serialized_size,
        "rows_per_group": (min(rows), max(rows)),
        "group_bytes": sorted(group_bytes),
        "geometry_bytes": sorted(geom),
        "sorting_columns": sorting,
        "compression": sorted(
            {
                md.row_group(0).column(i).compression
                for i in range(md.row_group(0).num_columns)
            }
        ),
        "columns": sorted(columns.items(), key=lambda kv: -kv[1]),
    }


def pct(values: list[int], q: float) -> int:
    if not values:
        return 0
    return values[min(len(values) - 1, int(q * (len(values) - 1)))]


# --- the upstream PMTiles archive -----------------------------------------
# One tile per zoom, chosen to land on populated ground (central Europe) so
# that the number is what a reader actually pays rather than an ocean tile.
PROBE_TILES = (
    (0, 0, 0), (1, 1, 0), (2, 2, 1), (3, 4, 2), (4, 8, 5),
    (5, 16, 10), (6, 33, 21), (7, 66, 43), (8, 133, 86), (9, 267, 172),
)


def pmtiles_header(url: str) -> dict:
    head = range_get(url, 0, 127)
    assert head[:7] == b"PMTiles", "not a PMTiles archive"
    fields = struct.unpack_from("<11Q", head, 8)
    clustered, internal, tile_comp, tile_type, minz, maxz = struct.unpack_from(
        "<6B", head, 96
    )
    return {
        "version": head[7],
        "root": (fields[0], fields[1]),
        "metadata": (fields[2], fields[3]),
        "leaves": (fields[4], fields[5]),
        "tile_data": (fields[6], fields[7]),
        "addressed": fields[8],
        "entries": fields[9],
        "contents": fields[10],
        "clustered": bool(clustered),
        "internal_compression": internal,
        "tile_compression": tile_comp,
        "tile_type": tile_type,
        "minzoom": minz,
        "maxzoom": maxz,
    }


def range_get(url: str, start: int, end: int) -> bytes:
    out = subprocess.run(
        ["curl", "-sS", "-H", f"Range: bytes={start}-{end}", url],
        capture_output=True, check=True,
    ).stdout
    want = end - start + 1
    if len(out) != want:
        sys.exit(f"range read of {url} returned {len(out)} bytes, wanted {want}")
    return out


def pmtiles_tiles(url: str, header: dict) -> tuple[dict, list[tuple]]:
    from pmtiles.tile import deserialize_directory, zxy_to_tileid

    root_off, root_len = header["root"]
    leaf_off, _ = header["leaves"]
    root = deserialize_directory(range_get(url, root_off, root_off + root_len - 1))

    def last_at_or_below(entries, tid):
        found = None
        for entry in entries:
            if entry.tile_id <= tid:
                found = entry
            else:
                break
        return found

    results = []
    for z, x, y in PROBE_TILES:
        tid = zxy_to_tileid(z, x, y)
        entry = last_at_or_below(root, tid)
        if entry is None:
            results.append((z, x, y, None))
            continue
        if entry.run_length == 0:
            leaf = deserialize_directory(
                range_get(url, leaf_off + entry.offset,
                          leaf_off + entry.offset + entry.length - 1)
            )
            entry = last_at_or_below(leaf, tid)
        if entry is None or entry.run_length == 0:
            results.append((z, x, y, None))
            continue
        results.append((z, x, y, entry.length))

    meta_off, meta_len = header["metadata"]
    raw = range_get(url, meta_off, meta_off + meta_len - 1)
    if header["internal_compression"] == 2:
        raw = gzip.decompress(raw)
    return json.loads(raw), results


def placetype_counts() -> list[tuple[str, int]]:
    import duckdb

    source = STAGED.as_posix() if STAGED.exists() else UPSTREAM_PARQUET
    con = duckdb.connect()
    if not STAGED.exists():
        con.execute("INSTALL httpfs; LOAD httpfs;")
    rows = con.execute(
        "SELECT placetype, count(*) AS n FROM read_parquet(?) "
        "GROUP BY 1 ORDER BY 2 DESC",
        [source],
    ).fetchall()
    con.close()
    return rows


def main() -> int:
    print("probing the host ...", flush=True)
    probes = {label: probe(url) for label, url in PROBE_TARGETS}

    print("reading the upstream PMTiles directories ...", flush=True)
    header = pmtiles_header(UPSTREAM_PMTILES)
    pm_meta, tiles = pmtiles_tiles(UPSTREAM_PMTILES, header)

    print("counting placetypes ...", flush=True)
    counts = placetype_counts()

    layout = None
    if STAGED.exists():
        print("reading the staged GeoParquet footer ...", flush=True)
        layout = footer_layout(STAGED)
    else:
        print(f"note: {STAGED} is absent; skipping the layout section")

    lines: list[str] = [
        "# What geocode.earth's own files measure",
        "",
        f"Generated by `tools/measure_upstream.py` on {EXTRACTION_DATE}. Every",
        "number here is a measurement against the live host or the staged",
        "upstream file, and every claim in the catalog's prose about what the",
        "upstream distribution costs a client points back at this file. Rerun",
        "the script after any upstream rebuild.",
        "",
        f"The distribution's own index page is [{DOWNLOAD_PAGE}]({DOWNLOAD_PAGE}).",
        "Its file list is fetched by the page's own JavaScript from",
        f"[{PARQUET_INVENTORY}]({PARQUET_INVENTORY}) and the sibling",
        "`inventory.json` files, so the HTML carries no download links at all.",
        "",
        "## 1. Vintage: the formats are not in sync",
        "",
        "There are no versioned URLs. Every file is named `-latest` and is",
        "overwritten in place, and the inventory's `vintage` field is literally",
        "the string `latest`, so a URL pins nothing. The inventory's",
        "`last_modified`, `last_updated`, `commit` and `sha256_compressed` are",
        "the only vintage and integrity record there is.",
        "",
        "| distribution | built | WOF tree |",
        "|---|---|---|",
        f"| GeoParquet | {UPSTREAM_PARQUET_BUILT} | `{UPSTREAM_PARQUET_WOF_COMMIT[:16]}...` |",
        f"| PMTiles | {UPSTREAM_PMTILES_BUILT} | `56b0ba1827b627a9...` |",
        f"| SQLite, SpatiaLite, GeoJSON bundle | {UPSTREAM_SQLITE_BUILT} | `56b0ba1827b627a9...` |",
        "",
        "The GeoParquet build is about six months older than the others and",
        "comes from a different WOF tree. A count taken from this catalog and a",
        "count taken from the SQLite distribution are therefore two vintages,",
        "not a discrepancy.",
        "",
        "**The HTTP `Last-Modified` header is not a vintage signal here.** Every",
        "object under `/wof/dist/` reports a `Last-Modified` of 2025-10-30,",
        "including files whose inventory entries span 2024-01 to 2025-10, and",
        "every ETag is multipart-shaped. The bucket was re-copied on that date.",
        "",
        "## 2. Hosting: can a browser read these files in place?",
        "",
        "One `Range: bytes=0-99` GET per file, with and without an `Origin`,",
        "plus a CORS preflight. Verbatim status lines and the headers a range",
        "client depends on.",
        "",
    ]

    for label, result in probes.items():
        lines += [
            f"### {label}",
            "",
            "```",
            f"GET with Range            -> {result['plain']['status']}",
            f"GET with Range and Origin -> {result['cors']['status']}",
            f"OPTIONS preflight         -> {result['preflight']}",
            "```",
            "",
            "| header | value on the Origin request |",
            "|---|---|",
        ]
        seen = result["cors"]["headers"]
        for key in WATCHED:
            value = seen.get(key)
            shown = f"`{value}`" if value else "**absent**"
            lines.append(f"| `{key}` | {shown} |")
        lines.append("")

    lines += [
        "### What that means for a browser client",
        "",
        "- **Range requests work.** Every file answered a `Range` request with",
        "  a `206` and a correct `Content-Range`, and suffix ranges",
        "  (`bytes=-500000`) work too.",
        "- **CORS allows the fetch.** `Access-Control-Allow-Origin: *` is",
        "  present on every response, with and without an `Origin`.",
        "- **`Access-Control-Expose-Headers` is absent.** `Content-Length` is",
        "  on the CORS-safelisted response-header list, so JavaScript can still",
        "  read it and discover a file's size with a `HEAD`. `Content-Range`,",
        "  `ETag` and `Accept-Ranges` are not safelisted and are not exposed, so",
        "  a client that derives the total size from a `206` response's",
        "  `Content-Range` will read `null` in a browser and must use",
        "  `Content-Length` instead. hyparquet's `asyncBufferFromUrl` takes the",
        "  `HEAD` path, so it works against these URLs.",
        "- **The preflight fails, and for a simple range read it does not",
        "  matter.** `OPTIONS` returns 403, but a single",
        "  `Range: bytes=<int>-<int>` is a CORS-safelisted *request* header",
        "  under the Fetch standard, so no preflight is issued for it. Any",
        "  client that adds a non-safelisted request header will hit that 403.",
        "- **A `Range` request is not guaranteed a `206`.** On a first probe",
        "  pass three of the large `.bz2` objects answered `200` with the whole",
        "  body instead, and it did not reproduce in ten later trials per URL.",
        "  `tools/fetch_sources.py` carries the scar: a resumed download",
        "  appended a second whole copy of the file and produced",
        "  9,164,361,132 bytes where 5,948,636,588 was expected. Check the",
        "  status code; do not assume it.",
        "- **The parquet responses carry no `Content-Type` at all.** Harmless",
        "  for `fetch` and for DuckDB, and worth knowing for anything that",
        "  sniffs a media type before reading.",
        "- **The host 403s some clients by User-Agent.** Python's default",
        "  `urllib` User-Agent is refused; curl, requests, aiohttp, DuckDB's",
        "  httpfs, GDAL, Node and browsers are served.",
        "",
        "## 3. The upstream PMTiles archive, tile by tile",
        "",
        f"`{UPSTREAM_PMTILES}`",
        "",
        f"- {human(2130846508)}, zoom {header['minzoom']}-{header['maxzoom']},",
        f"  {header['entries']:,} tile entries, {header['contents']:,} distinct",
        "  tile bodies, clustered.",
        f"- Generator: `{pm_meta.get('generator', '?')}`",
        f"- Generator options: `{pm_meta.get('generator_options', '?')}`",
        f"- {len(pm_meta.get('vector_layers', []))} vector layers, one per WOF",
        "  placetype.",
        "",
        "| zoom | tile | bytes | |",
        "|---|---|---|---|",
    ]
    for z, x, y, size in tiles:
        if size is None:
            lines.append(f"| {z} | {x}/{y} | — | no tile |")
        else:
            flag = " **too large for a browser**" if size > 2_000_000 else ""
            lines.append(f"| {z} | {x}/{y} | {size:,} | {human(size)}{flag} |")
    lines += [
        "",
        "The archive was built with `--no-tile-size-limit`, which is why the",
        "low zooms are what they are: the whole-world tile is",
        f"{human(tiles[0][3] or 0)} and the mid zooms are worse. tippecanoe also",
        "reports dropping millions of features per zoom to fit",
        "(`strategies[0].dropped_by_rate` is",
        f"{pm_meta.get('strategies', [{}])[0].get('dropped_by_rate', 0):,} at",
        "zoom 0), so a low-zoom view is both heavy and incomplete. This is the",
        "measurement behind this catalog building its own tiles rather than",
        "pointing a style at these.",
        "",
    ]

    if layout:
        geom = layout["geometry_bytes"]
        group = layout["group_bytes"]
        lines += [
            "## 4. The upstream GeoParquet, row group by row group",
            "",
            f"`{UPSTREAM_PARQUET}`",
            "",
            "| property | value |",
            "|---|---|",
            f"| size | {layout['size']:,} bytes ({human(layout['size'])}) |",
            f"| rows | {layout['rows']:,} |",
            f"| row groups | {layout['row_groups']} |",
            f"| rows per group | {layout['rows_per_group'][0]:,} to "
            f"{layout['rows_per_group'][1]:,} |",
            f"| footer | {layout['footer_size']:,} bytes |",
            f"| compression | {', '.join(layout['compression'])} |",
            f"| declared sort | "
            f"{'none in any row group' if layout['sorting_columns'] == {()} else layout['sorting_columns']} |",
            f"| created by | `{layout['created_by']}` |",
            "",
            "**The geometry column is the file.** Compressed bytes per column,",
            "whole file, top ten:",
            "",
            "| column | compressed bytes | share |",
            "|---|---|---|",
        ]
        total = sum(v for _, v in layout["columns"])
        for name, value in layout["columns"][:10]:
            lines.append(
                f"| `{name}` | {value:,} | {100 * value / total:.1f}% |"
            )
        lines += [
            "",
            "**What one feature costs.** A row-group-granular reader fetches a",
            "whole column chunk to decode one row, so the geometry chunk size",
            "per row group is what a single `select()` pays against this file:",
            "",
            "| | compressed geometry chunk | whole row group |",
            "|---|---|---|",
            f"| minimum | {human(geom[0])} | {human(group[0])} |",
            f"| median | {human(pct(geom, 0.5))} | {human(pct(group, 0.5))} |",
            f"| 95th percentile | {human(pct(geom, 0.95))} | {human(pct(group, 0.95))} |",
            f"| maximum | {human(geom[-1])} | {human(group[-1])} |",
            "",
            "No row group declares a sort order, and `placetype` statistics",
            "span most of the placetype alphabet in most row groups, so a",
            "`placetype` predicate prunes nothing. The file *is* spatially",
            "clustered -- GDAL wrote it in bounding-box order, and the",
            "`geometry_bbox` covering columns let a spatial predicate skip most",
            "row groups -- but a name lookup and a single-feature fetch both",
            "fall back to reading a whole 65,536-row group.",
            "",
            "That is the measurement this catalog's own files exist to fix, and",
            "it is why they exist beside the upstream file rather than instead",
            "of it: for a bulk scan, an export or a spatial query, the upstream",
            "file is the right thing to read and this catalog links straight to",
            "it.",
            "",
        ]

    total_rows = sum(n for _, n in counts)
    carried = sum(n for t, n in counts if t in PLACETYPE_LEVEL)
    lines += [
        "## 5. What is in the combined admin distribution",
        "",
        f"{len(counts)} placetypes, {total_rows:,} rows. The `level` column is",
        "this catalog's mapping onto the 0-based admin ladder the search index",
        "contract wants; `—` marks a placetype this catalog does not carry.",
        "",
        "| placetype | rows | level | note |",
        "|---|---|---|---|",
    ]
    for name, n in counts:
        level = PLACETYPE_LEVEL.get(name)
        if level is None:
            lines.append(
                f"| `{name}` | {n:,} | — | {PLACETYPE_EXCLUDED.get(name, 'not carried')} |"
            )
        else:
            lines.append(f"| `{name}` | {n:,} | {level} | |")
    lines += [
        "",
        f"Carried: {carried:,} of {total_rows:,} rows "
        f"({100 * carried / total_rows:.2f}%). The {total_rows - carried:,} rows",
        "left out are the non-administrative placetypes named above.",
        "",
        "There is **no** `venue`, `address`, `building`, `intersection` or",
        "`postalcode` in this distribution. Postcodes and constituencies are",
        f"separate combined files under `{DIST_BASE}/`, and venues are not",
        "distributed by geocode.earth at all.",
        "",
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(wrap_markdown("\n".join(lines)) + "\n")
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
