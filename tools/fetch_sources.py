#!/usr/bin/env python3
"""Stage geocode.earth's combined admin GeoParquet, and verify what arrived.

    python3 tools/fetch_sources.py           # download if absent, then verify
    python3 tools/fetch_sources.py --verify  # verify what is already staged

This is the only step that moves the 5.5 GiB upstream file. Everything after
it reads the staged copy, so the catalog's numbers and geocode.earth's bytes
cannot drift apart inside one build.

**The download does not resume, deliberately.** Two things were measured
against this host on 2026-11-12 and they combine badly. First, Cloudflare
closed the connection part-way through on two of three attempts, and `curl`
exits 0 on a short read, so a naive single attempt silently stages a
truncated file. Second, the host sometimes answers a `Range` request with a
`200` and the whole body instead of a `206` -- so `curl -C -`, which appends
from the current file size, appended a second whole copy and produced a
9,164,361,132-byte file where 5,948,636,588 was expected. Resume is therefore
unsafe here. Each attempt downloads to a temporary path from scratch, the size
is checked against the host's own `Content-Length`, and only an exact match is
moved into place.

The verification is deliberately not a comparison against geocode.earth's
inventory digest. `parquet/inventory.json` records this object as last
modified 2025-04-07 with WOF tree hash 1a746740..., while the sqlite, spatial,
bundle and PMTiles builds of the same repo record 56b0ba18... from
2025-10-14, and the object's own Last-Modified is 2025-10-30. The object was
replaced after its inventory entry was written, so the inventory's
sha256_compressed is stale for this file. This script therefore records the
digest of the bytes it actually read, which is what the catalog quotes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wofcommon import (  # noqa: E402
    SOURCES,
    UPSTREAM_PARQUET,
    UPSTREAM_PARQUET_BYTES,
    UPSTREAM_PARQUET_NAME,
    WORK,
    human,
)

DEST = SOURCES / UPSTREAM_PARQUET_NAME
RECORD = WORK / "source-record.json"
MAX_ATTEMPTS = 12


def declared_size() -> int:
    """The object's Content-Length, straight from the host."""
    out = subprocess.run(
        ["curl", "-sI", UPSTREAM_PARQUET], capture_output=True, text=True,
        check=True,
    ).stdout
    for line in out.splitlines():
        if line.lower().startswith("content-length:"):
            return int(line.split(":", 1)[1].strip())
    sys.exit("the host sent no Content-Length; refusing to guess the size")


def download(target: int) -> None:
    SOURCES.mkdir(parents=True, exist_ok=True)
    if DEST.exists() and DEST.stat().st_size == target:
        print(f"  already staged: {human(target)}")
        return
    partial = DEST.with_suffix(DEST.suffix + ".part")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"  attempt {attempt}: fetching {human(target)} ...", flush=True)
        partial.unlink(missing_ok=True)
        subprocess.run(
            ["curl", "-sS", "-L", "--fail", "-o", str(partial),
             UPSTREAM_PARQUET],
            check=False,
        )
        have = partial.stat().st_size if partial.exists() else 0
        if have == target:
            partial.replace(DEST)
            return
        print(f"    got {have:,} bytes, expected {target:,}; retrying")
    partial.unlink(missing_ok=True)
    sys.exit(f"gave up after {MAX_ATTEMPTS} attempts")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--verify", action="store_true",
        help="verify the staged file without downloading anything",
    )
    args = ap.parse_args()

    target = UPSTREAM_PARQUET_BYTES
    if not args.verify:
        live = declared_size()
        if live != target:
            print(
                f"note: the host now declares {live:,} bytes, not the "
                f"{target:,} recorded in tools/wofcommon.py. The upstream "
                "file changed; update UPSTREAM_PARQUET_BYTES and rebuild.",
            )
            target = live
        download(target)

    if not DEST.exists():
        sys.exit(f"missing {DEST}; run without --verify to download it")
    size = DEST.stat().st_size
    if size != target:
        sys.exit(f"{DEST} is {size:,} bytes, expected {target:,}")

    print(f"  hashing {human(size)} ...", flush=True)
    digest = sha256(DEST)
    WORK.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(
        json.dumps(
            {
                "url": UPSTREAM_PARQUET,
                "bytes": size,
                "sha256": digest,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"source: {DEST.name} {size:,} bytes")
    print(f"  sha256 {digest}")
    print(f"  recorded in {RECORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
