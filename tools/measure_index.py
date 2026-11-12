#!/usr/bin/env python3
"""Measure what the gazetteer index costs a client, and write the numbers down.

    python3 tools/measure_index.py

Three questions a consumer of this index has, answered against the built file
rather than asserted:

1. **What does the metadata cost?** A range-request client reads the footer
   before anything else, and the manifest declares the file size so that read
   can be one exactly-sized tail request. The number this prints is what that
   request has to fetch.

2. **What does a keystroke cost?** For every two-letter prefix that occurs in
   the index, how many row groups can hold a match. The answer is bounded by
   the sort: a prefix lives in a contiguous run of groups, and the row group
   statistics on `name_norm` are what a client binary-searches. A prefix that
   touches one group costs one range request.

3. **Where do the bytes go?** Compressed bytes per column, so a future change
   to the schema can be argued about with numbers.

The results go to `docs/index-measurements.md` and `docs/index-measurements.json`,
which the collection README cites. Rerun after any rebuild: if these numbers
moved, the prose is wrong.
"""
from __future__ import annotations

import bisect
import json
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pyarrow.parquet as pq  # noqa: E402

from wofcommon import (  # noqa: E402
    NAMES_PATH,
    WORK,
    NAMES_ROW_GROUP_ROWS,
    human,
    wrap_markdown,
)

REPO = Path(__file__).resolve().parents[1]
OUT_MD = REPO / "docs" / "index-measurements.md"
OUT_JSON = REPO / "docs" / "index-measurements.json"


