"""Read-only, versioned measurements for COH build ratings (no grades yet).

No model arithmetic is duplicated here: Hero Companion's engine, encounter
physics and support evaluator remain authoritative. Input build data is copied
so callers do not lose their slotting or acquire transient calculation fields.
"""

import copy
import hashlib
import json
import math

import engine
import first_principles
import role_output

EVALUATION_SCHEMA_VERSION = 1
DEFAULT_SCENARIO = "rating_plus4"

# Rating scenarios live HERE, not in first_principles.SCENARIOS: registering one
# there would make it a valid `content` for every solve/assess route. Each is a
# named base scenario plus overrides, resolved at call time, so the versions
# fingerprint below always describes the numbers actually used.
RATING_SCENARIOS = {
    # +4 version of the general solo encounter; nothing else changed.
    "rating_plus4": ("general", {"shift": 4}),
}


def scenario_params(name):
    """The encounter constants for an evaluation scenario name, or None."""
    if not isinstance(name, str):
        return None
    if name in RATING_SCENARIOS:
        base, overrides = RATING_SCENARIOS[name]
        return dict(first_principles.SCENARIOS[base], **overrides)
    sc = first_principles.SCENARIOS.get(name)
    return dict(sc) if sc is not None else None


def _fingerprint(params):
    """Short stable hash of the scenario constants: tuning any of them changes it."""
    blob = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _exemplar_level(build):
    """The exemplar level /build/calculate would apply (1-49), else None."""
    try:
        level = int(build.get("exemplar_level"))
    except (TypeError, ValueError):
        return None
    return level if 1 <= level <= 49 else None


def _validate(build):
    """Every structural check, in one place (the route only resolves the archetype)."""
    if not isinstance(build, dict) or not isinstance(build.get("powers"), list):
        raise ValueError("A build object with a powers array is required.")
    for p in build["powers"]:
        if not isinstance(p, dict):
            raise ValueError("Each power must be an object.")
        if not isinstance(p.get("full_name"), str) or not p["full_name"].strip():
            raise ValueError("Each power needs a full_name string.")
        slots = p.get("slots")
        if slots is not None and (not isinstance(slots, list) or any(
                s is not None and not isinstance(s, dict) for s in slots)):
            raise ValueError("Power slots must be arrays of objects or null.")
    if build.get("pvp"):
        raise ValueError("PvP evaluation is not supported; rating scenarios are PvE.")
    if _exemplar_level(build) is not None:
        raise ValueError("Exemplar evaluation is not yet supported.")


_EXTERNAL_BUFF_FLAGS = ("include_external", "include_amplifiers")


def _clean_copy(build):
    """The copy that is rated: the player's own build, in combat. Other people's
    buffs and inspiration amplifiers are removed; combat suppression is on.

    Boosters are KEPT: `slot.boost` is the level the player owns (the Sidekick,
    Mids and in-game importers write it there; an HO at +3 is a level-53 HO), so
    stripping it would rate a weaker build than the one in game. A booster
    PREVIEW is the client's to leave out of an evaluation payload; the server
    cannot tell the two apart and says how many boosted pieces it rated."""
    clean = copy.deepcopy(build)
    external = [k for k in _EXTERNAL_BUFF_FLAGS if clean.pop(k, None)]
    clean["suppression"] = True
    boosted = sum(1 for p in clean["powers"] for slot in p.get("slots") or []
                  if slot and (slot.get("boost") or 0) > 0)
    return clean, {"boosted_pieces_rated": boosted,
                   "external_buffs_removed": bool(external),
                   "defense_basis": "in_combat"}


def _has_suppressible_effects(powers, power_records):
    """True when any power carries a combat-suppressed self effect (Hide class):
    only then can the out-of-combat defense differ from the in-combat one."""
    for p in powers:
        rec = power_records.get(p["full_name"]) or {}
        if any((fx.get("suppression") or 0) & engine.SUPPRESS_IN_COMBAT
               for fx in rec.get("self_effects") or []):
            return True
    return False


