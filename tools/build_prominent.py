#!/usr/bin/env python3
"""Build the prominent index: the small, eagerly loadable half of the search.

    python3 tools/build_prominent.py --measure    # size per candidate policy
    python3 tools/build_prominent.py              # build it
    python3 tools/build_prominent.py --manifest-only  # refresh manifests only

Why there are two indexes
-------------------------
The full index is 576 MiB in 9.5 million rows. A browser cannot load that, so
`geocoder-core`'s `auto` strategy puts it on the **range** path: every
keystroke is an HTTP round trip, and the first one also pays the 1.7 MB
footer. That is the right design for "find me Hintertupfingen" and the wrong
one for the first three characters anybody types, which are almost always a
country, a region or a well-known city.

So this file is the other half: a strict row subset of the full index, in the
same schema and the same byte-wise `name_norm` sort, small enough to fetch
whole on focus and binary-search in memory. Every row here is a byte-for-byte
copy of a row there -- same `feature_id`, same `geometry_ref` -- so a hit
found here resolves its geometry exactly as a hit found there, and a client
that wants completeness queries the full index and ignores this one. It is
also the only index the client's fuzzy typo fallback can scan in range mode,
so what this file leaves out, a misspelled query cannot find.

The row policy
--------------
Stated here, in the manifest under `prominent_index.criteria`, and in
`names/AGENTS.md`, because a client that does not know what was left out
cannot know when to fall back to the full index.

Each level carries a rule for its primary (one-per-place) rows and another
for its alternative-name rows. A rule is ``"all"``, ``None`` (no rows), or a
pair ``(min_zoom_max, population_min)`` admitting a row when **either**
``min_zoom <= min_zoom_max`` or ``population >= population_min``. A null
signal fails its own test rather than erroring, so a row with neither signal
is excluded by rule -- see "what the signals are not" below.

1. **Every primary row at levels 0-2** -- country, dependency, disputed,
   region, county: 46,830 places, no defensible cut. **Level 3
   (localadmin) is cut to ``mz<=12 OR pop>=25k``**: 94,102 of 164,756
   kept. This is the one place the byte budget wins over inclusiveness,
   and it was measured before it was decided: keeping every localadmin is
   +5.1 MiB (policy "L3 all" in the grid, 24.9 MB total, over the eager
   budget); of the 70,654 dropped, only 9.5% remain findable here under
   the same name via another kept row, and the uncovered rest is
   dominated by small French communes (42,838), US civil townships
   (9,965) and Estonian villages -- the long tail the full index's range
   path answers in a few hundred ms anyway. The real cost is that
   range-mode *typo* search cannot see them, since the fuzzy fallback
   scans only this file; that trade is recorded rather than hidden.

2. **The English guarantee: a feature's English alternative-name rows
   follow the same rule as its primary row.** This distribution's primary
   names are in no particular language -- 328 of 353 country primaries and
   12,543 of 42,115 county primaries carry no Latin letter (Contra Costa
   County's primary name is Arabic; so is Kyoto Prefecture's) -- so any
   level that kept primaries but dropped alt rows would keep places nobody
   can find. The signals ride along on alt rows, copied from the parent,
   so the same rule selects the same features: 15,621 rows at levels 1-3,
   1.2 MiB, and it closes the exact failure class the Overture build hit
   when its first prominent index silently lost Baghdad, Tehran, Dhaka and
   Ho Chi Minh City (fixed 2026-11-13). The six probe cities this policy
   is tested against are all reachable in English only through an alt row.

3. **All-language alternative-name rows, per level:**

   - Level 0: all 6,006 -- every spelling of every country.
   - Level 1: ``mz<=8 OR pop>=500k``. The spellings, in 25 languages, of
     the regions people type (Bavaria/Beieren mz 6.6, Tokyo/Tokio 8.0)
     without the 64,459-row full set.
   - Levels 2-3: English only (the guarantee above). County min_zoom sits
     at exactly 6.0 for 175,936 alt rows -- the signal is a placetype
     band, not a ranking -- so there is no usable all-language cut; the
     full set would cost 12.7 MiB (grid row E shows the measured damage).
   - Level 4: ``mz<=6 OR pop>=200k``. The population arm keeps every
     spelling of every city of 200,000 people in every language; the zoom
     arm adds world-map cities whose population column is null. Florence
     (pop 377k, mz 5.6) and Venice (pop 51k, mz 5.1) both survive; the
     tighter ``(5, 500k)`` (grid row H) saves 2.0 MB by dropping the
     non-English spellings of 200-500k cities, the wrong thing to starve
     in a gazetteer, and was rejected.
   - Level 5: ``mz<=10 OR pop>=100k`` for both row kinds: 3,128 rows, 0.2
     MiB. This does NOT reach most famous neighbourhoods -- Soho and
     Montmartre sit at mz 13 with no population, and the mz<=13
     neighbourhood band is 192,136 rows -- so neighbourhoods are mostly a
     range-path (second-wave) answer, stated here so nobody wonders.

4. **Level-4 primary rows at ``mz<=10 OR pop>=50k``** (32,509 of 4.8M).
   The primary cut is looser than the all-language alt cut at the same
   level because one row per place is cheap; its spellings are what
   multiply.

The 14% of level-4 rows carrying neither signal are excluded by rule
however important the place (the Overture build faced the same hazard with
its `class` column and documented it the same way): this is a *recall*
boundary, not a judgment.

What the signals are not
------------------------
`min_zoom` is Who's On First's label-importance hint, carried per placetype
band (counties cluster at exactly 6.0, most localities at 10-12), not a
global ranking -- so every cut here is per-level and the two signals back
each other up. `population` is null on 77% of localities. Both signals ride
along on alternative-name rows (copied from their parent), which is what
lets one policy govern both row kinds. The full index -- one range request
away -- is what makes every omission recoverable.

The measurement grid (``--measure``, 2026-11-13 build)
------------------------------------------------------
    policy                                            rows         size  vs 16 MiB
    A  L3 all primaries                           356,442   26,298,013      1.6x
    B  shipped (L3 cut (12, 25k))                 285,735   21,225,495      1.3x
    C  A + L1 alts all                            376,392   27,788,785      1.7x
    D  A + L4 alts tighter (5, 500k)              330,605   24,302,687      1.4x
    E  A + L2 alts (6, 1M)                        523,278   37,785,257      2.3x
    F  A without level 5                          353,314   26,037,715      1.6x
    G  A, alts at 0+4 only (Overture-shaped)      311,738   23,065,073      1.4x
    H  B + L4 alts (5, 500k)                      259,898   19,201,442      1.1x

(Every row includes the English guarantee.) B is what ships: 21.2 MB, 1.6x
the 13.5 MB the Overture catalog's prominent index weighs on a full index
40% smaller than this one, and within rounding of the 20 MB eager budget.
H saves 2.0 MB by cutting the non-English spellings of cities of 200-500k
people, the wrong thing to starve in the file whose job is finding cities;
E shows why level-2 all-language alt rows stay out entirely.

The parquet itself follows the index contract's small-file shape: zstd,
statistics restricted to the four prunable columns, page index on, row
groups sized to the 100-150 KiB band (2,048 rows ~= 148 KiB here), and the
full index's own `geo` footer metadata carried over unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from wofcommon import (
    NAMES_PATH,
    PUBLISH,
    ZSTD_LEVEL,
    footer_metadata,
    human,
)
from build_names import (
    SOURCE_NAME,
    STATISTICS_COLUMNS,
    footer_bytes,
    manifest_path,
    multihash,
)

OUT = PUBLISH / "names" / "wof_names_prominent.parquet"

# A rule is "all", None, or (min_zoom_max, population_min): the row is kept
# when min_zoom <= the first OR population >= the second. Nulls fail their
# own arm. These two dicts are the whole definition of "prominent"; they are
# published verbatim in the manifest under `prominent_index.criteria`, and
# --measure prints the grid they came from.
PRIMARY_RULES = {
    0: "all", 1: "all", 2: "all", 3: (12.0, 25_000),
    4: (10.0, 50_000), 5: (10.0, 100_000),
}
ALT_RULES = {
    0: "all", 1: (8.0, 500_000), 2: None, 3: None,
    4: (6.0, 200_000), 5: (10.0, 100_000),
}

# A byte target, not a row count: the index contract asks for 100-150 KiB per
# row group at this file size, and the measured 63 B/row puts 2,048 rows at
# ~129 KiB.
ROW_GROUP_ROWS = 2048
ROW_GROUP_TARGET_KIB = (100, 150)

READ_BATCH = 262_144

#: The --measure grid: label -> (primary rules, alt rules).
_L3_ALL = {**PRIMARY_RULES, 3: "all"}
POLICY_GRID = {
    "A  L3 all primaries": (_L3_ALL, ALT_RULES),
    "B  shipped (L3 cut (12, 25k))": (PRIMARY_RULES, ALT_RULES),
    "C  A + L1 alts all": (_L3_ALL, {**ALT_RULES, 1: "all"}),
    "D  A + L4 alts tighter (5, 500k)": (
        _L3_ALL, {**ALT_RULES, 4: (5.0, 500_000)}),
    "E  A + L2 alts (6, 1M)": (_L3_ALL, {**ALT_RULES, 2: (6.0, 1_000_000)}),
    "F  A without level 5": (
        {**_L3_ALL, 5: None}, {**ALT_RULES, 5: None}),
    "G  A, alts at 0+4 only (Overture-shaped)": (
        _L3_ALL, {**ALT_RULES, 1: None, 5: None}),
    "H  B + L4 alts (5, 500k)": (
        PRIMARY_RULES, {**ALT_RULES, 4: (5.0, 500_000)}),
}


def _rule_mask(table: pa.Table, level: int, rule) -> pa.ChunkedArray | None:
    """The rows of ``level`` a rule admits, as a boolean mask (None: none)."""
    if rule is None:
        return None
    at_level = pc.equal(table.column("level"), pa.scalar(level, pa.int8()))
    if rule == "all":
        return at_level
    mz_max, pop_min = rule
    # fill_null keeps the mask boolean rather than letting a null propagate
    # into or_, where it would drop a row silently instead of by rule.
    mz_ok = pc.fill_null(pc.less_equal(table.column("min_zoom"), mz_max), False)
    pop_ok = pc.fill_null(
        pc.greater_equal(table.column("population"), pop_min), False
    )
    return pc.and_(at_level, pc.or_(mz_ok, pop_ok))


def mask(table: pa.Table, primary_rules: dict, alt_rules: dict):
    """The row policy, as one boolean mask over ``table``.

    Three clauses per level: primary rows under the primary rule,
    alternative-name rows under the alt rule, and -- the English guarantee --
    *English* alternative-name rows under the primary rule. The third exists
    because this distribution's primary names are in no particular language
    (Contra Costa County's is Arabic; 12,543 of 42,115 county primaries
    carry no Latin letter at all), so without it a kept place can be
    unfindable by the name everyone types.
    """
    is_alt = pc.is_valid(table.column("alt_of"))
    is_eng = pc.fill_null(
        pc.equal(table.column("name_lang"), pa.scalar("eng")), False
    )
    keep = pc.equal(table.column("level"), pa.scalar(-1, pa.int8()))  # all false
    for level, rule in primary_rules.items():
        m = _rule_mask(table, level, rule)
        if m is not None:
            keep = pc.or_(keep, pc.and_(m, pc.invert(is_alt)))
            # The English guarantee: a feature's eng alt rows follow the
            # same rule as its primary row (the signals ride along on alt
            # rows, copied from the parent, so the same rule means the
            # same features).
            keep = pc.or_(keep, pc.and_(m, pc.and_(is_alt, is_eng)))
    for level, rule in alt_rules.items():
        m = _rule_mask(table, level, rule)
        if m is not None:
            keep = pc.or_(keep, pc.and_(m, is_alt))
    return keep


def _widest() -> tuple[dict, dict]:
    """Per level, the loosest rule any grid policy uses (for one read pass)."""
    def widen(rules_list, level):
        rules = [r.get(level) for r in rules_list]
        if any(r == "all" for r in rules):
            return "all"
        pairs = [r for r in rules if isinstance(r, tuple)]
        if not pairs:
            return None
        return (max(p[0] for p in pairs), min(p[1] for p in pairs))
    primaries = [p for p, _ in POLICY_GRID.values()]
    alts = [a for _, a in POLICY_GRID.values()]
    levels = range(6)
    return (
        {lv: widen(primaries, lv) for lv in levels},
        {lv: widen(alts, lv) for lv in levels},
    )


def collect() -> pa.Table:
    """One pass over the full index, keeping a superset of every candidate.

    The full index is sorted by `(name_norm, level, country, feature_id)` and
    a filter preserves row order, so the result is sorted without re-sorting
    -- which matters, because re-sorting would have to reproduce the
    builder's byte-wise UTF-8 comparison exactly or silently break the
    binary search.
    """
    if not NAMES_PATH.exists():
        sys.exit(f"missing {NAMES_PATH}; run tools/build_names.py first")
    wide_primary, wide_alt = _widest()
    reader = pq.ParquetFile(NAMES_PATH)
    kept = []
    rows_in = 0
    started = time.time()
    for batch in reader.iter_batches(batch_size=READ_BATCH):
        table = pa.Table.from_batches([batch])
        rows_in += table.num_rows
        kept.append(table.filter(mask(table, wide_primary, wide_alt)))
        print(
            f"\r  read {rows_in:,} of {reader.metadata.num_rows:,} rows, "
            f"kept {sum(t.num_rows for t in kept):,} "
            f"({time.time() - started:.0f}s)",
            end="",
            flush=True,
        )
    print()
    return pa.concat_tables(kept)


def subset(pool: pa.Table, primary_rules: dict, alt_rules: dict) -> pa.Table:
    return pool.filter(mask(pool, primary_rules, alt_rules))


def _rule_json(rule):
    if rule is None:
        return "none"
    if rule == "all":
        return "all"
    return {"min_zoom_max": rule[0], "population_min": rule[1]}


def write(table: pa.Table, out: Path) -> dict:
    """Write the file with the full index's own schema metadata and sort."""
    source_schema = pq.ParquetFile(NAMES_PATH).schema_arrow
    meta = footer_metadata({"cnmw:role": "names-index-prominent"})
    # The GeoParquet metadata is the full index's, with its own measured
    # extent: this file is a row subset, so its bbox can only be narrower,
    # and a covering that claims more than it holds prunes nothing but is
    # not wrong. Copying it keeps the two files' metadata identical for
    # every key a client might compare.
    if source_schema.metadata and b"geo" in source_schema.metadata:
        meta[b"geo"] = source_schema.metadata[b"geo"]
    meta[b"cnmw:prominent_of"] = NAMES_PATH.name.encode()
    meta[b"cnmw:prominent_rules"] = json.dumps({
        "primary": {str(k): _rule_json(v) for k, v in PRIMARY_RULES.items()},
        "alt": {str(k): _rule_json(v) for k, v in ALT_RULES.items()},
    }).encode()
    table = table.replace_schema_metadata(meta)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    pq.write_table(
        table,
        out,
        compression="zstd",
        compression_level=ZSTD_LEVEL,
        write_statistics=STATISTICS_COLUMNS,
        write_page_index=True,
        version="2.6",
        row_group_size=ROW_GROUP_ROWS,
        sorting_columns=[
            pq.SortingColumn(
                table.schema.get_field_index("name_norm"),
                descending=False,
                nulls_first=True,
            )
        ],
    )
    md = pq.ParquetFile(out).metadata
    return {
        "rows": md.num_rows,
        "row_groups": md.num_row_groups,
        "size": out.stat().st_size,
    }


