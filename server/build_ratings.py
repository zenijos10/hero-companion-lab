"""M4: S-F category ratings over the /build/evaluate measurements.

Owner's rulings (2026-11-10): +4 is the default rating scenario; thresholds
start as FIXED numbers, set with the shipped champion builds as a guideline,
and move as more builds come in; the champion roster is NOT the comparison
population (that is worked out as we go).

The numbers live in data/rating_thresholds.json (written by
tools/calibrate_rating_thresholds.py, editable by hand). Each grade keeps its
exact measurement beside it. Labels besides S-F:
  Unknown  the measurement is missing, or offense is incomplete (a picked
           power deals damage the model does not read: no offense grade)
  None     the capability is absent (zero control, no team buff, ...)
  N/A      the category cannot apply (pet damage on a build with no pets)
Ratings are given only when the evaluation ran in the scenario the thresholds
were calibrated for, with the same scenario fingerprint; otherwise the
response says why it is not rated instead of grading against the wrong fight.
"""
import json
import os
import re

import range_profile
import rating_measures

GRADES = ("S", "A", "B", "C", "D")      # F = below the D cut
LOW_SAMPLE = 30     # cuts set from fewer champions than this are flagged low_sample
THRESHOLDS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "rating_thresholds.json")


def _m(path):
    """Extractor for a {value,...} measurement at a dotted path in measurements."""
    def get(ev):
        node = ev.get("measurements") or {}
        for part in path.split("."):
            node = (node or {}).get(part) if isinstance(node, dict) else None
        if isinstance(node, dict) and "value" in node:
            return node["value"]
        return node if isinstance(node, (int, float)) and not isinstance(node, bool) else None
    return get


def _mean_of(path, keys):
    def get(ev):
        rows = ((ev.get("measurements") or {}).get("survival") or {}).get(path) or {}
        vals = [(rows.get(k) or {}).get("value") for k in keys]
        vals = [v for v in vals if isinstance(v, (int, float))]
        return sum(vals) / len(vals) if len(vals) == len(keys) else None
    return get


def _summary(ev):
    """The support ledger's summary, or None when the evaluation carries none
    (then every support category is Unknown, never a measured zero)."""
    return (((ev.get("measurements") or {}).get("support") or {})
            .get("team_support") or {}).get("summary")


def _ally_heal(ev):
    summary = _summary(ev)
    if summary is None or "ally_heals" not in summary:
        return None
    return (summary.get("ally_heals") or {}).get("sustained_per_second", 0.0)


def _summons(ev):
    """Picked powers that summon something, from the records (not from pet DPS)."""
    return (ev.get("build") or {}).get("summon_powers")


_UNREAD = ("unknown_record", "unread_redirect", "damaging_unread", "effect_unread")

# Which capability family an unread power could hide, from the game's own short
# help ("Ranged, Ally Heal", "Ranged, Foe -Res", "Foe Hold"). A power whose help
# names no family cannot make that family Unknown (a Brute's Taunt is not a team
# buff); a power with no help at all, or an unknown record, could be anything.
_FAMILY_WORDS = {
    "ally": re.compile(r"\b(Ally|Allies|Team|Teammates?|Friend)\b"),
    "debuff": re.compile(r"(Foe|Target)\s*-|-(Res|Def|ToHit|DMG|Dam|Regen|Rech|SPD|Recharge)"),
    "control": re.compile(r"\b(Hold|Sleep|Immobili[sz]e|Disorient|Stun|Confuse|Fear|Terrori[sz]e|Knock(back|down|up))\b"),
}
# _CATEGORY_FAMILY (which capability family hides each category) is built
# below CATEGORIES, from the same table.


def _unread_families(ev):
    """The capability families an unread power might be hiding."""
    families = set()
    for u in (ev.get("unsupported") or {}).get("powers") or []:
        if u.get("reason") not in _UNREAD:
            continue
        text = u.get("short_help")
        if u.get("reason") == "unknown_record" or not text:
            return set(_FAMILY_WORDS)              # no evidence: could be anything
        families |= {f for f, rx in _FAMILY_WORDS.items() if rx.search(text)}
    return families


_TYPES = ("Cold", "Energy", "Fire", "Lethal", "Negative", "Psionic", "Smashing", "Toxic")
_POSITIONS = ("Melee", "Ranged", "AoE")


