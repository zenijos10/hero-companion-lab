# Sidekick read-only Homecoming identity preview (stacked on codec PR #2)

`server/sidekick_preview.py` is deliberately **not** an importer. It checks
that a Sidekick SKIF v5 power ID can be traced through Sidekick's published
Homecoming contract to an exact Mids-derived Hero Companion power record.

It uses Sidekick `manifest.json`, each referenced powerset shard's
`id`/`setPath`/`powers[].internalName`, and `mids-names.json`'s
`nameReverse` and `nameMap` (to detect renamed and colliding names).
It does *not* infer power identity by slug similarity; missing mappings are
reported. The HC source of truth is the shipped `data/powers.json`.
Only real found matches are listed as resolved.

The source SKIF stays unchanged. Enhancements, active states, inherents,
incarnates, accolades, slot order and attack chains are not translated by
this phase; the report explicitly lists their presence under `unresolved`.
The result has `ready_for_import: false` regardless of power matches.
There is no score, playable build, export, or editor mutation.

## Offline command

If you have checked out Sidekick as a **separate** local repository:

```text
python tools/preview_skif.py path/to/character.skif --sidekick-contract path/to/coh-sidekick/contract/homecoming
```

The command reads Hero Companion's own data and the supplied Sidekick
contract on disk. Nothing is downloaded. Nonempty unresolved results exit
with status 2 (a preview can still show partial identity matches).
Invalid JSON/schema or a bad contract exits with a clear error.

This code is original and does not redistribute Sidekick's AGPL source or
published game-data bundle. Sidekick remains the external format authority.

## Targeted verification

```text
python -m unittest discover -s tools -p test_skif_document.py -v
python -m unittest discover -s tools -p test_skif_preview.py -v
```

## Next pieces

Prove enhancement semantics and whole-build handling (including inherent
and cast-state choices) in a genuinely lossless importer; independently
re-open emitted files in Sidekick before enabling import/export UI.