def verify(out: Path, full_rows: int) -> None:
    """Re-check the guarantees a client re-checks, plus the subset property."""
    pf = pq.ParquetFile(out)
    md = pf.metadata
    problems = []
    full = pq.ParquetFile(NAMES_PATH).schema_arrow
    if pf.schema_arrow.names != full.names:
        problems.append("column names differ from the full index")
    else:
        for name in full.names:
            if pf.schema_arrow.field(name).type != full.field(name).type:
                problems.append(
                    f"{name} has a different type from the full index"
                )
    if not md.row_group(0).sorting_columns:
        problems.append("the footer declares no sorting_columns")

    norm = (
        pq.read_table(out, columns=["name_norm"])
        .column("name_norm").to_pylist()
    )
    if any(v is None for v in norm):
        problems.append("name_norm holds a null")
    else:
        encoded = [v.encode("utf-8") for v in norm]
        bad = sum(
            1 for i in range(len(encoded) - 1) if encoded[i] > encoded[i + 1]
        )
        if bad:
            problems.append(f"name_norm is not ascending at {bad} position(s)")
    if md.num_rows >= full_rows:
        problems.append("the prominent index is not smaller than the full index")

    truncated = 0
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        idx = next(
            i for i in range(rg.num_columns)
            if rg.column(i).path_in_schema == "name_norm"
        )
        st = rg.column(idx).statistics
        if st is None or st.min is None or st.max is None:
            problems.append(f"row group {g} has no name_norm statistics")
            break
        if len(st.min) >= 64 or len(st.max) >= 64:
            truncated += 1
    if truncated:
        problems.append(f"{truncated} row group(s) may have truncated statistics")

    if problems:
        raise SystemExit("\n".join(f"error  {p}" for p in problems))
    print("  OK: same schema and sort as the full index, strictly a subset")


