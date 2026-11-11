# M7 — Integration and release gates

**Reference:** [Project plan](BUILD-EVALUATION-RATING-OPTIMIZATION-PLAN.md) §M7 and §5,
[M2 contract](M2-EVALUATION-CONTRACT.md), [M6 contract](M6-FRONTIER-CONTRACT.md).
**Battery:** `tools/test_m7_end_to_end.py` (CI: build-evaluation workflow, with the pinned
Sidekick checkout).

## The workflow, end to end

| Step | Route / surface | Proof |
| --- | --- | --- |
| Import a real Sidekick build | `/build/import-sidekick` | battery A (pinned `rb5d_browser_pass.skif`) |
| Validate | `_complete_build_validation` (= `/build/validate`) | battery A: zero errors |
| Measure, no optimization | `/build/evaluate` | battery A, D |
| Rate per category | `ratings` in the evaluation | battery A: `rated`; D: all 15 archetypes |
| Compare | `/build/compare`, 📊 Rate this build | battery A: imported vs an alternative, `scope: same_powersets` |
| Pareto alternatives | `/build/frontier`, 🧭 Alternatives | battery A, C |
| Export to Sidekick | `/build/export-sidekick` | battery A: every alternative exports and re-imports with identical picks |

Unknown Sidekick fields: `slotOrder`, `procOverrides`, `disabledProcCategories` and
`isActive` pass through (CLAUDE.md, Sidekick section). An alternative that changes the
slotting cannot keep `slotOrder`; the export reports `dropped_slot_order` and the app
says so (battery A checks the report is there and that the untouched build keeps it).

## Offline, LLM-free

Battery B runs evaluate, compare and frontier with `socket.create_connection` and
`socket.connect` raising, and any process whose PROGRAM is a `claude`/`anthropic` CLI
refused (`llm_program` judges the executable, never a path argument, so the solver's
CBC call from a temp dir named `claude-0` passes). All three routes complete. The client
ships with `AI_ENABLED` false.

## Reproducible, versioned artifacts

- `/build/evaluate`: `versions` (app, model, database, database version, scenario
  fingerprint), the full scenario parameters, `inputs_normalized`, the unsupported
  powers and `ratings.thresholds_version`.
- `/build/frontier`: the same `versions` plus `rating_thresholds`, the `scenario`, and
  `request` (objectives with directions, floors, budgets, `keep_sets`), so a saved file
  says exactly how to reproduce it. `search.deterministic` is false only when a time
  budget stopped the run.
- Battery C: identical inputs give byte-identical evaluations and frontiers (apart from
  every measured-seconds field) for budget-bounded runs; a time stop is labeled
  `deterministic: false` (pinned in `test_frontier_search.py`). The starting build is
  evaluated once per frontier run. `versions` is one copy, taken from the evaluation
  that graded the builds (`rating_thresholds` = its `ratings.thresholds_version`).

## Representative builds

Battery D: all 15 playable archetypes (first primary and secondary each, generated
through the real autopick + solve) evaluate to 36 rated categories with JSON-safe
numbers. Capability checks on purpose-picked builds:

- pets: Beast Mastery Mastermind lists summon powers and grades pet damage;
- support: Empathy Defender measures ally healing and a team buff; Arsenal/Cold
  Controller measures control and team defense;
- emergency protection: Broad Sword/Bio Stalker carries a `timed_click` kept out of the
  sustained totals;
- damage procs (negative control): emptying the proc slots the way the app's
  `clearSlot` does (`null`) lowers the generated Brute's damage, and emptying as many
  non-proc pieces in non-attack powers lowers it less.

## Performance and memory

Battery E, on the generated Super Strength/Invulnerability Brute (measured in the
development container): evaluate 0.01 s, compare of two builds 0.01 s, a 3-evaluation
frontier 16.6 s with peak traced memory 24 MB. CI ceilings: 20 s, 40 s, 150 s, 512 MB.
Each frontier direction is one real solve; no champion search, sweep or certification
runs anywhere in this workflow.

## Four kinds of number

| Kind | What it is | Where it appears |
| --- | --- | --- |
| Raw measurement | the build's number in the rating scenario, with its unit | `measurements` (evaluate), `cells[].value` (compare), `members[].measurements` (frontier) |
| Rating | S-F against provisional fixed cut points, or Unknown / None / N/A | `ratings.categories[].grade`, `members[].grades` |
| Optimization objective | the measurements the player chose to trade off | `members[].objectives`, `frontier.objectives` |
| Champion score | the optimizer's single certified score for a champion build | **never** in these responses; only champion/certification tools |

Battery F walks every key of the three responses and fails on `score`,
`canonical_score` or `champion_score`, and checks each response names its kind
(`stage`, `mode`, `kind: discovered_frontier`).

## Comparison scope

`/build/compare` states what it compares: `same_powersets`, `same_archetype`, or
`cross_archetype` (with a note that every grade uses the same all-archetype cut points,
so a gap can be the archetype rather than the build). Powersets are read from the PICKS
(`build.picked_powersets` in the evaluation: the archetype sets the picked powers come
from), never from how the request spelled them, and a refused column is named in the
scope note. The line renders at the lede size (`.rt-scope`), warning-coloured when
cross-archetype. The app shows it above the table
and flags a cross-archetype comparison. Per-archetype or per-powerset cut points (peer
cohorts) are not built: the owner ruled that cohorts are worked out as builds come in
(backlog item 4).

## Found and fixed while integrating

- **Frontier fingerprint ignored the piece.** Real slots name their piece as
  `piece_uid`, but `frontier_search.fingerprint` hashed `uid`, so two slottings of the
  same sets with different pieces collided and the second was skipped as "same
  slotting". Fixed: both spellings fold into one `piece` key, so the same piece also
  fingerprints the same however it is spelled. Pinned in `test_frontier_search.py`.

- **Snipers credited two exclusive states per shot (model v58, owner's ruling
  2026-11-11).** 24 sniper records summed the out-of-combat snipe (4.5) and the
  in-combat quick snipe (2.28); `tools/patch_snipe_states.py` keeps the in-combat
  state and folds it where our data lacked it (Blaster redirect twins, Defender Proton
  Volley). 128 champion contexts pick an affected power; their canonical scores are
  stale until a recert (see the PR for the measured movement). Grade cut points
  recalibrated (version 2). The `Redirects.*` pet channel is correct by the owner's
  ruling: those powers spawn pseudopets.

## Open, for the owner

- **Independent red/blue review** (plan §M7): the repository defines `hc-red` /
  `hc-blue` agents, but agent runs need the owner's opt-in and cost. Every milestone
  so far had a `/code-review` pass with findings fixed or reported.
- **Peer cohorts** (same-powerset / same-archetype grade baselines): owner's ruling
  pending, as above.
- The 29 zero-damage powers and the other KNOWN-GAPS items stand; an
  `offense_complete: false` build gets Unknown offense grades.
