# Sidekick SKIF v5: format boundary (first incremental change)

Sidekick's current native format (as inspected 2026-10-29) is v5, with an
envelope (`version`, optional `authoredAgainst`, optional `meta`, `build`).
Source-of-truth schema: [Sidekick `crates/coh_data/src/skif.rs`](https://github.com/wednesdaywoe/coh-sidekick/blob/main/crates/coh_data/src/skif.rs).

`server/skif_document.py` implements a **lossless JSON boundary**, not game-data
interpretation, import into the live build editor, or optimized-build export.
It refuses unknown structural enhancement tags/versions and invalid typed fields,
while retaining unknown vocabulary, metadata, and future fields verbatim.
It intentionally does not attempt to load old v2–v4 SKIF files.

Why staged: Sidekick powersets use ids like `stalker/energy-melee`, whereas
Hero Companion uses Mids-derived identifiers. Slot ids, set-piece ids, and
inherents also require an independently tested crosswalk. Guessing would
silently change legal builds, contrary to the project's mechanics doctrine.

Next work, separate PR:
1. Build and verify an explicit Homecoming-only ID crosswalk (selected powers,
   sets, generic IO, special/origin enhancements and incarnates).
2. Add a read-only preview/import result that reports *every* unresolved
   selection and refuses to claim fidelity for any dropped state.
3. Translate the Hero Companion editor build to SKIF, preserving compatible
   metadata without inventing missing state, and re-import in Sidekick.
4. Wire a `.skif` file picker and export button only after fixtures and exact
   round-trip coverage pass.

## Verify

`python -m unittest discover -s tools -p test_skif_document.py -v`

All test fixtures in this fork are newly authored small examples, not copies of
Sidekick's distributed fixture corpus. No third-party code was copied.
