# Portolan Conformance

Conformance means passing [rashid](https://github.com/portolan-sdi/rashid),
not claiming to conform, so it runs in CI:

```bash
python3 tests/test_conformance.py
```

That gate fails on any error-severity finding whose rule is not listed below.
The list starts empty and it must never grow without a row here. A known
deviation with an issue number is a debt someone can pay off. A silently
widened allow-list is a false claim about what this catalog conforms to.

## The rashid version floor

The gate needs rashid `>=0.1.5,<0.2.0`. It reads `rashid --version` and fails
outside that range. It also fails when rashid is absent, and prints the install
command. A skip would report a green run for a catalog that no validator read.

The floor is 0.1.5 because rules PTL-LNK-007, PTL-LNK-008, PTL-LNK-009 and
PTL-AST-006 do not exist below it. The gate asserts all four. An older rashid
reports a pass for a catalog that it never checked against them. The same range
is in `portolan-cli/pyproject.toml` and in the CI install step.

The upper bound stops an unreviewed 0.2 rule set from changing what this gate
means. Raise both bounds together when you move to 0.2, and read the new rules
first.

This file also records workarounds for the other validator CI runs. Those are
not conformance debts, because the catalog is correct and the validator is not.
They live here so nobody has to read CI code to find out why a gate skips
something.

## Accepted deviations

None.

<!--
When you accept one, add a row and a section explaining it, like this:

| Rule | Where | Why accepted | Tracking |
|---|---|---|---|
| PTL-VIZ-001 | all thumbnails | WebP is not yet permitted; the size saving is 4x | portolan-spec#121 |

Then add the rule id to ACCEPTED in tests/test_conformance.py. Both, or
neither.
-->

## Accepted warnings

A warning does not fail the gate, so these are recorded here rather than in
`ACCEPTED`. They are deliberate, and a future reader should not "fix" them.

### PTL-AST-003 on `upstream-inventory` and `upstream-members`

`portolan check` warns that these two assets carry no `file:size` and no
`file:checksum`. They are geocode.earth's own live index: the inventory gains
an entry every time a country is rebuilt, and the members manifest changes
with it. Pinning a digest to a file whose whole job is to change would be a
promise this catalog cannot keep, and a reader comparing against a stale
digest would conclude the file was corrupt.

Every other upstream asset — the GeoParquet, the PMTiles, the SQLite, the
SpatiaLite and the GeoJSON bundle — does carry both, taken from that same
inventory, because those files are rebuilt under a new entry rather than
amended in place.

### PTL-DAT-001 on every pinned upstream asset (upstream drift, found 2026-11-13)

`portolan check` downloads each upstream asset and reports that its bytes no
longer match the pinned `file:checksum`. The pins are correct and the bytes
have moved: geocode.earth publishes every distribution file under a `-latest`
name and overwrites it in place, and the upstream has rebuilt since the
2025-04-07 build this mirror's data, documentation and measurements all come
from. Recomputing the checksums (what the warning's auto-fix tries) would
re-pin the metadata to bytes this catalog was *not* built from — a false
claim of vintage — so the pins stay until the mirror itself is rebuilt from
a newer upstream, at which point `tools/fetch_sources.py` onward regenerate
everything and the pins move together. The vintage story (inventory.json is
authoritative; HTTP Last-Modified is not) is in the index manifest's notes
and `tools/wofcommon.py`.

### PTL-PRO-002 on every collection

"Add a `rel='canonical'` link to the upstream STAC object, when the source
publishes one." geocode.earth publishes no STAC; the upstream is a download
page plus per-format inventory.json files, both already linked as assets.
There is no canonical STAC object to link.

## Validator workarounds

### stac-check reports a dialect crash on every collection

`tests/test_stac_valid.py` exempts one stac-check failure:

```
'list' object has no attribute 'get'
[Schema: https://schemas.portolan-sdi.org/portolan/vX.Y.Z/schema.json]. Error in Extensions.
```

The Portolan schema is valid draft-07, and rashid validates catalogs against it
cleanly. `stac-validator`, which stac-check uses, hardcodes the JSON Schema
2020-12 dialect and ignores the `$schema` a schema declares. The profile schema
uses the draft-07 tuple form of `items` in `valid_bbox`, which means something
different under 2020-12, so the library raises instead of validating.

Tracked upstream at <https://github.com/stac-utils/stac-check/issues/159>,
and on the Portolan side at
<https://github.com/portolan-sdi/portolan-spec/issues/157>.

The exemption matches that exact message, and only when the failing schema is a
Portolan profile schema. Every other stac-check error still fails the build,
and the gate prints how many objects took the exemption.

The exemption expires on its own. The gate fails once stac-check stops emitting
the crash on a collection or item that declares the profile schema, and tells
you to delete both the exemption and this section. CI installs stac-check
unpinned, so the next release triggers that without anyone watching for it.

`tests/test_stac_valid.py` also fails when stac-check is absent, and prints the
install command. It takes no version floor and no pin. The rashid floor exists
because that gate asserts four named rules. This gate asserts no stac-check
rule. It needs the opposite property. A pin holds the exemption open after the
upstream fix ships.