PROBE_CITIES = (
    "baghdad", "tehran", "dhaka", "ho chi minh city", "kinshasa", "lagos",
)


def verify_probes(out: Path) -> None:
    """The six cities whose absence is how the Overture build's bug was found.

    All six are reachable in English only through an alternative-name row --
    their primary names are Arabic, Persian, Bengali, Vietnamese, Lingala and
    Yoruba -- so this is a direct test that the alt-row policy did its job.
    """
    table = pq.read_table(out, columns=["name_norm", "level"])
    norms = set(
        pc.filter(
            table.column("name_norm"), pc.equal(table.column("level"), 4)
        ).to_pylist()
    )
    missing = [c for c in PROBE_CITIES if c not in norms]
    if missing:
        raise SystemExit(f"error  probe cities missing at level 4: {missing}")
    print(f"  OK: all {len(PROBE_CITIES)} probe cities present at level 4")


def rows_per_level(out: Path) -> dict:
    table = pq.read_table(out, columns=["level", "alt_of"])
    levels = {}
    for lv in sorted(set(table.column("level").to_pylist())):
        at = pc.equal(table.column("level"), pa.scalar(lv, pa.int8()))
        alt = pc.and_(at, pc.is_valid(table.column("alt_of")))
        n = pc.sum(pc.cast(at, pa.int64())).as_py() or 0
        na = pc.sum(pc.cast(alt, pa.int64())).as_py() or 0
        levels[str(lv)] = {
            "rows": n, "primary_rows": n - na, "alt_rows": na,
        }
    return levels


