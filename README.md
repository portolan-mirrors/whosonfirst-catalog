# whosonfirst-catalog

A git-backed [Portolan](https://www.portolan-sdi.org/) catalog describing
[Who's On First](https://whosonfirst.org/), the open gazetteer, as
[geocode.earth](https://geocode.earth/data/whosonfirst/combined/) distributes
it — plus the few files a browser needs to search it.

The catalog metadata lives here. The data lives in object storage at
[source.coop/portolan-mirrors/whosonfirst-catalog](https://source.coop/portolan-mirrors/whosonfirst-catalog),
beside the published metadata.

## This catalog is metadata-first

Most Portolan mirrors copy the upstream bytes. This one does not, and that is
the point.

geocode.earth's combined Who's On First GeoParquet is already cloud-native:
GeoParquet 1.1 with a `covering` bbox, spatially clustered, served over HTTPS
with range requests and `Access-Control-Allow-Origin: *`. A planet-wide
aggregate over it takes seconds. Copying 5.5 GiB would produce a staler
duplicate of a file that already works.

So every collection links straight to geocode.earth's files, with the size and
sha256 their own inventory records, and this repository builds only what a
measurement says those files cannot do:

| built here | because |
|---|---|
| One GeoParquet per administrative level, small row groups, sorted by `(country, wof_id)` | one place's geometry from the upstream file costs a median of 38 MiB and up to 285 MiB |
| A display-simplified companion for levels 0–3 only | a median country is 4,866 coordinates; a median locality is **one** |
| PMTiles capped at 400 KB per tile | the upstream archive's whole-world tile is 15,671,392 bytes |
| A 9.5-million-row name index | nothing upstream answers "what places are called something like *this*" |

Every one of those numbers is measured, and every measurement is in
[`docs/upstream-measurements.md`](docs/upstream-measurements.md) and
[`docs/index-measurements.md`](docs/index-measurements.md). A built file with
no row in those documents does not belong in this catalog.

## Layout

| Path | What it is |
|---|---|
| `catalog/` | The published tree, synced 1:1 to object storage |
| `catalog.publish.yaml` | Where it publishes, and under what public URL |
| `tools/` | The build. Ten scripts, each runnable on its own |
| `tests/` | The gates CI runs on every pull request |
| `docs/upstream-measurements.md` | What geocode.earth's own files cost a client |
| `docs/index-measurements.md` | What the name index costs a client |
| `docs/licensing.md` | Why the `license` field says `other` |
| `docs/conformance.md` | Any validator finding this catalog accepts, and why |

`catalog/` is the publish boundary. Everything in it is published; nothing
outside it ever is. `tools/publish.py` has no flag that widens that.

## Build

The pipeline needs DuckDB with `spatial`, PyArrow, pycountry, GDAL's
`ogr2ogr`, `tippecanoe` and the `pmtiles` CLI. It stages about 10 GiB in
`../whosonfirst-staging`, outside the repository.

```bash
python3 tools/fetch_sources.py       # 5.5 GiB from geocode.earth, verified
python3 tools/measure_upstream.py    # -> docs/upstream-measurements.md
python3 tools/build_boundaries.py    # -> 6 GeoParquet files, ~18 min
python3 tools/build_display.py       # -> 4 display companions, ~3 min
python3 tools/build_names.py         # -> the index and its manifest, ~5 min
python3 tools/build_pmtiles.py       # -> 7 PMTiles archives
python3 tools/measure_index.py       # -> docs/index-measurements.md
python3 tools/make_styles.py         # -> the style JSONs
python3 tools/make_collections.py    # -> 7 collection.json
python3 tools/make_docs.py           # -> 14 README and AGENTS files
```

`tools/distributions.sql` reruns every distribution behind every style class
break and every count the catalog's prose quotes.

Four files under `catalog/` are written by hand and not generated:
`catalog.json`, `README.md`, `AGENTS.md`, `llms.txt` and
`changes-from-upstream.md`. Everything else there comes from a generator; see
[`AGENTS.md`](AGENTS.md) for which.

## Test

```bash
python3 tests/run_all.py
```

| Gate | What it checks |
|---|---|
| `test_links.py` | Every relative link and asset href resolves |
| `test_publish.py` | Nothing outside `catalog/` can be uploaded |
| `test_upload_data.py` | Only staged files with an allowed suffix upload |
| `test_stac_valid.py` | Valid STAC 1.1.0, via `stac-check` |
| `test_conformance.py` | Portolan conformance, via `rashid` |
| `test_styles.py` | Every legend class in every style is populated |
| `test_index_refs.py` | The index's `geometry_ref` pointers resolve to the right row, and every file declares the same `catalog_version` |

The last two need the built data and skip when the staging tree is absent,
which is what happens in CI. The two validator gates fail when their tools are
absent, because a skip would report a green run for a catalog no validator
read.

## Publish

```bash
python3 tools/publish.py             # dry run: what metadata would change
python3 tools/publish.py --confirm   # upload the catalog
python3 tools/upload_data.py         # dry run: what data would change
python3 tools/upload_data.py --confirm
```

Neither ever deletes. Removing a file from `catalog/` does not unpublish it.

Publishing goes through the `data.source.coop` gateway with the publisher's
own Source Cooperative credentials, which is what `endpoint_url` in
`catalog.publish.yaml` selects. CI with an approved IAM role would write to
the real bucket with no `endpoint_url` — same bytes, different door.

### Nothing has been published yet

The Source Cooperative repository does not exist, so neither script has been
run with `--confirm`. What is left, in order:

1. **Create the repository** `portolan-mirrors/whosonfirst-catalog` on
   [Source Cooperative](https://source.coop/), under the `portolan-mirrors`
   organization. Its title and description should match
   `catalog/catalog.json`; the license there is "other", with the two links
   in [`docs/licensing.md`](docs/licensing.md).
2. **Authenticate**: `source-coop login`, which writes the `source-coop`
   profile `catalog.publish.yaml` names.
3. **Upload the data first**, so no published metadata points at a missing
   file: `python3 tools/upload_data.py` to see the plan, then
   `--confirm`. About 7 GiB over 20 objects — six boundary GeoParquet files
   (3.3 GB), four display companions (0.4 GB), the index (0.6 GB) and seven
   PMTiles archives (1.2 GB).
4. **Then publish the metadata**: `python3 tools/publish.py`, then
   `--confirm`.
5. **Re-check against the live host**: `portolan check --live` from
   `catalog/`, which probes for HTTP Range support and CORS headers on the
   published objects. It will also probe the geocode.earth hrefs unless given
   a base URL, so pass `--url` to keep the report about this catalog's own
   host. The upstream host's own range and CORS behaviour is already recorded
   in [`docs/upstream-measurements.md`](docs/upstream-measurements.md).
6. **Register the catalog** in the Portolan registry.

Both scripts refuse to upload while `catalog.publish.yaml` still carries a
sentinel value, and they check before making any AWS call, so steps 3 and 4
can be rehearsed without credentials.

## License

Apache-2.0, covering the tooling in this repository.

The data carries its own licensing, which is a mix: Who's On First scopes CC0
to "the format and structure that allows Who's On First to operate" — the
schema, not the records — and the records inherit terms from over 300 sources.
Attribution is required. The evidence, the measured per-source shares and the
reasoning behind the `license` field are in
[`docs/licensing.md`](docs/licensing.md).
