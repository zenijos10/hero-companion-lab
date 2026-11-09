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

- ok, stage=measurements_only, schema_version: machine-readable status.
- versions: app, model, database name and database version, plus `scenario_fingerprint` (a hash of the scenario constants; it changes whenever any constant is tuned, MODEL_VERSION or not). Compare stored results only when every version field matches.
- inputs_normalized: `boosted_pieces_rated`, `external_buffs_removed`, `defense_basis` ("in_combat").
- build: archetype, primary, secondary, picked-power count.
- scenario: ID, enemy level shift/count, teammate count, duration, enemy damage type, the full parameter set and provenance.
- measurements.offense: raw ST chain DPS/AoE metrics (no scenario hit chance), then each part after the scenario: `scenario_single_target_dps`, `scenario_aoe_dps_per_target` with `scenario_aoe_targets`, and `scenario_pet_dps`. They are the exact parts of `scenario_personal_dps`: 0.4 x ST + 0.6 x AoE x targets + pets (pinned by the real-build battery). `first_principles.encounter_value` returns them as display-only keys; its score is byte-identical (checked on 42 build x scenario pairs).
- measurements.survival: `basis` (sustained = toggles and autos), `emergency_powers` (below), in-combat defense and resistance vectors, `defense_out_of_combat` rows only where suppressible defense makes them differ, estimated time to live, availability and incoming/outgoing hit probabilities.
- measurements.resources: recharge bonus, Hasten's time-averaged bonus (support uptime uses passive + Hasten, the same recharge the scenario figures use), endurance recovery, chain and toggle drain, net/sustainability.
- measurements.support: control proxy and per-power breakdown, control uptime, buffs/debuffs in percent by effect, self/team healing proxy and resurrections.
- unsupported: unrecognized power identifiers, plus `powers`: one row per power the model knowingly does not measure, with a reason: `unknown_record`, `no_modeled_effects` (a redirect whose effects live on another record, or an empty record) or `mez_protection_not_scored` (the open mez_in ruling). `effect_level_audit` is "power_level": detail is per power, not per effect row.
- confidence: `powers_modeled` of `powers_total` (picked powers the model reads), and one line per section saying whether it is modeled, provisional (scenario constants) or a proxy.

### Emergency powers

A click power with timed self Defense/Resistance (Unstoppable, Elude, Strength of Will) is emergency mitigation. It is never counted in the sustained totals, even when the player ticked it (the ticked ones are listed in `inputs_normalized.emergency_excluded_from_sustained`). Each one gets a row: the per-type gain while active (measured by recalculating with it switched on), duration, recharge after global recharge (incl. Hasten) and its own slotting, uptime, and the penalties the game data attaches (endurance, recovery, regeneration or HP crashes).
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
- [x] Verify representative complete builds including incarnates, pets, controls and procs (`tools/test_build_evaluation_builds.py`: real autopick + solve builds for a Mastermind, Controller, Brute with incarnates and an Archery Blaster, plus the pinned real Sidekick v5 fixture imported through `/build/import-sidekick`; finite-or-unknown, determinism, part-sum, +4 vs +1).
- [x] Provide individually scenario-adjusted ST and AoE outputs rather than only weighted composite.
- [x] Split sustained and emergency defensive metrics, including click uptime and restrictions.
- [x] Add per-build unsupported-effect detail and confidence metadata.
- [ ] **Blocked on game knowledge / owner rulings:** verify provisional mechanics against the live game and calibrate encounter assumptions. Nothing here can be settled from code; each needs an in-game measurement or a ruling (see below).

### Calibration owed (blocked: in-game measurement or an owner ruling)

These are the provisional inputs the scenario numbers rest on. The `confidence.sections.scenario` line says "provisional" until they are settled.

1. Scenario constants in `first_principles.SCENARIOS` (enemy_dps, rank_acc, ctrl_land, def_debuff_in, kb_in, slow_in): stated assumptions, not measured.
2. `_ATTACK_ACC_ENH` = 1.4 (typical slotted accuracy): marked PROVISIONAL in code.
3. Hasten elasticity (0.5 of damage is recharge-bound): a model constant.
4. Aura/patch proc valuation: field measured 10.66% per hit-tick vs the formula's 6.14% (open ruling, CLAUDE.md).
5. `mez_in` (incoming mez pressure): unblocks scoring of self mez protection, reported here as `mez_protection_not_scored`.
6. **New, found by this work:** Archery's Ranged Shot (`Blaster_Ranged.Archery.Ranged_Shot`) is a redirect record with no effect rows, so the engine gives it zero damage. 2,107 records in the shipped data have no effect rows; they are not yet classified (some are known mechanic toggles such as ammo swaps, some are redirects like this one), and any build that picks one now shows it under `unsupported.powers`. Whether the redirect records should be filled is a data ruling (harden-before-certify applies: it would move scores).