def _by_type(bucket, effect):
    """One effect type from the evaluation's support_by_type (rating_measures):
    None when the evaluation carries no breakdown (Unknown, never a measured
    zero); 0 when it was measured and the build has none of the type."""
    def get(ev):
        types = ((ev.get("measurements") or {}).get("support") or {}).get("support_by_type")
        if types is None or bucket not in types:
            return None
        return (types.get(bucket) or {}).get(effect, 0.0)
    return get


# The buff and debuff types graded one by one (owner, 2026-11-11: "each type of
# debuff should matter"). key: (label, bucket, game effect, unit). AV-facing
# debuffs land from every power; spawn-facing ones from area powers.
BUFF_TYPES = {
    "buff_defense": ("Team defense buff", "Defense"),
    "buff_resistance": ("Team resistance buff", "Resistance"),
    "buff_damage": ("Team damage buff", "DamageBuff"),
    "buff_tohit": ("Team to-hit buff", "ToHit"),
    "buff_recharge": ("Team recharge buff", "RechargeTime"),
    "buff_recovery": ("Team recovery buff", "Recovery"),
    "buff_regeneration": ("Team regeneration buff", "Regeneration"),
    "buff_hitpoints": ("Team max HP buff", "HitPoints"),
}
_TYPE_UNIT = {"HitPoints": "hit_points"}          # rating_measures.ABSOLUTE_TYPES
DEBUFF_TYPES = {
    "debuff_resistance_av": ("-Resistance vs an AV", "debuffs_vs_av_percent", "Resistance", "percent"),
    "debuff_regeneration_av": ("-Regeneration vs an AV", "debuffs_vs_av_percent", "Regeneration", "percent"),
    "debuff_hitpoints_av": ("-Max HP vs an AV", "debuffs_vs_av_percent", "HitPoints", "hit_points"),
    "debuff_defense_spawn": ("-Defense vs a spawn", "debuffs_vs_spawn_percent", "Defense", "percent"),
    "debuff_tohit_spawn": ("-ToHit vs a spawn", "debuffs_vs_spawn_percent", "ToHit", "percent"),
    "debuff_damage_spawn": ("-Damage vs a spawn", "debuffs_vs_spawn_percent", "DamageBuff", "percent"),
    "debuff_slow_spawn": ("-Speed (slow) vs a spawn", "debuffs_vs_spawn_percent", "Slow", "percent"),
    "debuff_recharge_spawn": ("-Recharge vs a spawn", "debuffs_vs_spawn_percent", "RechargeTime", "percent"),
    "debuff_recovery_spawn": ("-Recovery vs a spawn", "debuffs_vs_spawn_percent", "Recovery", "percent"),
    "debuff_ddr_spawn": ("Lowers enemies' defense debuff resistance", "debuffs_vs_spawn_percent",
                         "DefDebuffResist", "percent"),
    "debuff_endurance_spawn": ("Endurance drain vs a spawn", "drains_per_second_percent",
                               "Endurance", "percent_per_second"),
}


def _debuff_resist(key):
    def get(ev):
        dr = ((ev.get("measurements") or {}).get("survival") or {}).get("debuff_resistance")
        return None if dr is None else dr.get(key, 0.0)
    return get


