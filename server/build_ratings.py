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

GRADES = ("S", "A", "B", "C", "D")      # F = below the D cut
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


def _support(section, bucket, effect):
    def get(ev):
        summary = ((((ev.get("measurements") or {}).get("support") or {})
                    .get("team_support") or {}).get("summary") or {})
        return ((summary.get(section) or {}).get(bucket) or {}).get(effect, 0.0)
    return get


def _ally_heal(ev):
    summary = ((((ev.get("measurements") or {}).get("support") or {})
                .get("team_support") or {}).get("summary") or {})
    return (summary.get("ally_heals") or {}).get("sustained_per_second", 0.0)


def _has_pets(ev):
    return bool(((ev.get("measurements") or {}).get("offense") or {})
                .get("scenario_pet_dps", {}).get("value"))


_TYPES = ("Cold", "Energy", "Fire", "Lethal", "Negative", "Psionic", "Smashing", "Toxic")
_POSITIONS = ("Melee", "Ranged", "AoE")
_DEB = "debuffs_landing_average_percent"
_BUF = "buffs_average_percent"

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
    "defense": ("Defense (melee/ranged/AoE mean)", _mean_of("defense", _POSITIONS), "percent", "stat"),
    "resistance": ("Resistance (8-type mean)", _mean_of("resistance", _TYPES), "percent", "stat"),
    "endurance": ("Endurance (net per second)", _m("resources.net_per_second"),
                  "endurance_per_second", "stat"),
    "recharge": ("Recharge", _m("resources.global_recharge"), "percent_bonus", "stat"),
    "control": ("Control", _m("support.control_proxy"), "weighted_mez_seconds_proxy", "capability"),
    "healing": ("Ally healing", _ally_heal, "model_heal_units_per_second", "capability"),
    "buff_defense": ("Team defense buff", _support(_BUF, "sustained", "Defense"), "percent", "capability"),
    "buff_damage": ("Team damage buff", _support(_BUF, "sustained", "DamageBuff"), "percent", "capability"),
    "buff_recharge": ("Team recharge buff", _support(_BUF, "sustained", "RechargeTime"),
                      "percent", "capability"),
    "debuff_resistance_av": ("-Resistance vs an AV", _support(_DEB, "single_target_vs_av", "Resistance"),
                             "percent", "capability"),
    "debuff_regeneration_av": ("-Regeneration vs an AV",
                               _support(_DEB, "single_target_vs_av", "Regeneration"),
                               "percent", "capability"),
    "debuff_defense_spawn": ("-Defense vs a spawn", _support(_DEB, "aoe_vs_scenario", "Defense"),
                             "percent", "capability"),
    "debuff_tohit_spawn": ("-ToHit vs a spawn", _support(_DEB, "aoe_vs_scenario", "ToHit"),
                           "percent", "capability"),
    "debuff_damage_spawn": ("-Damage vs a spawn", _support(_DEB, "aoe_vs_scenario", "DamageBuff"),
                            "percent", "capability"),
}


def measure(evaluation):
    """{category: value} straight from an evaluation (the calibration reads this too)."""
    return {key: spec[1](evaluation) for key, spec in CATEGORIES.items()}


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
    if (evaluation.get("versions") or {}).get("scenario_fingerprint") != \
            thresholds.get("scenario_fingerprint"):
        return _not_rated("the scenario constants changed since the thresholds were "
                          "calibrated; recalibrate", thresholds)
    offense_ok = (evaluation.get("confidence") or {}).get("offense_complete", False)
    values = measure(evaluation)
    out = {}
    for key, (label, _get, unit, kind) in CATEGORIES.items():
        value = values[key]
        cuts = (thresholds.get("categories") or {}).get(key, {}).get("cuts")
        row = {"label": label, "value": value, "unit": unit, "cuts": cuts}
        if kind == "pets" and not _has_pets(evaluation):
            row.update(grade="N/A", why="the build has no pets")
        elif kind == "offense" and not offense_ok:
            row.update(grade="Unknown", why="a picked power deals damage the model does not "
                                            "read (unsupported.powers, damaging: true)")
        elif value is None:
            row.update(grade="Unknown", why="not measured")
        elif kind == "capability" and value <= 0:
            row.update(grade="None", why="the build has none of this")
        elif not cuts:
            row.update(grade="Unknown", why="no threshold for this category yet")
        else:
            row["grade"] = grade(value, cuts)
        out[key] = row
    return {"status": "rated", "thresholds_version": thresholds.get("version"),
            "scenario": thresholds.get("scenario"), "provisional": True,
            "basis": thresholds.get("method"), "categories": out}
