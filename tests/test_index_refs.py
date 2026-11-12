#!/usr/bin/env python3
"""The index's `geometry_ref` pointers into the boundary files have to be right.

This is the catalog's load-bearing claim for the `select()` fast path
(`names/AGENTS.md`, "The geometry_ref fast path, and why it must be
verified"). `geometry_ref` names a file, a row group and a row; a client
range-reads that row group and takes that row. If the pointer is stale or
wrong, the client gets **another place's polygon** and nothing looks wrong:
the geometry is valid, the bbox is plausible, and the map flies somewhere
else. No schema validator catches it — only resolving the pointer against the
actual boundary files does.

Four things are checked, all against the built files:

1. `row // row_group_rows` equals the published `row_group`, with
   `row_group_rows` taken from the manifest rather than from the build's own
   constants, so the manifest a client reads is what gets checked.
2. The row at that offset in the level's boundary file carries the expected
   `wof_id`.
3. Where a display companion exists, the same offset in it carries the same
   `wof_id` — which is what makes one pointer valid against either file.
4. Every file the manifest names declares the same `cnmw:catalog_version` in
   its Parquet footer as the manifest does, which is the version pin
   `select()` checks before it trusts a pointer at all.

It needs the built data, which lives outside git (`WOF_STAGING`). When the
staging tree is absent it skips, which is what happens in CI. Run it locally
after any rebuild:

    python3 tests/test_index_refs.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

try:
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    print("skip: pyarrow is not installed")
    raise SystemExit(0)

from wofcommon import CNMW_VERSION_KEY, NAMES_PATH, PUBLISH  # noqa: E402

MANIFEST = ROOT / "catalog" / "names" / "index.json"
# Sampling rather than exhaustive: resolving every one of 9.5 million pointers
# means reading every boundary file end to end. A random sample per level
# catches a systematic error, which is the only kind this can have -- the
# offsets come from one `file_row_number` read, so either the arithmetic is
# right for all of them or it is wrong for all of them.
SAMPLE_PER_LEVEL = 200
SEED = 20261112

errors: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def resolve(path: Path, row: int, column: str = "wof_id"):
    """The value at a physical row offset, read a row group at a time."""
    reader = pq.ParquetFile(path)
    md = reader.metadata
    seen = 0
    for group in range(md.num_row_groups):
        rows = md.row_group(group).num_rows
        if seen + rows > row:
            table = reader.read_row_group(group, columns=[column])
            return table.column(column)[row - seen].as_py(), group
        seen += rows
    return None, None


def main() -> int:
    if not NAMES_PATH.exists():
        print(f"skip: {NAMES_PATH} is absent (no staging tree)")
        return 0
    if not MANIFEST.exists():
        print(f"skip: {MANIFEST} is absent")
        return 0

    manifest = json.loads(MANIFEST.read_text())
    by_level = {entry["level"]: entry for entry in manifest["boundaries"]}
    version = manifest["catalog_version"]

    # 4. The version pin, in every file the manifest names.
    paths = [NAMES_PATH]
    for entry in manifest["boundaries"]:
        for role in ("full", "display"):
            if role in entry:
                paths.append(
                    (PUBLISH / "names" / entry[role]["url"]).resolve()
                )
    for path in paths:
        if not path.exists():
            fail(f"{path} is named by the manifest but is not on disk")
            continue
        meta = pq.ParquetFile(path).schema_arrow.metadata or {}
        declared = meta.get(CNMW_VERSION_KEY.encode())
        if declared is None:
            fail(f"{path.name} carries no {CNMW_VERSION_KEY} footer metadata")
        elif declared.decode() != version:
            fail(
                f"{path.name} declares {declared.decode()!r}, the manifest "
                f"says {version!r}"
            )

    # 1-3. The pointers themselves.
    random.seed(SEED)
    index = pq.read_table(
        NAMES_PATH,
        columns=["feature_id", "level", "geometry_ref", "alt_of"],
    )
    rows = index.to_pylist()
    checked = 0
    for level, entry in sorted(by_level.items()):
        candidates = [
            r for r in rows if r["level"] == level and r["alt_of"] is None
        ]
        if not candidates:
            fail(f"level {level} has no primary rows in the index")
            continue
        sample = random.sample(
            candidates, min(SAMPLE_PER_LEVEL, len(candidates))
        )
        group_rows = entry["row_group_rows"]
        full = (PUBLISH / "names" / entry["full"]["url"]).resolve()
        display = (
            (PUBLISH / "names" / entry["display"]["url"]).resolve()
            if "display" in entry else None
        )
        for row in sample:
            ref = row["geometry_ref"]
            if ref is None:
                fail(f"level {level}: {row['feature_id']} has no geometry_ref")
                continue
            if ref["file"] != entry["collection"]:
                fail(
                    f"level {level}: geometry_ref.file is {ref['file']!r}, "
                    f"the manifest's collection is {entry['collection']!r}"
                )
                continue
            if ref["row"] // group_rows != ref["row_group"]:
                fail(
                    f"level {level}: row {ref['row']} // {group_rows} is "
                    f"{ref['row'] // group_rows}, published row_group is "
                    f"{ref['row_group']}"
                )
                continue
            found, group = resolve(full, ref["row"])
            if found != row["feature_id"]:
                fail(
                    f"level {level}: {full.name} row {ref['row']} holds "
                    f"wof_id {found!r}, the index says {row['feature_id']!r}"
                )
                continue
            if group != ref["row_group"]:
                fail(
                    f"level {level}: row {ref['row']} of {full.name} is in "
                    f"row group {group}, published row_group is "
                    f"{ref['row_group']}"
                )
                continue
            if display is not None:
                shown, _ = resolve(display, ref["row"])
                if shown != row["feature_id"]:
                    fail(
                        f"level {level}: {display.name} row {ref['row']} "
                        f"holds wof_id {shown!r}, not {row['feature_id']!r}; "
                        "the display file is not row-aligned"
                    )
                    continue
            checked += 1

    if errors:
        print(f"error  {len(errors)} problem(s):")
        for message in errors[:20]:
            print(f"  {message}")
        return 1
    print(
        f"OK: {checked:,} geometry_ref pointer(s) resolved to the right row "
        f"in {len(by_level)} boundary file(s), and {len(paths)} file(s) "
        f"declare catalog_version {version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