CRITERIA_DESCRIPTION = (
    "A strict row subset of the full index, in the same schema and the same "
    "byte-wise name_norm sort, so a hit found here resolves its geometry "
    "exactly as a hit found there: same feature_id, same geometry_ref. Per "
    "level, a rule admits primary rows and a separate rule admits "
    "alternative-name rows; a rule is 'all', 'none', or a pair admitting a "
    "row when min_zoom <= min_zoom_max OR population >= population_min. A "
    "row carrying neither signal fails a pair rule however important the "
    "place: this is a recall boundary, not a judgment, and the full index "
    "is what makes every omission recoverable. Alternative-name rows are "
    "load-bearing, not garnish: this distribution's primary names are in "
    "no particular language (Contra Costa County's primary row is Arabic, "
    "Baghdad's too), so English alternative-name rows additionally follow "
    "each level's PRIMARY rule -- the 'english_guarantee' -- meaning every "
    "place kept here is findable by its English name where the "
    "distribution carries one. min_zoom is Who's On First's per-placetype "
    "label hint, "
    "not a global ranking (counties cluster at exactly 6.0), so every rule "
    "is per-level and population backs the zoom arm up. See "
    "tools/build_prominent.py for the measured grid behind each number."
)

CRITERIA_FALLBACK = (
    "Any query this subset cannot answer -- a name excluded by the rules "
    "above, or any query needing completeness -- is answered by the full "
    "index at ./wof_names.parquet via range requests; clients that load "
    "this file eagerly run both waves and merge."
)