# key: (label, extractor, unit, kind). kind: "offense" (Unknown while offense is
# incomplete), "stat" (always graded), "capability" (None when zero),
# "pets" (N/A without pets).
CATEGORIES = {
    "single_target_damage": ("Single-target damage", _m("offense.scenario_single_target_dps"),
                             "damage_per_second", "offense"),
    "aoe_damage": ("Area damage", _m("offense.scenario_aoe_dps_per_target"),
                   "damage_per_second_per_target", "offense"),
    "pet_damage": ("Pet damage", _m("offense.scenario_pet_dps"), "damage_per_second", "pets"),
    "survival": ("Survival (time to live)", _m("survival.time_to_live"), "seconds", "stat"),
    "toughness": ("Toughness (damage you can take)", _m("survival.toughness"),
                  "incoming_damage_per_second", "stat"),
    "toughness_vs_archetype": ("Toughness for its archetype", _m("survival.toughness_vs_archetype"),
                               "multiple_of_bare_archetype", "stat"),
    "defense": ("Defense (melee/ranged/AoE mean)", _mean_of("defense", _POSITIONS), "percent", "stat"),
    "resistance": ("Resistance (8-type mean)", _mean_of("resistance", _TYPES), "percent", "stat"),
    "debuff_resist_defense": ("Defense debuff resistance (DDR)", _debuff_resist("defense_debuff"),
                              "percent", "capability"),
    "debuff_resist_slow": ("Slow and -Recharge resistance", _debuff_resist("slow_and_recharge_debuff"),
                           "percent", "capability"),
    "endurance": ("Endurance (net per second)", _m("resources.net_per_second"),
                  "endurance_per_second", "stat"),
    "recharge": ("Recharge", _m("resources.global_recharge"), "percent_bonus", "stat"),
    "control": ("Control (all)", _m("support.control_proxy"), "weighted_mez_seconds_proxy", "capability"),
    "control_single_target": ("Control, single target", _m("support.control_single_target"),
                              "weighted_mez_seconds_proxy", "capability"),
    "control_aoe": ("Control, area", _m("support.control_aoe"), "weighted_mez_seconds_proxy",
                    "capability"),
    "healing": ("Ally healing", _ally_heal, "model_heal_units_per_second", "capability"),
    # the rarity-weighted support index is graded from the per-type values
    # (rate()); it sits beside healing so the Support section stays together
    "support_index": ("Team support (rarity-weighted)", None, "support_index_points",
                      "capability"),
}
SUPPORT_INDEX = "support_index"
CATEGORIES.update({key: (label, _by_type("buffs_average_percent", effect),
                         _TYPE_UNIT.get(effect, "percent"), "capability")
                   for key, (label, effect) in BUFF_TYPES.items()})
CATEGORIES.update({key: (label, _by_type(bucket, effect), unit, "capability")
                   for key, (label, bucket, effect, unit) in DEBUFF_TYPES.items()})

_CATEGORY_FAMILY = dict({"healing": "ally", "control": "control",
                         "control_single_target": "control", "control_aoe": "control",
                         SUPPORT_INDEX: "ally"},
                        **{k: "ally" for k in BUFF_TYPES}, **{k: "debuff" for k in DEBUFF_TYPES})
# a type's effect (the rarity census key) and its side
_TYPE_EFFECT = dict({k: ("buff", e) for k, (_l, e) in BUFF_TYPES.items()},
                    **{k: ("debuff", e) for k, (_l, _b, e, _u) in DEBUFF_TYPES.items()})

# which range profile (measurements.range_profile.profiles) each category reads:
# the profile built from the same powers its value counts
_BUCKET_PROFILE = {"debuffs_vs_av_percent": "debuff_av", "debuffs_vs_spawn_percent": "debuff_spawn",
                   "drains_per_second_percent": "drain"}
_RANGE_KEY = dict({"single_target_damage": "single_target_damage", "aoe_damage": "aoe_damage",
                   "pet_damage": "pet_damage", "control": "control",
                   "control_single_target": "control_single_target", "control_aoe": "control_aoe",
                   "healing": "healing", SUPPORT_INDEX: "support"},
                  **{k: f"buff:{e}" for k, (_l, e) in BUFF_TYPES.items()},
                  **{k: f"{_BUCKET_PROFILE[b]}:{e}" for k, (_l, b, e, _u) in DEBUFF_TYPES.items()})

# The scorecard's sections, one per category, in CATEGORIES order (the
# renderer bands rows by this, so a section is never split).
SECTIONS = dict({k: "Damage" for k in ("single_target_damage", "aoe_damage", "pet_damage")},
                **{k: "Survival" for k in ("survival", "toughness", "toughness_vs_archetype",
                                           "defense", "resistance", "debuff_resist_defense",
                                           "debuff_resist_slow")},
                **{k: "Resources" for k in ("endurance", "recharge")},
                **{k: "Control" for k in ("control", "control_single_target", "control_aoe")},
                **{k: "Support" for k in ("healing", "support_index")},
                **{k: "Team buffs" for k in BUFF_TYPES},
                **{k: "Debuffs" for k in DEBUFF_TYPES})


