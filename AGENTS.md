# Portolan agent norms

All agents MUST read this document before starting work, with no exceptions,
ever. (Claude Code does not read `AGENTS.md` but imports this file via a
one-line `CLAUDE.md`.)

## Ground rules

The [portolan-spec](https://github.com/portolan-sdi/portolan-spec) repo is the
absolute ground truth for the Portolan spec. All other tools are downstream of
it.

Before documenting any command, flag, or API, verify that it exists.

Use conventional commits always.

## This Repository

A git-backed Portolan catalog describing Who's On First as geocode.earth
distributes it. The catalog metadata is tracked here; the few data files this
catalog adds are built by `tools/` and live in object storage. Read
`README.md` for the layout and the build commands.

### This catalog is metadata-first

Most Portolan mirrors copy the upstream bytes. This one does not. Its boundary
assets are geocode.earth's own URLs, because geocode.earth already serves them
over HTTPS with range requests and permissive CORS, and copying 5.5 GB to say
the same thing twice would make this catalog a staler duplicate of a file that
is already cloud-native.

What this repository builds is only what a browser client cannot get from
there, and every built file has to carry its own justification: a measurement
showing what the upstream file costs for that job, and a sentence saying when
to use which. `docs/upstream-measurements.md` is where those measurements
live, and `tools/measure_upstream.py` regenerates it. A built file with no row
in that document does not belong in this catalog.

### The publish boundary

`catalog/` is the published catalog. Everything in it is published except
dot-directories, and nothing outside it ever is. Do not move a file into
`catalog/` to make it publish, and do not add a path outside `publish_dir` to
`tools/publish.py`. The boundary is the only thing standing between a scratch
file and a public bucket, and it holds because it is structural rather than a
list of exclusions.

### Data never enters git

Never commit a GeoParquet, PMTiles, SQLite or Zarr file. The pipeline stages
the upstream download and its own output in `../whosonfirst-staging`, outside
the repository, and `tools/upload_data.py` carries the publishable part to the
bucket. Git keeps every version of a binary forever and deleting it later
reclaims nothing.

### Edit the generator, not the generated file

These files under `catalog/` are generated and will be overwritten:

| generated | by |
|---|---|
| `catalog/*/collection.json` | `tools/make_collections.py` |
| `catalog/*/styles/*.json` | `tools/make_styles.py` |
| `catalog/*/README.md` | `tools/make_docs.py` |
| `catalog/*/AGENTS.md` | `tools/make_docs.py` |
| `catalog/*/*.thumb.png` | `tools/make_thumbnails.py` |
| `catalog/names/index.json` | `tools/build_names.py` |
| `docs/upstream-measurements.md` | `tools/measure_upstream.py` |
| `docs/index-measurements.md`, `.json` | `tools/measure_index.py` |

`catalog/catalog.json`, `catalog/README.md`, `catalog/AGENTS.md`,
`catalog/llms.txt` and `catalog/changes-from-upstream.md` are written by hand,
as are the files under `catalog/_assets/`, which are Who's On First's own
copied verbatim.

Two modules exist so a fact has one home. `tools/columns.py` holds every
published column description with its provenance tag, read by both the
collection generator and the documentation generator. `tools/wofcommon.py`
holds the placetype-to-level mapping, the layout targets, the licensing
blocks and the `geom_src` grouping — nothing may restate any of them.

### The conformance allow-list

`ACCEPTED` in `tests/test_conformance.py` is not widened without a matching
row in `docs/conformance.md` giving the rule, where it fires, why it is
accepted, and the issue tracking its removal.

### Published agent guides

Every claim in a `catalog/**/AGENTS.md` is either quoted from a source or
measured from the data. An invented join key or column name produces a
confident wrong answer that nothing downstream catches. The guides tag each
claim **[attested]**, **[researched]** or **[derived]**, and a **[derived]**
claim carries the query that produced it.

Two traps specific to this catalog:

- **Who's On First has no numeric admin level.** The `level` column is this
  catalog's mapping of WOF placetypes onto the 0-based ladder the search index
  contract uses. It is defined in one place, `PLACETYPE_LEVEL` in
  `tools/wofcommon.py`, and nothing may restate it by hand.
- **The upstream formats are not in sync.** The GeoParquet build is six months
  older than the SQLite, SpatiaLite, GeoJSON-bundle and PMTiles builds of the
  same repository. Any count this catalog quotes is a count of the GeoParquet
  vintage, and the prose says so.

### Licensing is a mix, and the catalog says so

Who's On First is not one license. Its own LICENSE.md scopes CC0 to "the
format and structure that allows Who's On First to operate", not to the
records, and the records inherit terms from 300-odd sources. Do not write
`CC0-1.0` or any single SPDX identifier into a `license` field here. The
catalog uses `other` with `license` links, and the per-source reality is
documented with measured shares. See `docs/licensing.md`.
