# Native build reconstruction from Sidekick SKIF v5

`server/sidekick_reconstruct.py` turns a **supported subset** of a validated
Homecoming SKIF into Hero Companion's native build dictionary:

- Exact Homecoming archetype from Sidekick's `archetypes.json` (not a slug guess)
- Verified primary, secondary, pool and epic powerset paths, including empty sets
- Selected powers, pick levels, ordered slot positions, and *empty* slots
- Enhancement UID, set/piece metadata, IO level, booster, attunement and
  special enhancement offsets using the previously verified identity bridge
- Character level, name and declared origin as native metadata
- Exact selected Incarnate powers and per-slot active/inactive state, using
  Hero Companion's shipped incarnate catalog; disabled picks remain visible
  but do not contribute to the peak-stat calculation payload

It never writes a save, alters the editor, runs an optimizer, or downloads
upstream code. It retains the complete input separately as `source_skif`,
which is provenance, **not an export of any later edits**.

## Explicit loss-of-fidelity refusal

Any unresolved power or enhancement, unsupported Sidekick state (including
prestige or archetype inherents, active power mode, proc overrides,
shopping progress, unknown incarnate records and unshipped incarnate choices), unknown schema field, wrong powerset classification,
inability to determine an ordinary crafted IO's level, a booster on an attuned
IO (the game allows none), or a Hamidon/Titan/Hydra/D-Sync grade outside +0..+3
(the game's 50..53 range) produces
`ok: false` with issues and **no native build**.

Sidekick SKIF may omit an IO level because Sidekick has a session-wide
default; Hero Companion cannot reconstruct it from the file alone.
Supply `--default-io-level N` based on the setting in the source session
when that information is known. Do not assume it was 50.

The converter validates **generic IO eligibility** against Sidekick's
per-power Homecoming `allowedEnhancements` table, rejects missing eligibility
rules, and enforces the six-slots-per-power/67-additional-slots caps. Other
mechanics may still be unsupported; `ok: true` is not proof of every build
constraint. The guarded in-app importer also applies HC's shared validator
before allowing a build into the editor.

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
against shipped Homecoming game data. The original published fixture now imports its seven powers plus attack-chain
references as non-simulated metadata. The pinned v4 Homecoming inherent slots
are also exercised as v5 records. This is not a guarantee of arbitrary SKIF
round-trip parity.

## Remaining work

The guarded editor importer now supports powers, slotted standard inherents,
reference-only attack chains and exact incarnate selections with active flags.
Remaining milestones include unsupported active power modes, proc overrides,
shopping/progression state, finer legality rules and real SKIF export with
re-import parity. This is still a conservative subset, not universal SKIF
support.
