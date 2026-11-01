# Native build reconstruction from Sidekick SKIF v5

`server/sidekick_reconstruct.py` turns a **supported subset** of a validated
Homecoming SKIF into Hero Companion's native build dictionary:

- Exact Homecoming archetype from Sidekick's `archetypes.json` (not a slug guess)
- Verified primary, secondary, pool and epic powerset paths, including empty sets
- Selected powers, pick levels, ordered slot positions, and *empty* slots
- Enhancement UID, set/piece metadata, IO level, booster, attunement and
  special enhancement offsets using the previously verified identity bridge
- Character level, name and declared origin as native metadata

It never writes a save, alters the editor, runs an optimizer, or downloads
upstream code. It retains the complete input separately as `source_skif`,
which is provenance, **not an export of any later edits**.

## Explicit loss-of-fidelity refusal

Any unresolved power or enhancement, unsupported Sidekick state (including
inherents with slots, active power mode, attack chains, proc overrides,
incarnates and progress), unknown schema field, wrong powerset classification,
inability to determine an ordinary crafted IO's level, a booster on an attuned
IO (the game allows none), or a Hamidon/Titan/Hydra/D-Sync grade outside +0..+3
(the game's 50..53 range) produces
`ok: false` with issues and **no native build**.

Sidekick SKIF may omit an IO level because Sidekick has a session-wide
default; Hero Companion cannot reconstruct it from the file alone.
Supply `--default-io-level N` based on the setting in the source session
when that information is known. Do not assume it was 50.

The native converter follows the existing Mids importer's HO-level convention,
but **does not prove all enhancement mechanics, slot legality, or character
build constraints**. Even `ok: true` means structurally reconstructed, not
certified game-legal or installed into the editor. A future editor integration
must run the full HC validator before exposing the result as usable.

## Offline command

Use a separate local Sidekick checkout's `contract/homecoming` folder:

```powershell
python tools/preview_skif.py character.skif --sidekick-contract path/to/coh-sidekick/contract/homecoming --reconstruct
```

For builds whose crafted IOs omit a level, add:
```powershell
--default-io-level 50
```
*Only* if 50 was actually the Sidekick session setting.

On success the command prints the reconstructed build plus source/evidence and
exits 0. Unresolved/unsupported state prints an explicit refusal and exits 2.
Malformed files or an unreadable contract exit 1. No files are written.

## Regression verification

```powershell
python -m unittest discover -s tools -p test_skif_reconstruct.py -v
```

The PR CI additionally checks an actual pinned Sidekick v5 Stalker fixture
against shipped Homecoming game data. The original fixture is **intentionally
refused** because it carries an attack chain; a *derived supported-subset test*
without that chain proves all seven power identities and native fields.
This is not evidence that the original full Sidekick file imports losslessly.

## Remaining work

A usable one-button editor importer requires a complete state mapping,
inherent and incarnate handling, game legality validation, atomic UI state
application and a reliable export/re-import parity test. Until then this is
an offline, fail-closed reconstruction feature.
