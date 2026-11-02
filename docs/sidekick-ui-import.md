# Importing Sidekick builds in Hero Companion

The Character → Import screen now accepts `.skif` v5 files alongside the
existing Mids `.mbd` and Homecoming `/build_save_file` exports.

**This is a deliberately conservative, opt-in compatibility path.** It
does not download a game-data contract automatically or silently substitute
abilities the planner doesn't understand.

## One-time local contract setup

Sidekick publishes the Homecoming contract in its own repository.
Use a *separate* checkout of the Sidekick project. For example:

```sh
git clone https://github.com/wednesdaywoe/coh-sidekick.git
```

Then configure the directory of its `contract/homecoming` files as the
environment variable `HC_SIDEKICK_CONTRACT_DIR` in the environment that
launches Hero Companion. It needs `manifest.json`, `mids-names.json`,
`archetypes.json`, `boost-index.json`, `enhancements.json`, and
the referenced powerset shard files. If you update Sidekick's checkout,
run the tests again; the consumer was verified against the pinned fixture
in this PR and other versions may introduce incompatible vocabulary.

Example for PowerShell (source checkout):

```powershell
$env:HC_SIDEKICK_CONTRACT_DIR = "C:\path\to\coh-sidekick\contract\homecoming"
python run_app.py
```

The configured path is **server-side only**. The browser cannot request
a different filesystem directory. No third-party contract is copied into
the Hero Companion repository, and the import itself makes no network calls.

## What happens on import

1. Choose `.skif` from Character → Import.
2. A missing contract, a non-v5 file, unknown powers/IOs, unsupported
   attack chains or other state, or a failed game-legality check is
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
The current Hero Companion editor cannot yet preserve Sidekick's active
power state, incarnates, slotted inherents, proc overrides, attack chains,
shopping progress, or all future fields. These block import rather than
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
