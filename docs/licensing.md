# Why this catalog's license says `other`

Who's On First is not one license, and no single SPDX identifier is true of
it. This document carries the evidence, so that the `license` field in every
`collection.json` can be short.

Everything quoted here was read on 2026-11-12. Every number was measured
against the upstream file this catalog describes.

## What Who's On First says about itself

`https://github.com/whosonfirst-data/whosonfirst-data/blob/master/LICENSE.md`,
in full:

> # License
>
> Crediting Who's On First is recommended and linking back to the License is
> required. For example:
>
> > Data from Who's On First. [License](https://whosonfirst.org/docs/licenses/).
>
> The Who's On First dataset is both an original work and a modification of
> existing open data. Some of those open data projects do require attribution.
> We have listed all sources in the full
> [license file](https://whosonfirst.org/docs/licenses/).
>
> Remember, some sources require attribution, some do not. The format and
> structure that allows Who's On First to operate is made available under a
> [Creative Commons Zero](https://creativecommons.org/choose/zero/)
> designation, and [a shout out](https://twitter.com/mapzen/) would be lovely.

Three things follow, and they are the whole argument.

**CC0 is scoped to the schema, not the records.** The sentence is "the format
and structure that allows Who's On First to operate is made available under a
Creative Commons Zero designation". That is the data model — the placetypes,
the property namespaces, the hierarchy. It is not a grant over the geometry
and names, which WOF does not own and cannot place in the public domain on
their sources' behalf.

**Linking back to the license is required; crediting WOF is recommended.**
That is the only hard obligation WOF states, and it is an obligation this
catalog passes on to its readers.

**The records inherit their sources' terms.**
[whosonfirst.org/docs/licenses/](https://whosonfirst.org/docs/licenses/) is a
flat list of sources, each with a data link and a license link, and it ends:

> *All 312 sources listed above are currently used to populate Who's On First
> records or will be added to Who's On First records in the near future.*

The page is generated, and it is stale: the file it is generated from,
`whosonfirst-sources/LICENSE.md`, now says 340 sources and carries a
generation date of 2024-03-21 against the page's 2020-02-21.

There is no blanket CC0 or CC-BY claim anywhere on that page.

## What WOF's import policy says

`whosonfirst-cookbook/definition/data_licenses.md`, under "Acceptable data
licenses":

> Who's On First is an "open" project. Because Who's On First is liberally
> licensed open data, we must be selective about adding new data. We either
> need to find a new source that is open data with a
> [CC-BY](https://creativecommons.org/licenses/by/4.0/) or
> [CC-0](https://creativecommons.org/share-your-work/public-domain/cc0/)
> license that allows commercial and derivative works or create new shapes
> based on local knowledge and by cross-referencing multiple sources. …
>
> Other data licenses are **not** acceptable for import, as such licenses do
> not allow Who's On First to openly redistribute the data.

So the *intent* is "CC-BY or CC0, nothing else". The measurement below is
what the intent produced in practice.

## The per-source table, and how to read it machine-side

The useful form is not the website. It is
[whosonfirst-sources](https://github.com/whosonfirst/whosonfirst-sources):

- `data/sources-spec-latest.json` — 182 source records
- rendered at
  [whosonfirst.org/docs/sources/list/](https://whosonfirst.org/docs/sources/list/)

Each record carries, per
[whosonfirst.org/docs/sources/](https://whosonfirst.org/docs/sources/):

> `"license"`: A link to the license or terms of service page, if available,
> for the source (string, optional property).
> `"license_type"`: The license or equivalent license type for the source's
> data (string, optional property).
> `"usage_geometry"`: Represents whether or not this source is used for
> geometries (integer, required property).
> `"usage_property"`: … `"usage_concordance"`: …

The `usage_*` flags are what make the picture tractable. **Every source with a
non-open license is marked `usage_geometry: 0, usage_property: 0,
usage_concordance: 1`** — used only to mint identifiers that point at someone
else's record, never to produce a geometry or an attribute value. That
includes:

| source | `license_type` | geometry / property / concordance |
|---|---|---|
| `osm` OpenStreetMap | ODbL | 0 / 0 / 1 |
| `eg` EuroGeographics | Restricted Use License (non-commercial) | 0 / 0 / 1 |
| `wmo` | CC BY-NC-ND 4.0 | 0 / 0 / 1 |
| `dbp` DBpedia | CC BY-SA 3.0 Unported | 0 / 0 / 1 |
| `iata`, `icao`, `ioc`, `nielsen`, `nyt`, `latimes`, `fct`, `m49` | Restricted | 0 / 0 / 1 |
| `iso` ISO 3166, `itu` | Restricted | 0 / 1 / 1 |

`iso` and `itu` are the two that reach a property value, and what they supply
is a two-letter country code and a dialling code.

**OpenStreetMap is not on whosonfirst.org/docs/licenses/ at all**, and in the
sources spec it contributes no geometry. There is therefore **no ODbL
share-alike obligation on this catalog**, which is the whole reason it is
worth publishing beside the
[ODbL Overture one](https://source.coop/portolan-mirrors/cn-gazetteer-overture).

## What the data actually carries

The upstream file has a `geom_src` column — WOF's `src:geom` property, "The
data source of a record's geometry", whose valid values are the
`whosonfirst-sources` prefixes. So the per-record licensing is not a guess; it
is a join.

Measured on
`https://data.geocode.earth/wof/dist/parquet/whosonfirst-data-admin-latest.parquet`
(5,423,663 rows, 108 distinct `geom_src` values), joined to
`sources-spec-latest.json`:

| share | records | `license_type` of the geometry source |
|---|---|---|
| 70.88% | 3,844,289 | CC BY — GeoNames |
| 16.44% | 891,696 | CC-BY — Karmashapes, Mesoshapes |
| 7.27% | 394,250 | CC BY 2.0 — Quattroshapes, qs_pg, Open Data France |
| 2.58% | 139,913 | CC0 — whosonfirst, Metazen, US Census, woedb |
| 0.97% | 52,730 | unmatched or empty `geom_src` |
| ~1.8% | rest | CC BY 3.x/4.0, OGL, Public Domain, PDDL, ODC-By, dl-de/by-2-0 |
| 0.0003% | 14 | CC BY-SA 3.0 — Wikipedia |

The shape of it: **attribution-requiring, not share-alike, and dominated by
one CC-BY source.** GeoNames alone is 3,843,415 records, and
[geocode.earth's own sources page](https://geocode.earth/sources/) states
GeoNames' terms explicitly:

> GeoNames under CC-BY-4.0.

The single share-alike contribution is 14 records.

## What geocode.earth says about redistribution

[geocode.earth/data/whosonfirst/combined/](https://geocode.earth/data/whosonfirst/combined/)
carries exactly one licensing sentence:

> This data is made available under the terms of the
> [Who's On First License](https://whosonfirst.org/docs/licenses/).

No click-through, no registration, no additional restriction, and no request
for credit to geocode.earth. Their own summary of the dataset, on
[geocode.earth/sources/](https://geocode.earth/sources/), is:

> Who's On First under various CC-BY or CC-0 equivalent licenses.

[geocode.earth/terms/](https://geocode.earth/terms/) is the Terms of Use for
their paid geocoding API. Its restrictions clause forbids redistributing "the
Services", which is the subscription product; the download pages point at the
WOF license instead. Mirroring or linking these files is governed by the WOF
license.

Crediting geocode.earth is not required. This catalog does it anyway, with a
`providers` entry in the `host` and `processor` roles, because they build and
pay for the distribution this whole catalog is about.

## The decision

```json
"license": "other",
"links": [
  { "rel": "license",
    "href": "https://whosonfirst.org/docs/licenses/",
    "title": "Who's On First data licenses, source by source" },
  { "rel": "license",
    "href": "https://github.com/whosonfirst-data/whosonfirst-data/blob/master/LICENSE.md",
    "title": "Who's On First LICENSE.md" }
]
```

STAC 1.1.0 allows exactly three forms for `license`: an SPDX identifier, an
SPDX expression, or the string `other`. It also says:

> If the license is **not** an SPDX license identifier, links to the license
> texts SHOULD be added. The links MUST use the `license` link relation type.
> … If no link to a license is included and the `license` field is set to
> `other` …, the data is private, and consumers have not been granted any
> explicit right to use it.

So `other` is only honest when the links are there, and they are.

What was rejected, and why:

- **`CC0-1.0` is wrong.** WOF's CC0 claim covers the format and structure.
  Over 95% of the geometry traces to attribution-requiring sources. Declaring
  CC0 would tell a reader they may strip attribution that WOF's sources
  require and WOF cannot waive.
- **`CC-BY-4.0` is defensible but not true.** It is the strictest term binding
  the large majority of the data, and complying with it over-complies with
  every CC0, public-domain, OGL and PDDL component — a conservative floor. It
  is not what WOF says about itself, it mislabels the CC0 records, and it
  under-states the 14 CC-BY-SA-3.0 records. A catalog whose whole value is
  honest metadata should not relabel someone else's license for tidiness.
- **An SPDX expression such as `CC-BY-4.0 AND CC0-1.0` is misleading.** `AND`
  in SPDX means every listed license applies to the whole work. Here they
  apply to disjoint subsets of records, and the expression still omits the
  OGL, PDDL and ODC-By tail.

## What a consumer has to do

Pass on the link. Quoting WOF's own wording:

> Data from Who's On First.
> [License](https://whosonfirst.org/docs/licenses/).

That satisfies the one stated requirement. Two additions this catalog
recommends, neither of them required by WOF by name:

- Credit GeoNames, under CC-BY 4.0, because it is 71% of the geometry.
- Credit geocode.earth, because they build the distribution.

And one thing a careful consumer can do that no blanket license permits:
**check the record.** `geom_src` is on every row. Join it to
`sources-spec-latest.json` and the license of a specific feature is a fact
rather than an average.

## Known gaps

- `sources-spec-latest.json` holds 182 records and the generated license page
  claims 340 sources, so some `geom_src` values resolve to no record. In this
  distribution that is 52,730 records, 0.97%, counted above as unmatched. Their
  license is not knowable from the published spec.
- Four sources in the spec carry an empty `license_type`. One of them,
  `ccsf-sfo` (San Francisco International Airport), is marked
  `usage_geometry: 1` and its `license_text` begins "Data contained on this Web
  page/site is Copyright © San Francisco City and County (CCSF),
  California. The GIS data are proprietary to CCSF…". It is venue-scale and
  contributes no rows to the placetypes this catalog carries, but it is a real
  wart in WOF's own licensing and it is recorded here rather than smoothed
  over.