def support_index(values, cuts, rarity):
    """Sum over every buff and debuff type the build has: rarity weight x
    (value / that type's median cut). 1 point = one common type at a typical
    strength; a rare type (-Max HP, -DDR, team regeneration) counts several.
    None when the inputs to judge it are missing."""
    if rarity is None:
        return None
    total = 0.0
    for key, (side, effect) in _TYPE_EFFECT.items():
        value, typical = values.get(key), ((cuts.get(key) or {}).get("cuts") or {}).get("B")
        if not value or value <= 0 or not typical:
            continue
        weight = ((rarity.get(side) or {}).get(effect) or {}).get("weight") or 1.0
        total += weight * value / typical
    return round(total, 3)


def _toughness_detail(ev):
    """'weakest 70.7 dmg/s: Psionic (melee, ranged, AoE); a bare archetype takes 61.5 dmg/s'."""
    t = ((ev.get("measurements") or {}).get("survival") or {}).get("toughness") or {}
    w = t.get("weakest") or {}
    cells, value = w.get("cells"), w.get("value")
    if not cells or not isinstance(value, (int, float)):
        return None
    positions = {}
    for pos, dtype in cells:
        positions.setdefault(dtype, []).append(pos)
    where = "; ".join(f"{d} ({', '.join(p if p == 'AoE' else p.lower() for p in ps)})"
                      for d, ps in positions.items())
    text = f"weakest {value:g} dmg/s: {where}"
    bare = t.get("bare_archetype")
    if isinstance(bare, (int, float)):
        text += f"; a bare archetype takes {bare:g} dmg/s"
    return text


def _section(ev, name):
    return (ev.get("measurements") or {}).get(name) or {}


def _types_detail(field):
    def get(ev):
        return rating_measures.describe_types(_section(ev, "offense").get(field))
    return get


def _cascade_detail(ev):
    """'+4 enemies keep a 7.4% floor to hit; steady -Defense 2.0% (8.1% with no DDR)'."""
    c = _section(ev, "survival").get("defense_cascade") or {}
    if c.get("model") != "cascade":
        return None
    pct = lambda x: f"{x * 100:.1f}%"  # noqa: E731
    shift = (ev.get("scenario") or {}).get("enemy_level_shift")
    who = f"+{shift} enemies" if isinstance(shift, int) and shift > 0 else "Enemies"
    text = (f"{who} always keep a {pct(c['hit_chance_floor'])} chance to hit; "
            f"their -Defense settles at {pct(c['steady_def_debuff'])}")
    if c["steady_def_debuff_without_ddr"] > c["steady_def_debuff"]:
        text += f" ({pct(c['steady_def_debuff_without_ddr'])} with no DDR)"
    return text + f", hit chance {pct(c['hit_chance_before'])} -> {pct(c['hit_chance_after'])}"


def _rarity_detail(key):
    def get(ev):
        side, effect = _TYPE_EFFECT[key]
        r = ((_section(ev, "support").get("effect_rarity") or {}).get(side) or {}).get(effect)
        if not r:
            return None
        return f"offered by {r['powersets']} player powersets (rarity weight {r['weight']:g})"
    return get


def _not_read_detail(ev):
    dr = _section(ev, "survival").get("debuff_resistance") or {}
    missing = dr.get("not_read")
    return ("not in our data yet: " + ", ".join(missing)) if missing else None


# one line of context shown beside a grade (the grade itself still reads `value`)
_DETAIL = dict({"toughness": _toughness_detail,
                "single_target_damage": _types_detail("damage_types_single_target"),
                "aoe_damage": _types_detail("damage_types_aoe"), "debuff_resist_defense": _cascade_detail,
                "debuff_resist_slow": _not_read_detail},
               **{k: _rarity_detail(k) for k in _TYPE_EFFECT})


def measure(evaluation, thresholds=None):
    """{category: value} straight from an evaluation (the calibration reads this
    too). The support index needs the per-type median cuts, so it is measured
    only when thresholds are given."""
    out = {key: spec[1](evaluation) for key, spec in CATEGORIES.items() if spec[1]}
    out[SUPPORT_INDEX] = None
    if thresholds:
        rarity = _section(evaluation, "support").get("effect_rarity")
        out[SUPPORT_INDEX] = support_index(out, thresholds.get("categories") or {}, rarity)
    return out


