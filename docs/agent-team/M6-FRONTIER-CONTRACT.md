# M6 — Discovered Pareto frontier contract

**Status:** implemented: `server/pareto.py`, `server/frontier_search.py`,
`POST /build/frontier`, and the app's 🧭 Alternatives view in the rating dialog.
**Reference:** [Project plan](BUILD-EVALUATION-RATING-OPTIMIZATION-PLAN.md) §M6,
[M2 contract](M2-EVALUATION-CONTRACT.md) (the measurements this reads).

## What it does

It takes the player's build and returns several legal re-slottings of the same
picks that do not dominate one another on the objectives the player chose. The
starting build competes as a candidate. Nothing is saved.

## Request

    POST /build/frontier
    {
      "build": { ...the planner's build... },
      "objectives": ["single_target_damage", "defense", "recharge"],
      "directions": {"recharge": "max"},
      "floors": {"defense": {"min": 30}},
      "max_evaluations": 12,
      "max_seconds": null,
      "max_frontier_size": null,
      "keep_sets": false
    }

- `objectives`: any of the 18 rating category keys (`build_ratings.CATEGORIES`).
  Default = the seven core ones (single-target, area, survival, defense,
  resistance, endurance, recharge). The values compared are the **unrounded
  measurements** (`build_ratings.measure`), never grades.
- `directions`: `max` (default) or `min` per objective.
- `floors`: hard constraints on any category, `{min}` and/or `{max}`. A
  candidate that misses one never enters the frontier.
- `max_evaluations`: default 12, capped at 40. The starting build counts as one.
- `max_seconds`: optional wall-clock budget. A run it stops is labeled
  `deterministic: false`.
- `max_frontier_size`: optional cap. Without it the frontier is **exact** (every
  feasible nondominated candidate found is kept). With it, crowding distance
  (NSGA-II) removes the most crowded member each time the cap is passed, and the
  response says `exact: false` with the rule.
- `keep_sets`: also lock the placed set pieces (the solver's `preserve`). The
  picks are always locked.

Refused with HTTP 400: no build, an unknown objective or direction, a malformed
floor or budget, and any build `/build/evaluate` refuses (PvP, exemplar level).

## Dominance

Every objective is turned to "higher is better" by its direction, without
rescaling. A dominates B iff A is at least as good on every objective and strictly
better on at least one. Two values are equal when they differ by no more than
`max(1e-9, 1e-6 x the larger magnitude)`; the tolerance is stated per objective in
the response. Equal candidates with different slottings are both kept. A
candidate missing a measured value on a chosen objective is `incomparable` and
never admitted.

The frontier is updated on every insert: a dominated newcomer is rejected; an
admitted one removes every incumbent it dominates. Members are ordered by
fingerprint, so arrival order never changes the result.

## Search

Candidates come from the existing solver (`/build/solve`, full re-slot) run along
a fixed, disclosed list of `frontier_search.DIRECTIONS`: the role presets
(balanced, damage, hard targets, tank, buffer, healer, controller, debuffer) and
target emphases (45% position defense, resistance cap, +150% recharge, +120%
recovery, +300% regeneration). Directions that serve a chosen objective run first.
A direction only proposes a candidate; dominance alone decides what is kept, and
no weighted sum is ever used. Each candidate is checked with
`_complete_build_validation` (the same check the Sidekick export uses), evaluated
in `rating_plus4`, held to the floors, then offered to the frontier. A slotting
seen before is not evaluated again.

The result is the **discovered frontier**: the directions do not span every legal
slotting, so it is never presented as the global Pareto frontier.

## Response

- `kind: "discovered_frontier"`, `claim` (states it is not proven global).
- `frontier`: `exact`, `size`, `max_size`, `dropped_by_cap`, `approximation`,
  `objectives` (key, direction, tolerance).
- `members[]`: `fingerprint`, `label`, `direction` (null = the starting build),
  `is_starting_build`, `objectives` (the compared values), `grades` (all 18),
  `measurements` (all 18), `change_from_start`, `holds_out_on` (per other member:
  the objectives this one is strictly better on, i.e. why it is not dominated),
  `offense_complete`, `build` (exportable).
- `starting_build`: its values and whether it is on the frontier.
- `search`: `stop_reason` (`exhausted`, `evaluation_budget`, `time_budget`),
  `evaluations`, `directions_tried`, `directions_not_tried`, `seconds`,
  `deterministic`, `locked`, `floors`, and `log` (every candidate's outcome:
  admitted with what it removed, dominated by whom, illegal with errors, below a
  floor, not evaluated, incomparable, or same slotting as an earlier one).
- `scenario`, `model_version`, `database_version`.

## Cost

Each direction is one real solve (about 1-7 s measured on a Brute) plus one
evaluation; a full 14-evaluation run took 27 s. No champion search, sweep or
certification runs.

## Tests

- `tools/test_pareto.py` — comparator and frontier rules (plan example, ties,
  float noise, min/max, removal, order independence, cap labeling, strengths).
- `tools/test_frontier_search.py` — search rules on a stubbed solver (illegal,
  floors, budgets, determinism, time budget, incomparable, duplicate slotting,
  request parsing) and the real route (legal, locked picks, repeatable, Sidekick
  import -> frontier -> export -> re-import with identical picks).
- `tools/test_frontier_view.js` — the app view (16 checks, negative-controlled).
- `tools/test_user_paths.py` — route coverage.

## App view (plan 6.4)

📊 Rate this build → 🧭 Alternatives. The player ticks categories (the checkboxes
start from `/meta.frontier_default_objectives`) and presses Find alternatives
(12 evaluations). The table lists every member with grade, value and change
against their build in each chosen category; the row says what it is best at
(the unique leader on a category) or that it is a trade-off. "Sort by" reorders
and "Minimum standards" hides rows below a number and states how many are
hidden; neither removes anything. **Use this build** applies the member's
slotting as an ordinary edit (`recordEdit` first, so Undo takes it back) and
closes the dialog; Sidekick or Mids export then runs from the Build menu as
usual. Save as file writes the whole frontier response. The renderer is pure
(`renderFrontierHtml`) with a node battery, `tools/test_frontier_view.js`.

## Open
- More directions widen the discovered frontier (for example per-type defense
  targets, or neighbourhood moves on a frontier member); each costs one solve.
- Offense objectives on a build whose `offense_complete` is false compare the same
  unread powers on every candidate (picks are locked), but the number understates
  the build; members carry the flag.