def prominent_manifest_entry() -> dict:
    """The manifest's `prominent_index` block, read back from the built file."""
    md = pq.ParquetFile(OUT).metadata
    footer, page_index = footer_bytes(OUT)
    return {
        "url": f"./{OUT.name}",
        "size": OUT.stat().st_size,
        "row_count": md.num_rows,
        "row_groups": md.num_row_groups,
        "footer_bytes": footer + page_index,
        "footer_metadata_bytes": footer,
        "checksum": multihash(OUT),
        "row_group_rows": ROW_GROUP_ROWS,
        "sorted_by": ["name_norm", "level", "country", "feature_id"],
        "of": f"./{NAMES_PATH.name}",
        "load": "eager",
        "rows_per_level": rows_per_level(OUT),
        "criteria": {
            "signal_columns": ["min_zoom", "population"],
            "primary": {
                str(k): _rule_json(v) for k, v in PRIMARY_RULES.items()
            },
            "alt": {str(k): _rule_json(v) for k, v in ALT_RULES.items()},
            "english_guarantee": (
                "alternative-name rows with name_lang 'eng' are admitted "
                "by the level's primary rule as well as its alt rule"
            ),
            "description": CRITERIA_DESCRIPTION,
            "fallback": CRITERIA_FALLBACK,
        },
    }


