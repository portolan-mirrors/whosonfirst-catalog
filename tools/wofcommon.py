#!/usr/bin/env python3
"""Shared constants and helpers for the Who's On First build.

Nothing here touches the published catalog. The build stages geocode.earth's
own downloads under ``sources/`` in the staging root, works in ``work/``, and
writes the few data files this catalog adds to ``publish/`` under the same
root, which ``catalog.publish.yaml`` names as ``data_dir``.
``tools/publish.py`` never reads that tree, so the publish boundary is
unchanged.

This catalog is metadata-first. Its boundary assets are geocode.earth's URLs,
not copies, so the only thing staged for upload is what a browser client
cannot get from there: the name search index and its manifest. See
``catalog/AGENTS.md``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path

# The staging root. Override with WOF_STAGING. It sits outside the repository
# because the staged download is gigabytes and git keeps every version of a
# binary forever.
_DEFAULT_STAGING = Path(__file__).resolve().parents[2] / "whosonfirst-staging"
STAGING = Path(os.environ.get("WOF_STAGING", _DEFAULT_STAGING))
SOURCES = STAGING / "sources"
WORK = STAGING / "work"
PUBLISH = STAGING / "publish"


def run(cmd: list[str] | str, **kw) -> None:
    """Run a command, echo it, and fail loudly."""
    shell = isinstance(cmd, str)
    printable = cmd if shell else " ".join(cmd)
    print(f"  $ {printable}", flush=True)
    subprocess.run(cmd, shell=shell, check=True, **kw)


# ---------------------------------------------------------------------------
# The upstream distribution
# ---------------------------------------------------------------------------
# geocode.earth builds Who's On First into several formats and serves them from
# data.geocode.earth. The human-facing index is
# https://geocode.earth/data/whosonfirst/combined/ , whose file list is fetched
# by its own JavaScript from the per-format inventory.json files below; the
# page's HTML carries no file links, which is why this catalog records the
# URLs rather than telling a reader to go and find them.
DIST_BASE = "https://data.geocode.earth/wof/dist"
DOWNLOAD_PAGE = "https://geocode.earth/data/whosonfirst/combined/"
PER_COUNTRY_PAGE = "https://geocode.earth/data/whosonfirst/"
WOF_LICENSE_PAGE = "https://whosonfirst.org/docs/licenses/"
WOF_PLACETYPES_PAGE = "https://whosonfirst.org/docs/placetypes/"

# The combined admin distribution, which is the one this catalog describes.
# `whosonfirst-data-admin` is geocode.earth's name for the union of the 260
# per-country whosonfirst-data-admin-* repositories.
UPSTREAM_REPO = "whosonfirst-data-admin"
UPSTREAM_PARQUET_NAME = f"{UPSTREAM_REPO}-latest.parquet"
UPSTREAM_PARQUET = f"{DIST_BASE}/parquet/{UPSTREAM_PARQUET_NAME}"
UPSTREAM_PMTILES = f"{DIST_BASE}/protomaps/{UPSTREAM_REPO}-latest.pmtiles"
UPSTREAM_SQLITE = f"{DIST_BASE}/sqlite/{UPSTREAM_REPO}-latest.db.bz2"
UPSTREAM_SPATIAL = f"{DIST_BASE}/spatial/{UPSTREAM_REPO}-latest.spatial.db.bz2"
UPSTREAM_BUNDLE = f"{DIST_BASE}/bundles/{UPSTREAM_REPO}-latest.tar.bz2"
PARQUET_INVENTORY = f"{DIST_BASE}/parquet/inventory.json"

# There are no versioned URLs. Every file geocode.earth publishes is named
# `-latest` and overwritten in place, and `vintage` is literally the string
# "latest", so nothing in a URL pins a version. Two things do.
#
# `parquet/inventory.json` is the authoritative vintage and integrity record:
# per file it carries `last_modified` (when the distribution was built),
# `last_updated` (the newest member repo's own commit date), `commit` (the WOF
# tree hash the build came from) and `sha256_compressed`.
#
# The HTTP `Last-Modified` header is NOT a vintage signal here. Every object
# under /wof/dist/ reports 2025-10-30T18:0x, including files whose inventory
# entries span 2024-01 to 2025-10, and every ETag is multipart-shaped -- the
# whole bucket was re-copied on that date. Reading the header as a data date
# would date the 2025-04 parquet build six months late.
#
# tools/fetch_sources.py re-asserts the size and digest below before it
# accepts a download. See docs/upstream-measurements.md.
UPSTREAM_PARQUET_BYTES = 5_948_636_588
UPSTREAM_PARQUET_SHA256 = (
    "f465c3a6507b407d060bec7cfa96e95e028d7cc13fbd06739f2cc5aa4ee6de11"
)
# From the parquet build's own inventory entry.
UPSTREAM_PARQUET_BUILT = "2025-04-07T13:07:59Z"
UPSTREAM_PARQUET_WOF_COMMIT = (
    "1a746740a8d4917d08327ac12bf280430523c07d89e36b32c6758fe771349291"
)
UPSTREAM_PARQUET_MEMBERS = 260

# The PMTiles, sqlite, spatial and GeoJSON-bundle builds of the same repo are
# six months NEWER than the parquet: 2025-10-14 against 2025-04-07, from a
# different WOF tree. A reader comparing a count from this catalog against a
# count from the sqlite distribution is comparing two vintages, and the
# catalog says so.
UPSTREAM_PMTILES_BYTES = 2_130_846_508
UPSTREAM_PMTILES_BUILT = "2025-10-14T15:28:42Z"
UPSTREAM_SQLITE_BUILT = "2025-10-14T10:19:29Z"
UPSTREAM_NEWER_WOF_COMMIT = (
    "56b0ba1827b627a955da1211443795b9765611f55008c4a028fe2c604027bc99"
)
UPSTREAM_NEWER_WOF_COMMIT_DATE = "2025-10-14T04:33:58Z"
EXTRACTION_DATE = "2026-11-12"

# The version string the geocoder pins an index against (design doc §6.4). It
# appears in the index manifest and in the footer metadata of every file this
# build writes, and all of them must agree.
#
# It names the date geocode.earth *built the GeoParquet*, from that file's own
# inventory entry -- not the HTTP Last-Modified, which is a bucket-migration
# timestamp, and not today's date, which would say nothing about the data.
CATALOG_VERSION = "whosonfirst-admin-parquet-2025-04-07"
CNMW_VERSION_KEY = "cnmw:catalog_version"


# ---------------------------------------------------------------------------
# Scope: which placetypes this catalog carries, and at which level
# ---------------------------------------------------------------------------
# Who's On First has no numeric admin level. It has placetypes, arranged in a
# hierarchy of its own (https://whosonfirst.org/docs/placetypes/). The search
# index contract wants a 0-based integer level, and the two sibling catalogs
# already fixed what those integers mean: country 0, region 1, county 2,
# localadmin 3, locality 4. This mapping extends that ladder by one rung for
# the neighbourhood tier and folds each of WOF's `macro`/`micro` variants onto
# the rung of the placetype it varies.
#
# A level is therefore a *tier*, not a strict generation of the hierarchy: a
# tier can hold both a unit and a unit's own subdivision, because WOF inserts
# `macroregion` above `region` and `microhood` below `neighbourhood` without
# adding a rung anyone else recognizes. The `placetype` column is carried
# through on every row of every file this build writes, so nothing about which
# WOF placetype a feature actually is gets lost in the folding.
PLACETYPE_LEVEL = {
    # level 0 -- country-equivalent
    "country": 0,
    "dependency": 0,
    "disputed": 0,
    # level 1 -- first-order subdivision
    "macroregion": 1,
    "region": 1,
    # level 2 -- second-order subdivision
    "macrocounty": 2,
    "county": 2,
    # level 3 -- local administrative unit
    "localadmin": 3,
    # level 4 -- settlement
    "locality": 4,
    "borough": 4,
    # level 5 -- sub-settlement
    "macrohood": 5,
    "neighbourhood": 5,
    "microhood": 5,
}

# Carried by geocode.earth's combined admin distribution and deliberately NOT
# indexed here, with the reason each one is out of scope. Counts are measured
# (tools/measure_upstream.py) and quoted in catalog/AGENTS.md.
PLACETYPE_EXCLUDED = {
    "campus": "a university, airport or military base, not an administrative unit",
    "postalregion": "a postal-service region; postcodes are a separate upstream distribution",
    "marinearea": "a body of water, not land administration",
    "marketarea": "a media market (Nielsen DMA), not administration",
    "timezone": "a timezone polygon, not an administrative unit",
    "ocean": "a body of water, not land administration",
    "continent": "above the country rung, so it has no level on a 0-based admin ladder",
    "empire": "a historical polity, above the country rung and not current",
}

# One collection per level, named after the placetype that dominates it.
COLLECTIONS: dict[str, tuple[str, ...]] = {
    "country": ("country", "dependency", "disputed"),
    "region": ("macroregion", "region"),
    "county": ("macrocounty", "county"),
    "localadmin": ("localadmin",),
    "locality": ("locality", "borough"),
    "neighbourhood": ("macrohood", "neighbourhood", "microhood"),
}
COLLECTION_LEVEL = {
    name: PLACETYPE_LEVEL[types[0]] for name, types in COLLECTIONS.items()
}
LEVEL_COLLECTION = {level: name for name, level in COLLECTION_LEVEL.items()}
LEVELS = tuple(sorted(LEVEL_COLLECTION))

# The 25 language columns geocode.earth's parquet build flattens WOF's
# `name:{lang}_x_preferred` properties into, in the file's own column order.
# WOF itself carries names in far more languages; this is the subset that
# survives into the parquet distribution, which is why this catalog's index
# cannot be richer than 25 languages however multilingual WOF is.
NAME_LANGS = (
    "ara", "ben", "deu", "eng", "ell", "fas", "fra", "heb", "hin", "hun",
    "ind", "ita", "jpn", "kor", "nld", "pol", "por", "rus", "spa", "swe",
    "tur", "ukr", "urd", "vie", "zho",
)

ZSTD_LEVEL = 15


# ---------------------------------------------------------------------------
# Layout targets
# ---------------------------------------------------------------------------
# Rows per row group, chosen per collection from the measured vertex count per
# feature so that one row group lands between about 1 and 2 MB. A client that
# wants one place's geometry fetches about that much instead of the median
# 38 MiB and worst-case 285 MiB the upstream file's 65,536-row groups cost
# (docs/upstream-measurements.md).
#
# The measured vertex counts behind these numbers, from
# tools/distributions.sql, are what make them differ by three orders of
# magnitude across six levels:
#
#   level  features    vertices  median  p95      point geometries
#       0       353       7.52M   4,866   77,813   0
#       1     4,362      29.33M   1,150   25,717   26
#       2    42,115      64.34M     490    5,254   443
#       3   164,756      76.40M     210    1,721   35,741
#       4 4,796,292     158.30M       1      157   4,031,001  (84%)
#       5   397,416       9.42M       1       75     334,785  (84%)
#
# tools/build_boundaries.py prints the achieved figure on every run and warns
# when a level leaves the band.
ROW_GROUP_ROWS = {
    "country": 4,
    "region": 16,
    "county": 64,
    "localadmin": 256,
    "locality": 2048,
    "neighbourhood": 4096,
}

# The display-simplified companions hold the same rows in the same order and
# the same groups, so a consumer reads row i of either file from group i // n.
DISPLAY_ROW_GROUP_ROWS = ROW_GROUP_ROWS

# Which levels get a display-simplified companion, and the measurement that
# decided it. Levels 0-3 have a median of 210 to 4,866 vertices per feature
# and a 95th percentile of 1,721 to 77,813, so drawing one of them from full
# resolution is slow and a simplified companion earns its second file. Levels
# 4 and 5 have a median of **one** vertex -- 84% of their features are points
# -- and a 95th percentile of 157 and 75, so there is nothing there to
# simplify and a second file would only add a fetch.
DISPLAY_LEVELS = (0, 1, 2, 3)

# Display simplification. The tolerance is per feature, not per collection:
#
#     tol = least(SIMPLIFY_TOLERANCE[collection],
#                 bbox_diagonal * SIMPLIFY_SHARE)
#
# and the outward buffer uses the same value. A single absolute tolerance
# cannot serve both Russia and Monaco: at a flat tolerance the small feature's
# outline moves by most of its own width. Scaling by the feature's own extent
# is what keeps every feature above the containment floor, and
# tools/build_display.py verifies containment per feature and reports the
# worst case.
SIMPLIFY_SHARE = 0.004
SIMPLIFY_TOLERANCE = {
    "country": 0.03,
    "region": 0.01,
    "county": 0.004,
    "localadmin": 0.002,
}

# The search index is sorted by name_norm, so a client that wants a name
# prefix fetches a contiguous run of row groups. The target is bytes, not
# rows.
#
# The index contract asks for 100-150 KiB per row group, and that is right for
# the index it was measured on: 2.5 MB, where the Parquet footer is a rounding
# error. It is the wrong target at this scale. The footer carries one thrift
# record per column per row group, and a range client reads the whole footer
# before it can read anything, so shrinking the groups grows what the first
# keystroke costs. The sibling Overture index measured the knee at 6,400 rows
# for 5.6M rows; this index is the same order of magnitude, so it takes the
# same figure, and tools/measure_index.py reprints the table for the file
# actually built.
NAMES_ROW_GROUP_ROWS = 6400
NAMES_ROW_GROUP_TARGET_KIB = (400, 560)


def staged_source() -> Path:
    return SOURCES / UPSTREAM_PARQUET_NAME


def boundary_path(collection: str) -> Path:
    return PUBLISH / collection / f"wof_{collection}.parquet"


def display_path(collection: str) -> Path:
    return PUBLISH / collection / f"wof_{collection}_display.parquet"


def pmtiles_path(collection: str) -> Path:
    return PUBLISH / collection / f"{collection}.pmtiles"


NAMES_PATH = PUBLISH / "names" / "wof_names.parquet"
NAMES_MANIFEST_NAME = "index.json"


def stream_write(
    src: Path,
    out: Path,
    *,
    row_group_rows: int,
    footer_meta: dict[bytes, bytes],
    batch_rows: int | None = None,
    transform=None,
    sorting_columns=None,
    compression_level: int = ZSTD_LEVEL,
):
    """Rewrite a Parquet file with exact row groups, a batch at a time.

    The whole table is never held in memory. That is not only thrift: DuckDB's
    Arrow appender refuses a binary column whose offsets exceed 2 GiB, which
    the locality geometry column does on its own, and streaming avoids the
    limit rather than switching to 64-bit offsets and changing the published
    column types.

    `batch_rows` is rounded down to a multiple of `row_group_rows`, so every
    group written is exactly full and a row number alone tells a consumer
    which group a row is in. That is what makes the search index's
    `geometry_ref` a single range read.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    if batch_rows is None:
        batch_rows = row_group_rows * max(1, 65_536 // row_group_rows)
    batch_rows = max(row_group_rows, (batch_rows // row_group_rows) * row_group_rows)
    reader = pq.ParquetFile(src)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    writer = None
    try:
        for batch in reader.iter_batches(batch_size=batch_rows):
            table = pa.Table.from_batches([batch])
            if transform is not None:
                table = transform(table)
            if writer is None:
                writer = pq.ParquetWriter(
                    out,
                    table.schema.with_metadata(footer_meta),
                    compression="zstd",
                    compression_level=compression_level,
                    write_statistics=True,
                    write_page_index=True,
                    version="2.6",
                    sorting_columns=sorting_columns,
                )
            writer.write_table(
                table.cast(writer.schema), row_group_size=row_group_rows
            )
    finally:
        if writer is not None:
            writer.close()
    return pq.ParquetFile(out).metadata


# ---------------------------------------------------------------------------
# Licensing
# ---------------------------------------------------------------------------
# Who's On First is not one license. Its own LICENSE.md scopes CC0 to "the
# format and structure that allows Who's On First to operate" -- the schema,
# not the records -- and says the dataset "is both an original work and a
# modification of existing open data", some of which requires attribution.
# The per-source terms are in whosonfirst-sources.
#
# So the STAC license is `other` with license links, which is what STAC 1.1.0
# requires of a license that is not an SPDX identifier. Measured against the
# upstream file's own `geom_src` column joined to
# whosonfirst-sources/data/sources-spec-latest.json, the geometry in the
# combined admin distribution breaks down as:
#
#   70.88%  3,844,289  CC BY            GeoNames
#   16.44%    891,696  CC-BY            Karmashapes, Mesoshapes
#    7.27%    394,250  CC BY 2.0        Quattroshapes, qs_pg, Open Data France
#    2.58%    139,913  CC0              whosonfirst, Metazen, US Census, woedb
#    0.97%     52,730  unmatched or empty geom_src
#    ~1.8%        rest CC BY 3.x/4.0, OGL, Public Domain, PDDL, ODC-By, ...
#  0.0003%         14  CC BY-SA 3.0     Wikipedia
#
# No ODbL source contributes geometry: whosonfirst-sources marks `osm` as
# usage_geometry 0, usage_property 0, usage_concordance 1, so OpenStreetMap is
# used only to mint concordance ids. There is therefore no share-alike
# obligation on this catalog, which is the whole reason it is worth publishing
# beside the ODbL Overture one.
STAC_LICENSE = "other"
LICENSE_LINKS = (
    (WOF_LICENSE_PAGE, "Who's On First data licenses, source by source"),
    (
        "https://github.com/whosonfirst-data/whosonfirst-data/blob/master/LICENSE.md",
        "Who's On First LICENSE.md",
    ),
)
WOF_SOURCES_SPEC = (
    "https://raw.githubusercontent.com/whosonfirst/whosonfirst-sources/main/"
    "data/sources-spec-latest.json"
)
WOF_SOURCES_LIST = "https://whosonfirst.org/docs/sources/list/"

# The attribution WOF asks for, verbatim from its LICENSE.md: "Crediting Who's
# On First is recommended and linking back to the License is required. For
# example: Data from Who's On First. License."
ATTRIBUTION = (
    f"Data from Who's On First. License: {WOF_LICENSE_PAGE}"
)
ATTRIBUTION_BLOCKS = (
    {
        "text": ATTRIBUTION,
        "license": "other",
        "url": WOF_LICENSE_PAGE,
        "share_alike": False,
    },
    {
        "text": "Includes data from GeoNames, available under CC BY 4.0.",
        "license": "CC-BY-4.0",
        "url": "https://www.geonames.org/about.html",
        "share_alike": False,
    },
    {
        "text": "Distribution built and hosted by geocode.earth.",
        "license": "other",
        "url": DOWNLOAD_PAGE,
        "share_alike": False,
    },
)


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------
# The index-file contract fixes this: NFD, strip combining marks (Unicode
# category Mn), lowercase, collapse whitespace, trim, and keep only Unicode
# letters, digits, space, hyphen and apostrophe. Everything else is removed.
# The alphabet matters because the geocoder normalizes the user's keystrokes
# with the same rule in JavaScript and then compares strings byte-wise against
# this column; a character this rule keeps and the client's rule drops makes
# the binary search miss.
_KEEP = re.compile(r"[^\w\s'-]", re.UNICODE)
_UNDERSCORE = re.compile(r"_")
_WS = re.compile(r"\s+")


def normalize_name(name: str | None) -> str | None:
    """Fold a display name to the index's sort key."""
    if name is None:
        return None
    decomposed = unicodedata.normalize("NFD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    # \w includes the underscore, which is not in the declared alphabet.
    cleaned = _UNDERSCORE.sub(" ", _KEEP.sub(" ", stripped))
    folded = _WS.sub(" ", cleaned).strip().lower()
    return folded or None


def shrink_bbox_float32(bbox_array):
    """Recast a float64 bbox struct to float32, rounding outward.

    Halves what the bbox costs in the search index, where four doubles a row
    across millions of rows is tens of megabytes. A naive cast is not safe:
    float32 rounds to nearest, so an xmin could round *up* and leave part of
    the geometry outside the bbox that claims to cover it, which silently
    breaks both row group pruning and a map fly-to. So each minimum is nudged
    towards -inf and each maximum towards +inf whenever the cast moved it the
    wrong way. The resulting box is never smaller than the true one, which is
    what the index contract's §6.2 amendment requires.

    float32 holds about 7 significant decimal digits, so a degree value keeps
    roughly 1e-5 degrees, about a metre.
    """
    import numpy as np
    import pyarrow as pa

    def outward(values, towards):
        exact = np.asarray(values, dtype=np.float64)
        cast = exact.astype(np.float32)
        wrong = (cast > exact) if towards < 0 else (cast < exact)
        if wrong.any():
            cast[wrong] = np.nextafter(
                cast[wrong], np.float32(towards * np.inf)
            )
        return pa.array(cast, pa.float32())

    bbox_array = bbox_array.combine_chunks()
    return pa.StructArray.from_arrays(
        [
            outward(bbox_array.field("xmin").to_numpy(zero_copy_only=False), -1),
            outward(bbox_array.field("ymin").to_numpy(zero_copy_only=False), -1),
            outward(bbox_array.field("xmax").to_numpy(zero_copy_only=False), +1),
            outward(bbox_array.field("ymax").to_numpy(zero_copy_only=False), +1),
        ],
        names=["xmin", "ymin", "xmax", "ymax"],
    )


def geo_metadata(
    *,
    geometry_column: str = "geometry",
    bbox_column: str = "bbox",
    bbox: list[float],
    geometry_types: list[str],
) -> bytes:
    """A GeoParquet 1.1.0 ``geo`` metadata value with bbox covering.

    The ``crs`` key is omitted, which the GeoParquet specification defines as
    OGC:CRS84 (longitude, latitude in degrees on WGS 84). That is the CRS the
    upstream coordinates are already in, so nothing is reprojected.
    """
    doc = {
        "version": "1.1.0",
        "primary_column": geometry_column,
        "columns": {
            geometry_column: {
                "encoding": "WKB",
                "geometry_types": geometry_types,
                "bbox": bbox,
                "covering": {
                    "bbox": {
                        "xmin": [bbox_column, "xmin"],
                        "ymin": [bbox_column, "ymin"],
                        "xmax": [bbox_column, "xmax"],
                        "ymax": [bbox_column, "ymax"],
                    }
                },
            }
        },
    }
    return json.dumps(doc).encode("utf-8")


def wrap_markdown(text: str, width: int = 79) -> str:
    """Wrap generated markdown to a readable width, leaving structure alone.

    A generator builds a paragraph as one long string, and a reader opening
    the raw file in a terminal or a diff then gets one line per paragraph.
    Fenced code blocks, tables and headings are left exactly as they are,
    because wrapping any of those changes what they mean. List markers and
    blockquote markers keep their prefix and get a hanging indent.
    """
    import textwrap

    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        stripped = line.strip()
        if (
            in_fence
            or not stripped
            or len(line) <= width
            or stripped.startswith(("|", "#", "---"))
        ):
            out.append(line)
            continue
        prefix = re.match(r"^(\s*(?:> )?(?:[-*] |\d+\. )?)", line).group(1)
        body = line[len(prefix):]
        hanging = " " * len(prefix)
        if prefix.lstrip().startswith(">"):
            hanging = prefix[: prefix.index(">") + 2]
        out.extend(
            textwrap.wrap(
                body,
                width=width,
                initial_indent=prefix,
                subsequent_indent=hanging,
                break_long_words=False,
                break_on_hyphens=False,
            )
            or [line]
        )
    return "\n".join(out)


def connect(*, memory_limit: str = "12GB", threads: int | None = None):
    """A DuckDB connection configured for this build.

    `preserve_insertion_order` is off by default, which is right for an
    unordered aggregate and wrong for any write whose row order is
    load-bearing. `copy_ordered` turns it back on for the duration of such a
    write.
    """
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("SET preserve_insertion_order = false;")
    con.execute(f"SET memory_limit='{memory_limit}';")
    WORK.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{(WORK / 'duckdb-tmp').as_posix()}';")
    if threads:
        con.execute(f"SET threads={threads};")
    con.execute("SET enable_progress_bar=false;")
    return con


def copy_ordered(con, sql: str, out: Path, *, level: int = 3) -> None:
    """Run an ORDER BY query and write the result to one Parquet file in order.

    `preserve_insertion_order` is forced on for the write, because a parallel
    single-file write may emit batches out of order and the row order of a
    boundary file is load-bearing: the search index's `geometry_ref` names a
    row number in it, and the display companion holds the same rows at the
    same offsets.

    The default compression level is low because the usual caller is writing
    an intermediate that is read once and deleted.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    con.execute("SET preserve_insertion_order = true;")
    try:
        con.execute(
            f"COPY ({sql}) TO '{out.as_posix()}' "
            f"(FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL {level})"
        )
    finally:
        con.execute("SET preserve_insertion_order = false;")


# ---------------------------------------------------------------------------
# ISO 3166-1 alpha-2 to alpha-3
# ---------------------------------------------------------------------------
# WOF's `country` property is "A two-letter country code from ISO 3166"
# (attested: https://whosonfirst.org/docs/properties/wof/). The index-file
# contract the geocoder reads declares `country` as alpha-3, and both sibling
# indexes publish alpha-3, so a widget configurable to any of the three can
# filter on one code system. This index therefore carries both: the derived
# alpha-3 under `country`, and WOF's own two-letter code byte for byte under
# `country_iso2`.
#
# The mapping comes from pycountry, which packages the official ISO 3166-1
# table. WOF also mints six codes of its own that ISO does not have
# (attested: https://github.com/whosonfirst/whosonfirst-placetypes):
#
#   XK  Kosovo ("We just followed Geonames' lead")
#   XN  Null Island
#   XS  Somaliland
#   XX  "a place disputed by two or more (ISO) countries"
#   XY  "an ISO country that has yet to be determined (by us)"
#   XZ  "the ISO country code equivalent of wof:parent_id=-2"
#
# None of those has an alpha-3. They are carried through unchanged, counted,
# and reported by the build.
WOF_SYNTHETIC_COUNTRIES = {
    "XK": "Kosovo, following GeoNames",
    "XN": "Null Island",
    "XS": "Somaliland",
    "XX": "disputed by two or more ISO countries",
    "XY": "an ISO country yet to be determined",
    "XZ": "no country; the equivalent of wof:parent_id = -2",
}


def register_iso3166(con) -> int:
    """Create an `iso3166` lookup table on a connection. Returns its size."""
    import pycountry

    rows = [(c.alpha_2, c.alpha_3) for c in pycountry.countries]
    con.execute(
        "CREATE OR REPLACE TEMP TABLE iso3166 "
        "(alpha_2 VARCHAR, alpha_3 VARCHAR)"
    )
    con.executemany("INSERT INTO iso3166 VALUES (?, ?)", rows)
    return len(rows)


def pycountry_version() -> str:
    import pycountry

    return getattr(pycountry, "__version__", "unknown")


def footer_metadata(extra: dict[str, str] | None = None) -> dict[bytes, bytes]:
    """Key-value footer metadata every data file this catalog writes carries.

    The version pin the geocoder checks (design doc §6.4) lives here, in the
    index manifest, and in every boundary file, and all three have to agree.
    """
    meta = {
        CNMW_VERSION_KEY: CATALOG_VERSION,
        "wof:distribution": UPSTREAM_REPO,
        "wof:parquet_built": UPSTREAM_PARQUET_BUILT,
        "wof:source_url": UPSTREAM_PARQUET,
    }
    meta.update(extra or {})
    return {k.encode("utf-8"): v.encode("utf-8") for k, v in meta.items()}


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n:.0f} B"
        n /= 1024.0
    return f"{n:.1f} GB"