def footer_bytes(path: Path) -> tuple[int, int]:
    """The footer, and the page index that sits before it.

    Parquet writes the page index after the last row group and the footer
    after that, so the span from the end of the last column chunk's pages to
    EOF is the two together. `file_offset` is optional and PyArrow writes 0
    for it, so the offset is taken from the dictionary page where there is one
    and from the first data page otherwise.
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


def row_group_ranges(path: Path) -> list[tuple[str, str]]:
    md = pq.ParquetFile(path).metadata
    ranges = []
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        idx = next(
            i for i in range(rg.num_columns)
            if rg.column(i).path_in_schema == "name_norm"
        )
        st = rg.column(idx).statistics
        ranges.append((st.min, st.max))
    return ranges


def groups_for_prefix(ranges: list[tuple[str, str]], prefix: str) -> int:
    """How many row groups can hold a name starting with prefix.

    The same arithmetic a client does: find the first group whose max is not
    below the prefix, then walk while the group's min still sorts below the
    prefix's upper bound. Compared on UTF-8 bytes, which is the file's order.
    """
    lows = [lo.encode("utf-8") for lo, _ in ranges]
    highs = [hi.encode("utf-8") for _, hi in ranges]
    key = prefix.encode("utf-8")
    upper = key + b"\xff" * 8
    first = bisect.bisect_left(highs, key)
    last = bisect.bisect_right(lows, upper) - 1
    if first > last:
        return 0
    return last - first + 1


def column_bytes(path: Path) -> list[tuple[str, int]]:
    md = pq.ParquetFile(path).metadata
    totals: dict[str, int] = {}
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        for i in range(rg.num_columns):
            col = rg.column(i)
            totals[col.path_in_schema] = (
                totals.get(col.path_in_schema, 0) + col.total_compressed_size
            )
    return sorted(totals.items(), key=lambda kv: -kv[1])


def hyparquet_report() -> str:
    """Run the Node verification and capture its output, or return "".

    Optional on purpose: the measurement document should still generate on a
    machine with no Node, and the absence of the section says so by being
    absent rather than by claiming an untested result.
    """
    script = Path(__file__).resolve().parent / "verify_index_hyparquet.mjs"
    modules = WORK / "node" / "node_modules"
    if not script.exists() or not modules.is_dir():
        print("note: skipping the hyparquet read-back (no node_modules)")
        return ""
    import os

    env = dict(os.environ, NODE_PATH=str(modules))
    result = subprocess.run(
        ["node", str(script), str(NAMES_PATH)],
        capture_output=True, text=True, env=env, check=False,
    )
    if result.returncode != 0:
        print("note: the hyparquet read-back failed:")
        print(result.stdout or result.stderr)
        return ""
    print("  hyparquet read-back: OK")
    return result.stdout


def main() -> int:
    if not NAMES_PATH.exists():
        sys.exit(f"missing {NAMES_PATH}; run tools/build_names.py first")
    md = pq.ParquetFile(NAMES_PATH).metadata
    size = NAMES_PATH.stat().st_size
    footer, page_index = footer_bytes(NAMES_PATH)
    ranges = row_group_ranges(NAMES_PATH)

    print("reading the name_norm column ...", flush=True)
    norms = pq.read_table(NAMES_PATH, columns=["name_norm"]).column("name_norm")
    prefixes = sorted({v[:2] for v in norms.to_pylist() if len(v) >= 2})
    print(f"  {len(prefixes):,} distinct two-character prefixes", flush=True)
    counts = [groups_for_prefix(ranges, p) for p in prefixes]
    present = [c for c in counts if c]

    cols = column_bytes(NAMES_PATH)
    stats = {
        "rows": md.num_rows,
        "size": size,
        "bytes_per_row": round(size / md.num_rows, 2),
        "row_groups": md.num_row_groups,
        "row_group_rows": NAMES_ROW_GROUP_ROWS,
        "mean_row_group_bytes": int(size / md.num_row_groups),
        "footer_bytes": footer,
        "page_index_bytes": page_index,
        "prefixes": len(prefixes),
        "groups_per_prefix": {
            "min": min(present),
            "median": int(statistics.median(present)),
            "mean": round(statistics.fmean(present), 2),
            "p95": sorted(present)[int(0.95 * (len(present) - 1))],
            "max": max(present),
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(stats, indent=2) + "\n")

    per_group = size / md.num_row_groups
    gpp = stats["groups_per_prefix"]
    lines = [
        "# Gazetteer index measurements",
        "",
        "Generated by `tools/measure_index.py` against the built index. Every",
        "number here is measured, and every claim the collection README makes",
        "about what a lookup costs points back at this file. Rerun it after any",
        "rebuild.",
        "",
        "## The file",
        "",
        "| | |",
        "|---|---|",
        f"| Rows | {md.num_rows:,} |",
        f"| Size | {size:,} bytes ({human(size)}) |",
        f"| Bytes per row | {stats['bytes_per_row']} |",
        f"| Row groups | {md.num_row_groups:,} of "
        f"{NAMES_ROW_GROUP_ROWS:,} rows |",
        f"| Mean row group | {int(per_group):,} bytes ({human(per_group)}) |",
        f"| Footer | {footer:,} bytes |",
        f"| Page index | {page_index:,} bytes |",
        "",
        "## What the first keystroke costs",
        "",
        "A range client reads the footer before it can read any row group, and",
        f"the manifest declares `index.size` so that read is one exactly-sized "
        f"tail request of {footer:,} bytes rather than hyparquet's speculative "
        "512 KB default. The page index sits before the footer and is read",
        "lazily, per column chunk, only by a reader that wants a page rather",
        "than a whole chunk.",
        "",
        f"So a cold first lookup is about {human(footer + per_group)}: the "
        f"footer plus one row group. Every later keystroke that keeps the same "
        "two-letter prefix stays inside the same row group, which the client",
        "already holds.",
        "",
        "## What a keystroke costs, per prefix",
        "",
        f"Measured over all {len(prefixes):,} two-character prefixes that occur",
        "in `name_norm`: how many row groups can hold a match, which is how",
        "many range requests a client makes.",
        "",
        "| | row groups |",
        "|---|---|",
        f"| minimum | {gpp['min']} |",
        f"| median | {gpp['median']} |",
        f"| mean | {gpp['mean']} |",
        f"| 95th percentile | {gpp['p95']} |",
        f"| maximum | {gpp['max']} |",
        "",
        f"At {human(per_group)} per group, the median prefix therefore costs",
        f"about {human(gpp['median'] * per_group)} and the worst about "
        f"{human(gpp['max'] * per_group)}.",
        "",
        "## Where the bytes go",
        "",
        "Compressed bytes per column, whole file.",
        "",
        "| column | bytes | share |",
        "|---|---|---|",
    ]
    total = sum(v for _, v in cols)
    for name, value in cols:
        lines.append(
            f"| `{name}` | {value:,} | {100 * value / total:.1f}% |"
        )
    lines += [
        "",
        "## Why the row groups are this size",
        "",
        "The index contract asks for 100-150 KiB per row group, and that is",
        "the right target for the 2.5 MB index it was measured on, where the",
        "Parquet footer is a rounding error. It is the wrong target here. The",
        "footer carries one thrift record per column per row group, and a",
        "range client reads the whole footer before it can read anything, so",
        "shrinking the groups grows what the first keystroke costs. The rule",
        "is to minimize *footer plus page index plus one row group*, not to",
        "hit a row-group size.",
        "",
        f"At {NAMES_ROW_GROUP_ROWS:,} rows per group this index lands at",
        f"{human(per_group)} per group with a {human(footer)} footer. Halving",
        "the group size would roughly double the footer, which a client pays",
        "on every cold start, to halve a per-keystroke cost it mostly does not",
        "pay because consecutive keystrokes share a group.",
        "",
    ]
    verify = hyparquet_report()
    if verify:
        lines += [
            "## Read back with hyparquet, which is what a browser uses",
            "",
            "`tools/verify_index_hyparquet.mjs` opens the built file with",
            "[hyparquet](https://github.com/hyparam/hyparquet) and",
            "[hyparquet-compressors](https://github.com/hyparam/hyparquet-compressors),",
            "counting every byte the reader asks for. PyArrow reading its own",
            "output proves less than a different implementation reading it,",
            "and this is the implementation a browser client actually runs.",
            "The compressors package is **required**: every column chunk is",
            "zstd.",
            "",
            "```",
            verify.rstrip(),
            "```",
            "",
            "`population` is INT64, so hyparquet hands it back as a BigInt. A",
            "client sorting on it has to coerce with `Number()`; mixing it",
            "with a plain number throws.",
            "",
        ]
    OUT_MD.write_text(wrap_markdown("\n".join(lines)) + "\n")
    print(f"wrote {OUT_MD.relative_to(REPO)} and {OUT_JSON.relative_to(REPO)}")
    print(
        f"  {md.num_rows:,} rows, {human(size)}, {md.num_row_groups:,} groups "
        f"of {NAMES_ROW_GROUP_ROWS:,} ({human(per_group)} each)"
    )
    print(
        f"  prefix -> row groups: min {gpp['min']}, median {gpp['median']}, "
        f"p95 {gpp['p95']}, max {gpp['max']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
