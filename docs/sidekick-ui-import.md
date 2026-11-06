# Importing Sidekick builds in Hero Companion

The Character → Import screen now accepts `.skif` v5 files alongside the
existing Mids `.mbd` and Homecoming `/build_save_file` exports.

**This is a deliberately conservative compatibility path.** It never
silently substitutes abilities the planner doesn't understand.

## Where Sidekick's ID map comes from

A `.skif` names powers and enhancements with CoH Sidekick's own IDs, so the
importer needs Sidekick's ID map (its "contract"). `server/sidekick_contract.py`
decides where that map comes from through one ordered **provider list**
(`server._sidekick_providers`); the importer only ever receives a folder.

1. **Configured folder** (`HC_SIDEKICK_CONTRACT_DIR`), for developers with
   their own Sidekick checkout. Server-side only; the browser cannot choose
   a path.
2. **Downloaded snapshot** (the normal path). The first `.skif` import asks
   before downloading Sidekick's published `bundle.json.gz` (about 2.4 MB,
   once) from GitHub at a **pinned commit**. Only bytes matching the pinned
   SHA-256 install. The slim ID map is unpacked atomically into
   `%APPDATA%\HeroCompanion\sidekick` (dev: `sidekick-data/`) and works
   offline from then on. "Not now" stores nothing, so the next import asks
   again. Nothing about the user's build is sent.

CI proves the pinned checksum matches the published bundle and that the slim
download imports the real Sidekick fixture exactly like Sidekick's full
contract folder (`tools/test_sidekick_contract_sidekick.py`).

### If CoH Sidekick ever stops

Nothing downstream of the provider list changes. Either:

- **Point the snapshot elsewhere**: update `SIDEKICK_SNAPSHOT` (url, sha256,
  size) to any other copy of the same bundle, or to a newer Sidekick commit
  after re-running the pinned tests; or
- **Add a provider**: any class with `name` and `locate()` returning a folder
  in the same layout (`manifest.json`, `powersets/...`, `archetypes.json`,
  `boost-index.json`, `enhancements.json`, `mids-names.json`), for example
  one generated from Hero Companion's own game data. Add `install()` if it
  must fetch or build its data first.

Already-downloaded copies keep working regardless, since they live on disk.

## What happens on import

1. Choose `.skif` from Character → Import.
2. A missing contract, a non-v5 file, unknown powers/IOs, unsupported
   character state, or a failed game-legality check is
   **refused before the current editor is modified**. The screen lists
   where the problem occurred.
3. If crafted IOs lack their level, supply the actual Sidekick session
   default. Leave it blank when unknown; Hero Companion will refuse
   instead of pretending every IO is level 50.
4. If a character is already open, confirm replacing it. A cancelled
   import leaves the existing build in place.
5. For successful supported builds, the existing importer loads the
   native build, generates totals, and supports Solve and Reset to imported.

**Limitations:** This does not import arbitrary Sidekick characters.
The current Hero Companion editor cannot yet preserve Sidekick's per-power
active modes, prestige or archetype inherents, proc overrides, shopping
progress, or all future fields. These block import rather than
being silently ignored. Successful conversion is not a Sidekick export
or evidence of round-trip parity. No automatically downloaded data or
new release package is included.

## Checks

```sh
python -m unittest discover -s tools -p test_sidekick_web_import.py -v
python -m unittest discover -s tools -p test_skif_reconstruct.py -v
node --check static/app.js
```

The PR also has a Flask test-client job using real shipped game data and
an actual pinned Sidekick v5 fixture.

## Sidekick attack chains (reference only)

Sidekick v5's named attack chains (ordered power addresses) now import when
every referenced power belongs to the selected, verified build. The converter
retains **both** original Sidekick power addresses and mapped Hero Companion
full names, including duplicates and order. Duplicate chain IDs, unsupported
chain attributes, or unknown/unselected powers cause the entire import to be
refused — there is no partial conversion.

A collapsible *Sidekick attack chains* panel in the build editor displays the
names and cast order. Chain records are carried in the native build under
`sidekick_attack_chains` so ordinary Save/Resume retain them; changing to a
new character clears the previous character's chains.

**This is provenance, not a rotation simulator.** Hero Companion does not yet
use these chains to calculate damage, optimize attacks, or generate a new SKIF
file. After you change the selected powers, the original chains may become
stale; the panel labels them as notes from the original build, not the current
simulation. Other Sidekick state that the editor does not represent (active
power modes, proc choices and progress) is still blocked rather
than silently ignored.

## Slotted inherents

Slots and enhancements on the seven inherents every character gets (Brawl,
Sprint, Rest, Swift, Hurdle, Health, Stamina) import onto Hero Companion's own
copies of those powers. The name comes from Sidekick's own inherent table
(`levels.json`: `Health` -> `Inherent.Fitness.Health`), never from guessing,
and must be one of Hero Companion's granted inherents. Their enhancements pass
the same checks as any other slot, and the slots count against the normal 67
(Homecoming grants no free inherent slots). A toggled-on inherent (for example
Sprint switched on), a prestige run or sprint, or an archetype inherent is
still refused, because the editor cannot represent it.

## Enhancement legality and slot budgets

An IO being present in the Homecoming database does not mean every power
can slot it. The SKIF converter checks each **generic IO** against Sidekick's
per-power `allowedEnhancements` list, including inherent powers. For example,
Health accepts Healing, not Recharge. Missing per-power rules or illegal
generic enhancement types **reject the entire file**, with the precise slot
reported; nothing in the editor is overwritten.

Homecoming allows at most six enhancement slots in a power and 67 **added**
slots across all powers, including the seven granted inherents. The source
converter checks these constraints before reconstruction, and Hero Companion's
shared build validator enforces the same limits for normal import and editor
requests. Inherents' one base slot is not an extra slot.

The one-time downloaded compatibility cache now includes the game's
per-power enhancement restrictions. An older cache lacking those restrictions
is identified as incomplete and repaired by another user-consented download.
A developer-supplied Sidekick checkout uses the original authoritative rules.

## Incarnate selections and active flags

Sidekick v5 stores each incarnate as a slot id, an **internal power name** and
an `active` flag. The importer now requires an **exact** match within Hero
Companion's shipped incarnate power catalog. It recognizes Homecoming's Alpha,
Judgement, Interface, Lore, Destiny, Hybrid, and Genesis slots when the named
power is present in that slot. Missing, ambiguous, unsupported and cross-slot
power identities cause a complete refusal rather than a dropped pick.

A supported selection is loaded directly into the End Game tab. A checkbox
next to each selected incarnate records whether it was **active** in Sidekick.
An inactive selection remains visible and is preserved by ordinary
Save/Resume, but is **excluded** from the `incarnates_full` calculation
payload when "Include incarnates (peak)" is turned on. Selecting a different
incarnate explicitly enables that new choice. The global peak toggle still
controls whether enabled incarnate buffs are included at all.

**Scope:** This preserves the saved identity and activation flags, not all
possible incarnate mechanics. Hero Companion's existing model still cannot
price every incarnate effect (e.g. some Lore pet effects and Interface procs).
Those choices are labeled unmodeled in the End Game interface and are not
given invented numerical benefits. The importer does not infer earned/crafted
status, purchase progress or new powers for a renamed fork.

Validation covers the original Sidekick v5 power fixture combined with six
real Homecoming incarnate choices from Sidekick's published v4 test case.
The unit suite also checks false versus true active flags and rejects unknown
or malformed records without returning a partial build. The real Flask test
checks import and Save/Resume.
