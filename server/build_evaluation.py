"""Read-only, versioned measurements for COH build ratings (no grades yet).

No model arithmetic is duplicated here: Hero Companion's engine, encounter
physics and support evaluator remain authoritative. Input build data is copied
so callers do not lose their slotting or acquire transient calculation fields.
"""

import copy
import hashlib
import json
import math

import effectless
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


_MITIGATION = ("Defense", "Resistance")
_PENALTY_EFFECTS = ("Endurance", "Recovery", "Regeneration", "HitPoints")


def _emergency_rows(rec):
    """A click power's timed self defense/resistance rows (PvE), the shape of
    Unstoppable, Elude, Strength of Will: emergency mitigation, not sustained."""
    if not rec or rec.get("power_type") != 0:
        return []
    return [fx for fx in rec.get("self_effects") or []
            if fx.get("effect") in _MITIGATION and (fx.get("scale") or 0) > 0
            and (fx.get("duration") or 0) > 0 and fx.get("pv_mode") != 2]


def _typed_gain(after, before):
    """Per-type percentage points one power adds (measured: totals with it on
    minus totals with it off), only the types it moves."""
    gain = {}
    for kind in ("defense", "resistance"):
        rows = {}
        for name, row in (after.get(kind) or {}).items():
            was = ((before.get(kind) or {}).get(name) or {}).get("value") or 0.0
            delta = (row.get("value") or 0.0) - was
            if abs(delta) > 0.05:
                rows[name] = round(delta, 2)
        gain[kind] = dict(sorted(rows.items()))
    return gain


def _emergency_ledger(build_copy, sustained, power_records, ctx, set_bonuses, res_cap,
                      global_recharge):
    """Each emergency power: what it adds while up (measured by recalculating with
    it switched on), how long it lasts, its enhanced recharge, the resulting
    uptime, and the penalties the game data attaches (crashes)."""
    ledger = []
    for i, power in enumerate(build_copy["powers"]):
        rec = power_records.get(power["full_name"])
        rows = _emergency_rows(rec)
        if not rows:
            continue
        trial = copy.deepcopy(build_copy)
        trial["powers"][i]["include_in_totals"] = True
        active = engine.calculate_build(trial, set_bonuses, res_cap=res_cap, ctx=dict(ctx))
        durations = {}
        for fx in rows:              # one duration per effect/type, longest row wins
            key = f'{fx["effect"]}.{fx.get("damage_type") or "None"}'
            durations[key] = max(durations.get(key, 0.0), fx["duration"])
        duration = max(durations.values())
        uniform = len(set(durations.values())) == 1
        base_rech = rec.get("base_recharge") or 0.0
        local = role_output._power_enh(dict(rec, slots=power.get("slots") or []), ctx,
                                       ("RechargeTime",))["RechargeTime"]
        enh_rech = base_rech / (1.0 + global_recharge + local) if base_rech > 0 else None

        def _uptime(seconds):
            return round(min(1.0, seconds / enh_rech), 3) if enh_rech else None
        uptime = _uptime(duration)
        ledger.append({
            "power": power["full_name"], "display_name": rec.get("display_name"),
            "while_active_gain_percent_points": _typed_gain(active, sustained),
            "duration_seconds": _measurement(
                duration, "seconds", "game data, unenhanced; the longest row when "
                "durations differ (see uptime_by_effect)"),
            "uniform_duration": uniform,
            # exact per effect/type whenever the rows do not share one duration
            "uptime_by_effect": ({} if uniform else
                                 {k: _uptime(v) for k, v in sorted(durations.items())}),
            "recharge_seconds": _measurement(round(enh_rech, 1) if enh_rech else None, "seconds",
                                             "base recharge / (1 + global incl. Hasten + own slotting)"),
            "uptime": _measurement(uptime, "fraction",
                                   "duration / enhanced recharge, capped at 1"),
            "penalty_basis": "raw game-data rows (scale in modifier-table units), "
                             "not a normalized severity",
            "penalties": [{"effect": fx["effect"], "scale": fx.get("scale"),
                           "duration_seconds": fx.get("duration")}
                          for fx in rec.get("self_effects") or []
                          if fx.get("effect") in _PENALTY_EFFECTS and (fx.get("scale") or 0) < 0
                          and fx.get("pv_mode") != 2],
        })
    return ledger


# effectless.classify class -> the reason reported per build
_REASON = {
    "unread_twins_damage": "unread_redirect", "unread_twins": "unread_redirect",
    "damaging_unread": "damaging_unread", "effect_unread": "effect_unread",
    "mechanic": "unpriced_mechanic", "auto_granted": "unpriced_mechanic",
}
_UNREAD = ("unknown_record", "unread_redirect", "damaging_unread", "effect_unread")


def _records_by_set(power_records):
    by_set = {}
    for rec in power_records.values():
        by_set.setdefault(rec.get("powerset_full_name"), []).append(rec)
    return by_set


