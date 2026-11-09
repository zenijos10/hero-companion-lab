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
- unsupported: unrecognized power identifiers, plus `powers`: one row per power the model knowingly does not measure, with a reason. Effect-less records are sorted by `server/effectless.py` (one copy, shared with `tools/classify_effectless_powers.py`, which writes `docs/EFFECTLESS-POWERS.md`): `unread_redirect` (its effects are in twin records we already ship, listed in `twins`), `damaging_unread` (the game's help names damage, or it takes Damage enhancement, and no record of ours carries it), `effect_unread` (another effect we do not carry), `unpriced_mechanic` (a mode switch or an auto-granted record: nothing to read). Each row says `damaging`. Also `unknown_record` and `mez_protection_not_scored` (the open mez_in ruling). `modeled_without_effect_rows` lists effect-less powers that ARE priced elsewhere: the Mastermind upgrades in a Mastermind summon set, priced by their re-cast time (`first_principles.mastermind_upgrade_records`, the rule encounter_value uses). `effect_level_audit` is "power_level": detail is per power, not per effect row.
- confidence: `powers_read` of `powers_total` (picks the model reads at all; **not** a completeness score: a read power can still be priced only in part), `offense_complete` (false whenever a picked power deals damage the model does not read, or is unknown), and one line per section saying whether it is modeled, provisional (scenario constants) or a proxy.

### Emergency powers

A click power with timed self Defense/Resistance (Unstoppable, Elude, Strength of Will) is emergency mitigation. It is never counted in the sustained totals, even when the player ticked it (the ticked ones are listed in `inputs_normalized.emergency_excluded_from_sustained`). Each one gets a row: the per-type gain while active (measured by recalculating with it switched on), duration, recharge after global recharge (incl. Hasten) and its own slotting, uptime, and the penalties the game data attaches (endurance, recovery, regeneration or HP crashes). When the rows do not share one duration, `uniform_duration` is false and `uptime_by_effect` gives the exact uptime per effect/type; the headline `duration_seconds`/`uptime` is then the longest row. Penalties are the raw game-data rows (`penalty_basis`), not a normalized severity.
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

### ⚠ Rating-release blocker (owner review of #25)

**No M4 offense grade may ship for a build whose `confidence.offense_complete` is false.** The classification is done (`docs/EFFECTLESS-POWERS.md`): of 336 player-pickable records with no effect rows, **31 deal damage the model does not read**: 2 have their effects in twin records we already ship (Archery's Ranged Shot, Fire Manipulation's Burn) and 29 have no record of ours carrying them (Savage Leap on four ATs, Rain of Arrows, Suppressive Fire, Psionic Lance, Storm Blast's Direct Strike, Aura of Insanity, Sniper Rifle, LRM Rocket and others). The rest are 142 non-damage effects we do not carry (Taunt, Gamma Boost class), 100 mode switches, 49 auto-granted records and 14 Mastermind upgrades priced elsewhere. Remaining before offense grades ship (owner rulings, they move scores): read the 2 twin-backed redirects, and source the other 29 from the client (PATCH-WATCH export) with regression tests, or grade affected offense as Unknown/Incomplete. This measurement API is improved, not game-certified.

### Calibration owed (blocked: in-game measurement or an owner ruling)

These are the provisional inputs the scenario numbers rest on. The `confidence.sections.scenario` line says "provisional" until they are settled.

1. Scenario constants in `first_principles.SCENARIOS` (enemy_dps, rank_acc, ctrl_land, def_debuff_in, kb_in, slow_in): stated assumptions, not measured.
2. `_ATTACK_ACC_ENH` = 1.4 (typical slotted accuracy): marked PROVISIONAL in code.
3. Hasten elasticity (0.5 of damage is recharge-bound): a model constant.
4. Aura/patch proc valuation: field measured 10.66% per hit-tick vs the formula's 6.14% (open ruling, CLAUDE.md).
5. `mez_in` (incoming mez pressure): unblocks scoring of self mez protection, reported here as `mez_protection_not_scored`.
6. **Effect-less damaging powers (classified, see above and `docs/EFFECTLESS-POWERS.md`):** 31 pickable powers deal damage the engine credits at zero. Filling them is a data ruling (harden-before-certify applies: it moves scores). Related, found the same day: encounter_value's upgrade rule takes the two cheapest effect-less casts in a Mastermind summon set, so for Ninjas it picks Smoke Flash; whether that is the right second upgrade is unverified.