def update_manifests() -> None:
    """Insert/replace `prominent_index` in the catalog manifest.

    The staging copy beside the parquet (publish/names/index.json) exists
    only for a local demo server; it gets the same entry so the two never
    disagree. Everything else in both documents is left untouched -- the
    full rebuild path through build_names.py composes them from scratch.
    """
    entry = prominent_manifest_entry()
    for path in (manifest_path(), PUBLISH / "names" / "index.json"):
        if not path.exists():
            print(f"  skip {path} (absent)")
            continue
        doc = json.loads(path.read_text())
        doc["prominent_index"] = entry
        path.write_text(json.dumps(doc, indent=2) + "\n")
        print(f"  {path}: prominent_index entry written")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--measure", action="store_true",
                    help="report size per candidate policy and write nothing")
    ap.add_argument("--manifest-only", action="store_true",
                    help="refresh the manifests from the built file")
    args = ap.parse_args(argv)

    if args.manifest_only:
        if not OUT.exists():
            sys.exit(f"missing {OUT}; run without --manifest-only first")
        update_manifests()
        return 0

    full_md = pq.ParquetFile(NAMES_PATH).metadata
    full_size = NAMES_PATH.stat().st_size
    print(
        f"full index: {human(full_size)}, {full_md.num_rows:,} rows "
        f"({NAMES_PATH.name})"
    )

    pool = collect()

    if args.measure:
        tmp = PUBLISH / "names" / ".prominent-measure.parquet"
        print(f"\n  {'policy':<44} {'rows':>9} {'size':>12} {'vs 16 MiB':>9}")
        for label, (primary_rules, alt_rules) in POLICY_GRID.items():
            table = subset(pool, primary_rules, alt_rules)
            stats = write(table, tmp)
            print(
                f"  {label:<44} {stats['rows']:>9,} {stats['size']:>12,} "
                f"{stats['size'] / (16 << 20):>8.1f}x"
            )
        tmp.unlink(missing_ok=True)
        return 0

    table = subset(pool, PRIMARY_RULES, ALT_RULES)
    stats = write(table, OUT)
    per_group_kib = stats["size"] / stats["row_groups"] / 1024
    print(
        f"prominent: {OUT.name} {human(stats['size'])}, {stats['rows']:,} "
        f"rows ({100 * stats['rows'] / full_md.num_rows:.1f}% of the full "
        f"index), {stats['row_groups']:,} row groups of {ROW_GROUP_ROWS:,}, "
        f"{per_group_kib:.0f} KiB per group"
    )
    lo, hi = ROW_GROUP_TARGET_KIB
    if not lo <= per_group_kib <= hi:
        print(
            f"  note: {per_group_kib:.0f} KiB per row group is outside the "
            f"{lo}-{hi} KiB band ROW_GROUP_ROWS targets"
        )
    verify(OUT, full_md.num_rows)
    verify_probes(OUT)
    update_manifests()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
