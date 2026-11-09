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
- measurements.offense: original raw ST chain DPS/AoE metrics separately from scenario-adjusted personal damage contribution. Raw DPS does **not** include scenario hit chance.
- measurements.survival: in-combat defense and resistance vectors, `defense_out_of_combat` rows only where suppressible defense makes them differ, estimated time to live, availability and incoming/outgoing hit probabilities.
- measurements.resources: recharge bonus, Hasten's time-averaged bonus (support uptime uses passive + Hasten, the same recharge the scenario figures use), endurance recovery, chain and toggle drain, net/sustainability.
- measurements.support: control proxy and per-power breakdown, control uptime, buffs/debuffs in percent by effect, self/team healing proxy and resurrections.
- unsupported: unrecognized power identifiers, explicit note that per-effect unknown auditing is not implemented, reference to known-gaps ledger.
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
- [ ] Verify representative complete imported builds including incarnates, pets, controls and procs.
- [ ] Provide individually scenario-adjusted ST and AoE outputs rather than only weighted composite.
- [ ] Split sustained and emergency defensive metrics, including click uptime and restrictions.
- [ ] Add per-build unsupported-effect detail and confidence metadata.
- [ ] Verify provisional mechanics against live game client and calibrate encounter assumptions.