def _range(ev, key):
    """(profile, 'N% melee, N% midrange, N% range') for a category."""
    profiles = ((ev.get("range_profile") or {}).get("profiles")) or {}
    prof = profiles.get(_RANGE_KEY.get(key, "overall"))
    return prof, range_profile.describe(prof)


def load_thresholds(path=THRESHOLDS_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def grade(value, cuts):
    """S..D for the first cut the value reaches (cuts descend), else F."""
    for letter in GRADES:
        if value >= cuts[letter]:
            return letter
    return "F"


def _not_rated(reason, thresholds=None):
    return {"status": "not_rated", "reason": reason,
            "thresholds_version": (thresholds or {}).get("version")}


def rate(evaluation, thresholds):
    """Category ratings for one /build/evaluate result."""
    if not thresholds:
        return _not_rated("no rating thresholds are installed")
    scenario = evaluation.get("scenario") or {}
    if scenario.get("id") != thresholds.get("scenario"):
        return _not_rated(f"thresholds are calibrated for {thresholds.get('scenario')}, "
                          f"not {scenario.get('id')}", thresholds)
    versions = evaluation.get("versions") or {}
    if versions.get("scenario_fingerprint") != thresholds.get("scenario_fingerprint"):
        return _not_rated("the scenario constants changed since the thresholds were "
                          "calibrated; recalibrate", thresholds)
    if versions.get("model") != thresholds.get("model_version"):
        return _not_rated(f"the thresholds were calibrated on model "
                          f"v{thresholds.get('model_version')}, this evaluation ran on "
                          f"v{versions.get('model')}; recalibrate", thresholds)
    if thresholds.get("database_version") and \
            versions.get("database_version") != thresholds.get("database_version"):
        return _not_rated(f"the thresholds were calibrated on game data "
                          f"{thresholds.get('database_version')}, this evaluation ran on "
                          f"{versions.get('database_version')}; recalibrate", thresholds)
    offense_ok = (evaluation.get("confidence") or {}).get("offense_complete", False)
    unread = _unread_families(evaluation)
    summons = _summons(evaluation)
    values = measure(evaluation, thresholds)
    out = {}
    for key, (label, _get, unit, kind) in CATEGORIES.items():
        value = values[key]
        spec = (thresholds.get("categories") or {}).get(key, {})
        cuts = spec.get("cuts")
        row = {"label": label, "section": SECTIONS.get(key), "value": value, "unit": unit,
               "cuts": cuts,
               "sample_size": spec.get("sample_size"),
               "low_sample": (spec.get("sample_size") or 0) < LOW_SAMPLE}
        if kind == "pets" and summons is None:
            row.update(grade="Unknown", why="the evaluation does not list summon powers")
        elif kind == "pets" and not summons:
            row.update(grade="N/A", why="the build picks no power that summons a pet")
        elif kind == "pets" and not value:
            row.update(grade="Unknown", why="the build summons pets whose damage the model "
                                            "does not price")
        elif kind == "offense" and not offense_ok:
            row.update(grade="Unknown", why="a picked power deals damage the model does not "
                                            "read (unsupported.powers, damaging: true)")
        elif value is None:
            row.update(grade="Unknown", why="not measured")
        elif kind == "capability" and value <= 0 and _CATEGORY_FAMILY.get(key) in unread:
            row.update(grade="Unknown", why="none measured, but the build picks powers whose "
                                            "effects the model does not read")
        elif kind == "capability" and value <= 0:
            row.update(grade="None", why="the build has none of this")
        elif not cuts:
            row.update(grade="Unknown", why="no threshold for this category yet")
        else:
            row["grade"] = grade(value, cuts)
        if key in _DETAIL:
            row["detail"] = _DETAIL[key](evaluation)
        # where it is delivered: only for something the build has
        row["range"], row["where"] = (_range(evaluation, key) if row.get("grade") not in
                                      ("None", "N/A") else (None, None))
        out[key] = row
    return {"status": "rated", "thresholds_version": thresholds.get("version"),
            "scenario": thresholds.get("scenario"), "provisional": True,
            "population_note": "cut points come from optimized itrial champions as a "
                               "guideline; they are NOT player-population percentiles",
            "basis": thresholds.get("method"), "categories": out}
