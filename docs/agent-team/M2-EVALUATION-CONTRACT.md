# M2 — Versioned build evaluation contract

**Status:** Initial implementation on a feature branch. This is not a completion claim for the entire M2 measurement backlog.  
**Reference:** [Project plan](BUILD-EVALUATION-RATING-OPTIMIZATION-PLAN.md) and [M1 audit](M1-TRACEABILITY-AUDIT.md).

## Purpose

Rating an imported character needs a stable, read-only measurement interface. Existing engine.calculate_build, first_principles.encounter_value, and role_output calculations remain authoritative. This layer exposes their measurements without assigning grades or optimizing builds.

## Request

POST /build/evaluate accepts JSON with a build object and optional scenario:

    {
      "build": {
        "archetype": "Class_Blaster",
        "primary": "Blaster_Ranged.Fire_Blast",
        "secondary": "Blaster_Support.Fire_Manipulation",
        "powers": []
      },
      "scenario": "rating_plus4"
    }

The build object uses the planner's existing format including power picks and slotting. For meaningful results, submit a real imported character rather than the empty example.

The default rating_plus4 scenario copies the general solo encounter, changing enemy level to +4. All other assumptions remain (4 enemies, 30-second duration, no teammates). **Existing general solver/optimization preset remains +1.** Explicitly selecting general evaluates the original +1 scenario. rating_plus4 lives in `build_evaluation.RATING_SCENARIOS` (base scenario + overrides), NOT in `first_principles.SCENARIOS`, so it is never a valid solver `content`.

Refused with HTTP 400 (never silently rated): malformed build structures, PvP builds (rating scenarios are PvE), and an exemplar level of 1-49 (the same values /build/calculate exemplars on; 50, 0, empty or non-numeric evaluate normally).

What is rated: the player's own build, in combat. Suppressible (Hide-class) defense is excluded; other people's buffs and inspiration amplifiers (`include_external`, `include_amplifiers`) are removed. Owned boosters (`slot.boost`, including HOs at +3) ARE rated: they are what the player has in game. A booster preview is the client's to leave out of the payload; the response counts the boosted pieces it rated.

## Versioned response (schema_version = 1)

- ok, stage=measurements_and_ratings, schema_version: machine-readable status.
- versions: app, model, database name and database version, plus `scenario_fingerprint` (a hash of the scenario constants; it changes whenever any constant is tuned, MODEL_VERSION or not). Compare stored results only when every version field matches.
- inputs_normalized: `boosted_pieces_rated`, `external_buffs_removed`, `defense_basis` ("in_combat").
- build: archetype, primary, secondary, picked-power count.
- scenario: ID, enemy level shift/count, teammate count, duration, enemy damage type, the full parameter set and provenance.
- measurements.offense: raw ST chain DPS/AoE metrics (no scenario hit chance), then each part after the scenario: `scenario_single_target_dps`, `scenario_aoe_dps_per_target` with `scenario_aoe_targets`, and `scenario_pet_dps`. They are the exact parts of `scenario_personal_dps`: 0.4 x ST + 0.6 x AoE x targets + pets (pinned by the real-build battery). `first_principles.encounter_value` returns them as display-only keys; its score is byte-identical (checked on 42 build x scenario pairs).
- measurements.survival.toughness: the incoming damage per second (as the enemies deal it) the build outlasts for the scenario's length, for an even mix of the 8 damage types x melee/ranged/AoE; `by_position_and_type` holds the 24 cells (defense = best of position and type, DDR-eroded; the -ToHit the build lands; resistance capped; regeneration + self heals + absorb, the same inputs as time to live), `weakest`, `break_even` (the damage sustain alone holds forever) and `bare_archetype` (base hit points and regeneration, nothing else). `toughness_vs_archetype` = toughness / bare_archetype. Idea from the community Survivability Tool (Homecoming forums topic 12212); the arithmetic is the encounter's own.
- measurements.survival: `basis` (sustained = toggles and autos), `emergency_powers` (below), in-combat defense and resistance vectors, `defense_out_of_combat` rows only where suppressible defense makes them differ, estimated time to live, availability and incoming/outgoing hit probabilities.
- measurements.resources: recharge bonus, Hasten's time-averaged bonus (support uptime uses passive + Hasten, the same recharge the scenario figures use), endurance recovery, chain and toggle drain, net/sustainability.
- measurements.support: control proxy and per-power breakdown, control uptime, buffs/debuffs in percent by effect, self/team healing proxy and resurrections.
- unsupported: unrecognized power identifiers, plus `powers`: one row per power the model knowingly does not measure, with a reason. Effect-less records are sorted by `server/effectless.py` (one copy, shared with `tools/classify_effectless_powers.py`, which writes `docs/EFFECTLESS-POWERS.md`): `unread_redirect` (its effects are in twin records we already ship, listed in `twins`), `damaging_unread` (the game's help names damage, or it takes Damage enhancement, and no record of ours carries it), `effect_unread` (another effect we do not carry), `unpriced_mechanic` (a mode switch or an auto-granted record: nothing to read). Each row says `damaging`. Also `unknown_record` and `mez_protection_not_scored` (the open mez_in ruling). `modeled_without_effect_rows` lists effect-less powers that ARE priced elsewhere: the Mastermind upgrades in a Mastermind summon set, priced by their re-cast time (`first_principles.mastermind_upgrade_records`, the rule encounter_value uses). `effect_level_audit` is "power_level": detail is per power, not per effect row.
- confidence: `powers_read` of `powers_total` (picks the model reads at all; **not** a completeness score: a read power can still be priced only in part), `offense_complete` (false whenever a picked power deals damage the model does not read, or is unknown), and one line per section saying whether it is modeled, provisional (scenario constants) or a proxy.

### Emergency powers

A click power with timed self Defense/Resistance (Unstoppable, Elude, Strength of Will) is emergency mitigation. It is never counted in the sustained totals, even when the player ticked it (the ticked ones are listed in `inputs_normalized.emergency_excluded_from_sustained`). Each one gets a row: the per-type gain while active (measured by recalculating with it switched on), duration, recharge after global recharge (incl. Hasten) and its own slotting, uptime, and the penalties the game data attaches (endurance, recovery, regeneration or HP crashes). When the rows do not share one duration, `uniform_duration` is false and `uptime_by_effect` gives the exact uptime per effect/type; the headline `duration_seconds`/`uptime` is then the longest row. Penalties are the raw game-data rows (`penalty_basis`), not a normalized severity.

A toggle whose own help says the caster cannot attack while it runs (Personal Force Field: "while it is active, you can only use powers that affect yourself"; 6 pickable records) is a defensive MODE: kept out of the sustained totals the same way, listed with `kind: caster_locked_toggle`, its gain while on and the game's restriction sentence, and no uptime (it is the player's choice and costs every attack). Timed clicks carry `kind: timed_click`.
- limitations: approximations and deliberately unsupported capabilities.