def _unsupported_powers(powers, power_records, powers_by_set, power_help):
    """Per power, what the model knowingly does not measure, and the effect-less
    powers that ARE priced elsewhere. Effect-less records are sorted by
    effectless.classify (one copy, shared with the report tool): an unread
    redirect (its twins are in our data), damage the game's help names but our
    record lacks, an effect we do not carry, or a mechanic that carries nothing.
    Plus unknown records, and self mez protection (carried, not scored: the
    open mez_in ruling)."""
    found, elsewhere = [], []
    for p in powers:
        fn = p["full_name"]
        rec = power_records.get(fn)
        if rec is None:
            found.append({"power": fn, "reason": "unknown_record",
                          "detail": "not in the shipped power data"})
            continue
        verdict = effectless.classify(rec, powers_by_set, (power_help or {}).get(fn),
                                      full_name=fn)
        if verdict and verdict["class"] == "modeled_elsewhere":
            elsewhere.append({"power": fn, "how": verdict["evidence"]})
        elif verdict:
            row = {"power": fn, "reason": _REASON[verdict["class"]],
                   "detail": verdict["evidence"],
                   "damaging": verdict["class"] in effectless.DAMAGING}
            if verdict.get("twins"):
                row["twins"] = verdict["twins"]
            found.append(row)
        if any(fx.get("effect") in ("MezProtection", "MezResist")
               for fx in rec.get("self_effects") or []):
            found.append({"power": fn, "reason": "mez_protection_not_scored",
                          "detail": "self mez protection is carried but not scored "
                                    "(needs the incoming-mez scenario input)"})
    return found, elsewhere


def _confidence(powers, unsupported):
    """How much to trust each section, and how many picks the model reads at all.
    The count is NOT model completeness: a read power can still be priced only
    in part (see unsupported.powers and docs/KNOWN-GAPS.md)."""
    blind = {u["power"] for u in unsupported if u["reason"] in _UNREAD}
    total = len({p["full_name"] for p in powers})
    return {
        "powers_read": _measurement(total - len(blind), "count",
                                    "picked powers the model reads (effect rows, or priced "
                                    "elsewhere); not a completeness score"),
        "powers_total": total,
        # false whenever a picked power deals damage the model does not read
        "offense_complete": not any(u["reason"] == "unknown_record" or u.get("damaging")
                                    for u in unsupported),
        "sections": {
            "offense_raw": "modeled: game data and the engine's chain",
            "scenario": "provisional: scenario constants (enemy damage, rank accuracy, "
                        "control landing) are stated assumptions, not measured",
            "survival_totals": "modeled: game data, caps applied",
            "emergency": "modeled uptime; gains measured by recalculation",
            "support": "proxy: control and healing units are model scores",
        },
    }


def evaluate(build, scenario, *, ctx, set_bonuses, res_cap, archetype_record,
             db_name, db_version, app_version, prepare=None,
             powers_by_set=None, power_help=None):
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
    # Sustained totals never count an emergency click, even one the player ticked.
    excluded = []
    for p in build_copy["powers"]:
        if _emergency_rows(power_records.get(p["full_name"])):
            if p.get("include_in_totals"):
                excluded.append(p["full_name"])
            p["include_in_totals"] = False
    normalized["emergency_excluded_from_sustained"] = excluded

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
    emergency = _emergency_ledger(build_copy, totals, power_records, ctx, set_bonuses,
                                  res_cap, global_recharge)
    unsupported, modeled_elsewhere = _unsupported_powers(
        build_copy["powers"], power_records,
        powers_by_set if powers_by_set is not None else _records_by_set(power_records),
        power_help)

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
                "scenario_single_target_dps": _measurement(
                    encounter.get("st_dps_scenario"), "damage_per_second",
                    "single-target chain after hit chance, level, slows, Hasten, meter, endurance"),
                "scenario_aoe_dps_per_target": _measurement(
                    encounter.get("aoe_dps_scenario_per_target"), "damage_per_second_per_target",
                    "AoE cycles after the same scenario factors"),
                "scenario_aoe_targets": encounter.get("aoe_targets"),
                "scenario_pet_dps": _measurement(
                    encounter.get("pet_dps_scenario"), "damage_per_second",
                    "pets at their own level, hit chance and uptime, after endurance"),
                "scenario_personal_dps": _measurement(
                    encounter.get("my_dps"), "damage_per_second_equivalent",
                    "scenario-weighted ST/AoE plus pets, hit chance, level, endurance and uptime"),
                "scenario_team_damage_amplified": _measurement(
                    encounter.get("amplified"), "damage_per_second_equivalent",
                    "scenario contribution created by buffs and resistance debuffs"),
            },
            "survival": {
                "basis": "sustained: toggles and autos; emergency clicks are reported separately",
                "emergency_powers": emergency,
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
            "powers": unsupported,
            "modeled_without_effect_rows": modeled_elsewhere,
            "effect_level_audit": "power_level",
            "known_gaps_reference": "docs/KNOWN-GAPS.md",
        },
        "confidence": _confidence(build_copy["powers"], unsupported),
        "limitations": [
            "Measured values are model estimates, not a live combat simulation.",
            "The offense raw DPS values do NOT include enemy-level hit chance; use scenario_personal_dps for scenario output.",
            "Control and healing proxy units are not literal seconds locked or HP restored.",
            "Emergency clicks are reported with gain and uptime, never folded into the sustained totals.",
            "PPM/proc and some scenario constants remain provisional; consult docs/KNOWN-GAPS.md and CLAUDE.md.",
            "This endpoint assigns no S-F ratings, percentile standings or Pareto rankings.",
        ],
    }