def _out_of_combat_rows(in_combat, out_of_combat):
    """Defense rows whose out-of-combat value differs (suppressible defense)."""
    rows = {}
    for name, row in sorted((out_of_combat or {}).items()):
        fight = ((in_combat or {}).get(name) or {}).get("value")
        value = row.get("value") if isinstance(row, dict) else None
        if isinstance(value, (int, float)) and isinstance(fight, (int, float)) \
                and abs(value - fight) > 0.05:
            rows[name] = _measurement(value, "percent",
                                      "out of combat; suppressible defense counted")
    return rows


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
             db_name, db_version, app_version, prepare=None):
    """Evaluate a build without optimization, rating or modifying player state.

    scenario must be a rating or registered scenario name. Context and game
    assets are injected by the server; `prepare(build)` (optional) enriches the
    working copy the way /build/calculate does. This function never loads or
    writes saved builds. A result is a versioned measurement contract, NOT a
    grade or certified comparison.
    """
    _validate(build)
    sc = scenario_params(scenario)
    if sc is None:
        raise ValueError("Unknown evaluation scenario.")
    archetype = build.get("archetype")
    if not isinstance(archetype, str) or archetype != archetype_record.get("name"):
        raise ValueError("Unknown build archetype.")

    build_copy, normalized = _clean_copy(build)
    if prepare is not None:
        prepare(build_copy)
    power_records = (ctx or {}).get("power_by_full") or {}
    unknown = sorted({p["full_name"] for p in build_copy["powers"]
                      if p["full_name"] not in power_records})

    totals = engine.calculate_build(build_copy, set_bonuses,
                                    res_cap=res_cap, ctx=dict(ctx))
    out_of_combat = {}
    if _has_suppressible_effects(build_copy["powers"], power_records):
        out_of_combat = engine.calculate_build(
            dict(copy.deepcopy(build_copy), suppression=False),
            set_bonuses, res_cap=res_cap, ctx=dict(ctx))
    encounter = first_principles.encounter_value(
        archetype, build_copy["powers"], ctx, totals, scenario=scenario,
        arch_row=archetype_record, role_output_mod=role_output, scenario_params=sc)
    offense = totals.get("offense") or {}
    endurance = totals.get("endurance") or {}
    rech_row = totals.get("recharge") or {}
    passive_recharge = (rech_row.get("value") or 0.0) / 100.0
    # Support output at the same recharge encounter_value uses: passive plus
    # Hasten's time-averaged bonus (one helper, so the two cannot disagree).
    hasten = first_principles.hasten_recharge_average(build_copy["powers"], passive_recharge)
    global_recharge = passive_recharge + hasten
    control_score, control_rows = role_output.build_control_output(
        build_copy["powers"], ctx)
    control_uptime = role_output.build_control_uptime(
        build_copy["powers"], ctx, global_recharge * 100.0)
    healing = role_output.build_heal_output(build_copy["powers"], ctx)
    debuffs = role_output.enhanced_debuff_totals(
        build_copy["powers"], ctx, global_recharge=global_recharge)
    buffs = role_output.enhanced_team_buffs(
        build_copy["powers"], ctx, global_recharge=global_recharge)

    # Raw offense is not an against-+4 damage figure; the encounter's my_dps
    # handles enemy level, hit chance, purple patch, pets and endurance instead.
    return {
        "ok": True,
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "stage": "measurements_only",
        "versions": {"app": app_version, "model": first_principles.MODEL_VERSION,
                     "database": db_name, "database_version": db_version,
                     "scenario_fingerprint": _fingerprint(sc)},
        "inputs_normalized": normalized,
        "build": {"archetype": archetype, "primary": build.get("primary"),
                  "secondary": build.get("secondary"),
                  "power_count": len(build_copy["powers"])},
        "scenario": {"id": scenario, "enemy_level_shift": sc["shift"],
                     "enemies": sc["enemies"], "teammates": sc["teammates"],
                     "duration_seconds": sc["length"],
                     "enemy_damage_type": sc.get("dmg_type"),
                     "parameters": dict(sorted(sc.items())),
                     "source": ("build_evaluation.RATING_SCENARIOS" if scenario in RATING_SCENARIOS
                                else "first_principles.SCENARIOS")},
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
                "defense": _typed_stat(totals.get("defense"),
                                       "in combat (suppressible defense excluded); before scenario hit modeling"),
                "defense_out_of_combat": _out_of_combat_rows(totals.get("defense"),
                                                             out_of_combat.get("defense")),
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
                "hasten_average_recharge": _measurement(round(hasten * 100.0, 2), "percent_bonus",
                                                        "Hasten time-averaged; added for support uptime"),
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
