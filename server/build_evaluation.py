"""Read-only, versioned measurements for COH build ratings (no grades yet).

No model arithmetic is duplicated here: Hero Companion's engine, encounter
physics and support evaluator remain authoritative. Input build data is copied
so callers do not lose their slotting or acquire transient calculation fields.
"""

import copy
import math

import engine
import first_principles
import role_output

EVALUATION_SCHEMA_VERSION = 1
DEFAULT_SCENARIO = "rating_plus4"


def _measurement(value, unit, basis):
    """Represent a numeric result with an explicit unit and measurement basis."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return {"value": None, "unit": unit, "basis": basis, "status": "unknown"}
    return {"value": value, "unit": unit, "basis": basis, "status": "modeled"}


def _typed_stat(rows, basis):
    return {name: _measurement(row.get("value") if isinstance(row, dict) else None,
                               "percent", basis)
            for name, row in sorted((rows or {}).items())}


def evaluate(build, scenario, *, ctx, set_bonuses, res_cap, archetype_record,
             db_name, db_version, app_version):
    """Evaluate a build without optimization, rating or modifying player state.

    scenario must be a registered name. Context and game assets are injected
    by the server; this function never loads or writes saved builds. A result is
    a versioned measurement contract, NOT a grade or certified comparison.
    """
    if not isinstance(build, dict) or not isinstance(build.get("powers"), list):
        raise ValueError("A build object with a powers array is required.")
    if not isinstance(scenario, str) or scenario not in first_principles.SCENARIOS:
        raise ValueError("Unknown evaluation scenario.")
    archetype = build.get("archetype")
    if not isinstance(archetype, str) or archetype != archetype_record.get("name"):
        raise ValueError("Unknown build archetype.")

    build_copy = copy.deepcopy(build)
    power_records = (ctx or {}).get("power_by_full") or {}
    if any(not isinstance(p, dict) for p in build_copy["powers"]):
        raise ValueError("Each power must be an object.")
    unknown = sorted({p.get("full_name") or "(missing full_name)"
                      for p in build_copy["powers"]
                      if p.get("full_name") not in power_records})

    totals = engine.calculate_build(build_copy, set_bonuses,
                                    res_cap=res_cap, ctx=dict(ctx))
    encounter = first_principles.encounter_value(
        archetype, build_copy["powers"], ctx, totals, scenario=scenario,
        arch_row=archetype_record, role_output_mod=role_output)
    offense = totals.get("offense") or {}
    endurance = totals.get("endurance") or {}
    rech_row = totals.get("recharge") or {}
    global_recharge = (rech_row.get("value") or 0.0) / 100.0
    control_score, control_rows = role_output.build_control_output(
        build_copy["powers"], ctx)
    control_uptime = role_output.build_control_uptime(
        build_copy["powers"], ctx, rech_row.get("value") or 0.0)
    healing = role_output.build_heal_output(build_copy["powers"], ctx)
    debuffs = role_output.enhanced_debuff_totals(
        build_copy["powers"], ctx, global_recharge=global_recharge)
    buffs = role_output.enhanced_team_buffs(
        build_copy["powers"], ctx, global_recharge=global_recharge)
    sc = first_principles.SCENARIOS[scenario]

    # Raw offense is not an against-+4 damage figure; the encounter's my_dps
    # handles enemy level, hit chance, purple patch, pets and endurance instead.
    return {
        "ok": True,
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "stage": "measurements_only",
        "versions": {"app": app_version, "model": first_principles.MODEL_VERSION,
                     "database": db_name, "database_version": db_version},
        "build": {"archetype": archetype, "primary": build.get("primary"),
                  "secondary": build.get("secondary"),
                  "power_count": len(build_copy["powers"])},
        "scenario": {"id": scenario, "enemy_level_shift": sc["shift"],
                     "enemies": sc["enemies"], "teammates": sc["teammates"],
                     "duration_seconds": sc["length"],
                     "enemy_damage_type": sc.get("dmg_type"),
                     "source": "first_principles.SCENARIOS"},
        "measurements": {
            "offense": {
                "single_target_dps_raw": _measurement(
                    offense.get("st_dps"), "damage_per_second",
                    "120-second greedy chain; before scenario hit chance and purple patch"),
                "aoe_dps_raw_per_target": _measurement(
                    offense.get("aoe_dps"), "damage_per_second_per_target",
                    "sum of AoE attack cycles; before scenario hit chance and purple patch"),
                "aoe_burst_raw_per_target": _measurement(
                    offense.get("aoe_burst"), "damage_per_target",
                    "sum of AoE power damage; not a timed burst rotation"),
                "scenario_personal_dps": _measurement(
                    encounter.get("my_dps"), "damage_per_second_equivalent",
                    "scenario-weighted ST/AoE plus pets, hit chance, level, endurance and uptime"),
                "scenario_team_damage_amplified": _measurement(
                    encounter.get("amplified"), "damage_per_second_equivalent",
                    "scenario contribution created by buffs and resistance debuffs"),
            },
            "survival": {
                "defense": _typed_stat(totals.get("defense"), "build totals before scenario hit modeling"),
                "resistance": _typed_stat(totals.get("resistance"), "build totals, AT caps applied"),
                "time_to_live": _measurement(encounter.get("ttl"), "seconds",
                                              "scenario damage pressure and sustain; estimate"),
                "availability": _measurement(encounter.get("availability"), "fraction",
                                             "scenario survival and control-pressure model"),
                "incoming_melee_hit": _measurement(encounter.get("hit_ml"), "probability",
                                                   "scenario enemy attack landing probability"),
                "incoming_ranged_hit": _measurement(encounter.get("hit_rn"), "probability",
                                                    "scenario ranged/AoE landing probability"),
                "outgoing_hit": _measurement(encounter.get("hit_out"), "probability",
                                             "scenario player attack landing probability"),
                "scenario_damage_prevented": _measurement(
                    encounter.get("prevented"), "damage_per_second_equivalent",
                    "scenario support/control/healing prevented-damage proxy"),
            },
            "resources": {
                "global_recharge": _measurement(rech_row.get("value"), "percent_bonus",
                                                "build passive plus modeled averaged proc recharge"),
                "recovery_per_second": _measurement(endurance.get("recovery_per_sec"),
                                                     "endurance_per_second", "build endurance ledger"),
                "chain_drain_per_second": _measurement(endurance.get("chain_drain_per_sec"),
                                                        "endurance_per_second", "build attack chain"),
                "toggle_drain_per_second": _measurement(endurance.get("toggle_drain_per_sec"),
                                                         "endurance_per_second", "active combat toggles"),
                "net_per_second": _measurement(endurance.get("net_per_sec"),
                                               "endurance_per_second", "recovery minus combat drain"),
                "sustainable": endurance.get("sustainable"),
                "travel_in_combat": endurance.get("travel_in_combat"),
            },
            "support": {
                "control_proxy": _measurement(control_score, "weighted_mez_seconds_proxy",
                                               "heuristic magnitude/duration/area; not exact lockdown"),
                "control_by_power": [{"power": name, "proxy_score": score}
                                     for name, score in control_rows],
                "hard_control_uptime": control_uptime,
                "team_buff_percent_by_effect": dict(sorted(buffs.items())),
                "enemy_debuff_percent_by_effect": dict(sorted(debuffs.items())),
                "healing_proxy": {"team_per_second": healing.get("team_hps"),
                                  "self_per_second": healing.get("self_hps"),
                                  "resurrection_powers": healing.get("rez"),
                                  "unit": "model_heal_units_per_second"},
            },
        },
        "unsupported": {
            "unknown_power_records": unknown,
            "effect_level_audit": "not_implemented",
            "known_gaps_reference": "docs/KNOWN-GAPS.md",
        },
        "limitations": [
            "Measured values are model estimates, not a live combat simulation.",
            "The offense raw DPS values do NOT include enemy-level hit chance; use scenario_personal_dps for scenario output.",
            "Control and healing proxy units are not literal seconds locked or HP restored.",
            "Click emergency defenses are not separately measured in this version.",
            "PPM/proc and some scenario constants remain provisional; consult docs/KNOWN-GAPS.md and CLAUDE.md.",
            "This endpoint assigns no S-F ratings, percentile standings or Pareto rankings.",
        ],
    }