Representative scalars have value, unit, basis, and status (modeled or unknown). Missing or nonfinite results are null, never silently zero.

## Boundaries and next steps

- API is read-only; it neither optimizes nor writes saved builds.
- Homecoming game-client-derived mechanics remain authoritative; no new rules are inferred from champions.
- No S/A/B/C/D/F grades, peer percentiles, comparison scorecards or Pareto frontiers yet.
- Control and healing figures are model proxies, not literal seconds of incapacitation or hit points restored.
- Scenario personal DPS is a scenario-weighted ST/AoE and pet **DPS-equivalent**, not isolated ST DPS at +4.
- Provisional PPM, aura, scenario and other gaps remain documented in docs/KNOWN-GAPS.md and CLAUDE.md.
- Build legality is not certified here; /build/validate remains the legality endpoint.

### Tests and commands

- python tools/test_build_evaluation_contract.py — deterministic contract unit tests.
- python tools/test_build_evaluation_route.py — Flask route smoke with real game data and no solve.
- python tools/test_user_paths.py — existing route coverage including /build/evaluate, using scratch save paths.
- .github/workflows/build-evaluation.yml — runs the above checks on relevant PRs.

### M2 backlog

- [x] Read-only evaluate(build, scenario) with versioned numeric measurements and explicit units.
- [x] Expose encounter-level hit chance, availability, time to live and contribution alongside raw stats.
- [x] Expose control, debuff, buff and healing outputs with proxy labeling.
- [x] Establish separate +4 default rating scenario without changing existing general +1 preset.
- [x] Expose unknown-power identifiers and known-gap references.
- [x] Verify representative builds including incarnates, pets, controls and procs (`tools/test_build_evaluation_builds.py`: real autopick + solve builds for a Mastermind, Controller, Brute with incarnates and an Archery Blaster, plus the pinned real Sidekick v5 fixture imported through `/build/import-sidekick`; finite-or-unknown, determinism, part-sum, +4 vs +1). The generated builds pass `/build/validate` with zero errors; the probes then APPEND powers (Unstoppable, Ranged Shot, the MM upgrades, which autopick never proposes), so the final brute/archer/mastermind builds are measurement probes, not claimed-legal characters.
- [x] Optimizer score parity is pinned (`tools/test_encounter_parity.py` + `tools/fixtures/encounter_parity.json`: 4 frozen builds x 7 scenarios; master's encounter_value reproduces every pinned value; a model bump re-pins with `--write`).
- [x] Provide individually scenario-adjusted ST and AoE outputs rather than only weighted composite.
- [x] Split sustained and emergency defensive metrics, including click uptime and restrictions.
- [x] Add per-build unsupported-effect detail and confidence metadata.
- [ ] **Blocked on game knowledge / owner rulings:** verify provisional mechanics against the live game and calibrate encounter assumptions. Nothing here can be settled from code; each needs an in-game measurement or a ruling (see below).

### M3: team support (`measurements.support.team_support`)

`server/support_ledger.py`, display only. Every magnitude, uptime and share comes from the helpers the score uses (`role_output.row_peak_pct`, `click_uptime`, `attack_share`, `_power_enh`, `power_control_uptime`'s rules; `first_principles.player_effect_strength`), extracted from the score's own functions without moving it: 72 old-vs-new comparisons of the support totals on 12 support builds and the 28-score parity pin all match.

Per picked power with support output:
- coverage: `area` (aoe / single_target) and `max_targets`; `cost`: cast seconds and endurance per minute of keeping it running (clicks cast on cooldown, toggles per activate period).
- `buffs` / `debuffs` per effect, aggregated by the score's own rule: rows SUM within (effect, damage type), then typed spreads collapse to the largest type (owner review of #26; pinned by a real-build regression that matches every ledger average to `role_output`'s own per-power totals): peak %, uptime, average % (peak x uptime), sustained (uptime >= 0.98) or burst, stated chance; `instant` effects (a click row with no duration) carry no uptime or average. Debuffs add `landing_peak_percent`: vs the rating scenario (purple patch at its shift) and vs an AV (purple patch at +2 and the AV's 85% debuff resistance, which never applies to -Resistance).
- `heals`: ally or self, per cast per target, targets, per second over the enhanced cycle, sustained or emergency (cycle >= 60 s); in the score's heal units, not literal HP.
- `controls` per mez: magnitude, enhanced duration, uptime, sustained, kind (hard/soft) and the ranks one application affects (mez lands when magnitude EXCEEDS protection: minion 1, lieutenant 2, boss 3, elite boss 6, AV 53).
- resurrect powers carry `conditional`: their buffs land only on a revived ally.

`summary`: buffs averaged sustained vs burst; debuffs single-target judged vs an AV and area judged vs the scenario's spawn; ally heals sustained vs emergency per second. Instant effects and resurrect buffs are excluded from it.

Acceptance (real builds, `tools/test_build_evaluation_builds.py`): a Cold Domination build's single-target -Regeneration against an AV reads high while its area -Damage does not; a Force Field build reads > 20% sustained Defense with zero healing; -Resistance ignores AV debuff resistance while -Regeneration does not; Elixir of Life is conditional and out of the averages. Negative-controlled.

**Found, not fixed (moves scores; KNOWN-GAPS.md):** the score's support totals count resurrect buffs and instant click effects as permanent.

### M4: S-F ratings (`ratings`)

`server/build_ratings.py` grades 20 categories (single-target, area and pet damage; survival; toughness and toughness for its archetype; defense; resistance; endurance; recharge; control; ally healing; team defense/damage/recharge buffs; -Resistance and -Regeneration vs an AV; -Defense, -ToHit and -Damage vs a spawn). Each row keeps its exact `value`, `unit` and the `cuts` it was graded against.

**Owner's rulings (2026-11-10):** +4 is the default; thresholds start as FIXED numbers using the shipped champions as a guideline and move as more builds come in; the champions are NOT the comparison population (peer cohorts are worked out as we go, so the three comparison scopes wait).

- The numbers: `data/rating_thresholds.json`, written by `tools/calibrate_rating_thresholds.py` (an archetype-stratified sample of itrial champions, rebuilt as served, evaluated at rating_plus4; cut points S>=p90, A>=p70, B>=p50, C>=p30, D>=p10, else F; capability categories cut only from champions that have the capability). Hand edits are expected; bump `version`.
- Labels besides S-F: **Unknown** (not measured; offense incomplete, so no offense grade while a picked power deals damage the model does not read; a support capability measured at zero while the build picks powers whose effects are unread; pets summoned but priced at zero), **None** (capability absent and everything read), **N/A** (pet damage when no picked power summons anything, read from the records' `summons`, never inferred from pet damage).
- **not_rated** (with the reason) when the evaluation's scenario, scenario fingerprint, model version or game-data version differs from the calibration's, or no thresholds are installed.
- Each row carries the cut's `sample_size` and `low_sample` (< 30 champions; team recharge buff is the known thin one). `tools/test_build_ratings.py` fails after a model bump or a rating-scenario change until the thresholds are recalibrated.
- Every rating is `provisional: true`. Grades are against optimized itrial champions, so a typical build lands lower than a percentile against all players would put it.

### M5: scorecard and side-by-side comparison (`POST /build/compare`, the app's 📊 Rate this build)

- **Route:** `{builds: [{label, build}, ...]}`, 1 to 4 builds, optional `scenario`. One build = `mode: scorecard`; more = `mode: comparison`. Read-only: it evaluates through the same `_evaluate_build` helper `/build/evaluate` uses (never solves, never writes a save; pinned by `tools/test_build_compare.py`). A build the evaluation refuses (PvP, an exemplar level) comes back as a column with `ok: false` and its reason, so the app states it instead of raising an error banner. Every comparison states its `scope`: `same_powersets`, `same_archetype` or `cross_archetype` (with `scope_note`: the cut points are all-archetype, so a cross-archetype gap can be the archetype rather than the build). Powersets come from the picks (`build.picked_powersets` in each evaluation), not the request's spelling; refused columns are named in the note. The app shows it above the table at the lede size and flags a cross-archetype comparison. A scorecard has `scope: null`.
- **Table (`server/build_compare.py`, pure):** one row per rating category with each build's grade, value and why; `best` (the leading letter-graded cell(s); none on a tie or with fewer than two graded cells); `meaningful` when the grades differ or the gap is at least 10% of the larger value; `difference` = the gap. **No overall winner is ever declared** (M4's no-composite rule).
- **App:** a 📊 Rate this build button on the Stats control row, mirrored as a Build menu item (the menu presses the real button). It sends the build as OWNED (`buildWithAccolades()`; booster previews live in `PREVIEW_BOOSTS`, never in `build.powers`), shows the scorecard, offers "Compare with" any other saved character, and saves the result as a JSON file through `saveTextFile` (no save is modified). The renderer `renderRatingHtml` is pure and tested under node (`tools/test_rating_view.js`: escaping of user-typed names, refused columns, gap column, best and low-sample markers; negative-controlled). Driven through the real page in Chromium: menu item → dialog on Stats → graded rows (18 then, 20 since the toughness grades) → compare against a saved character → side-by-side with gaps, no page errors.
- **Searchable help:** a "Build rating" topic (Stats tab).

### ⚠ Rating-release blocker (owner review of #25)

**No M4 offense grade may ship for a build whose `confidence.offense_complete` is false.** The classification is done (`docs/EFFECTLESS-POWERS.md`): of 335 player-pickable records with no effect rows, **29 deal damage the model does not read** (31 until 2026-11-11: Fire Manipulation's Burn now carries its patch damage folded from its Fiery Aura siblings, and Blaster Archery's Ranged Shot turned out to be priced by the pet channel from its click twin) and have no record of ours carrying them (Savage Leap on four ATs, Rain of Arrows, Suppressive Fire, Psionic Lance, Storm Blast's Direct Strike, Aura of Insanity, Sniper Rifle, LRM Rocket and others). The rest are 142 non-damage effects we do not carry (Taunt, Gamma Boost class), 100 mode switches, 49 auto-granted records and 15 priced elsewhere (14 Mastermind upgrades + Ranged Shot). Remaining before offense grades ship (owner rulings, they move scores): source the 29 from the client (PATCH-WATCH export) with regression tests, or grade affected offense as Unknown/Incomplete. This measurement API is improved, not game-certified.

### Calibration owed (blocked: in-game measurement or an owner ruling)

These are the provisional inputs the scenario numbers rest on. The `confidence.sections.scenario` line says "provisional" until they are settled.

1. Scenario constants in `first_principles.SCENARIOS` (enemy_dps, rank_acc, ctrl_land, def_debuff_in, kb_in, slow_in): stated assumptions, not measured.
2. `_ATTACK_ACC_ENH` = 1.4 (typical slotted accuracy): marked PROVISIONAL in code.
3. Hasten elasticity (0.5 of damage is recharge-bound): a model constant.
4. Aura/patch proc valuation: field measured 10.66% per hit-tick vs the formula's 6.14% (open ruling, CLAUDE.md).
5. `mez_in` (incoming mez pressure): unblocks scoring of self mez protection, reported here as `mez_protection_not_scored`.
6. **Effect-less damaging powers (classified, see above and `docs/EFFECTLESS-POWERS.md`):** 31 pickable powers deal damage the engine credits at zero. Filling them is a data ruling (harden-before-certify applies: it moves scores). Related, found the same day: encounter_value's upgrade rule takes the two cheapest effect-less casts in a Mastermind summon set, so for Ninjas it picks Smoke Flash; whether that is the right second upgrade is unverified.
