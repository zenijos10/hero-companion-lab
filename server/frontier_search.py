"""M6: search for a discovered Pareto frontier of legal slottings.

The player's PICKS are locked; the search re-slots them. Candidates come from
the existing solver (the real /build/solve) run along a fixed, disclosed list
of DIRECTIONS: the role presets and a few target emphases (defense soft cap,
resistance cap, high recharge...). A direction only proposes a candidate; it
never decides who wins. Every candidate is checked for legality, evaluated in
the rating scenario, held to the player's floors, and offered to a
pareto.Frontier that stays current on every insert.

The frontier is the DISCOVERED frontier: the directions do not cover every
legal slotting, so it is never called the global optimum. With an evaluation
budget the run is deterministic (same inputs, same directions, same order,
same frontier); a time budget is a stop reason and may cut a run short at a
machine-dependent point, which the result states.

Dependencies are injected (solve, validate, evaluate) so the rules are tested
without the game data; server.py wires the real ones.
"""
import copy
import hashlib
import json
import time

import build_ratings
import pareto

DEFAULT_OBJECTIVES = ("single_target_damage", "aoe_damage", "survival", "defense",
                      "resistance", "endurance", "recharge")
DEFAULT_MAX_EVALUATIONS = 12
MAX_EVALUATIONS = 40

_ALL_DAMAGE = ("single_target_damage", "aoe_damage", "pet_damage")
_SUPPORT = ("buff_defense", "buff_damage", "buff_recharge")
_DEBUFF = ("debuff_resistance_av", "debuff_regeneration_av", "debuff_defense_spawn",
           "debuff_tohit_spawn", "debuff_damage_spawn")
_RES_TYPES = ("Smashing", "Lethal", "Fire", "Cold", "Energy", "Negative", "Toxic", "Psionic")


def _direction(key, label, request, serves):
    return {"id": key, "label": label, "request": request, "serves": tuple(serves)}


# Order matters: it is the exploration order (after the ones serving the chosen
# objectives move to the front). Solve requests use the solver's own presets
# and custom-target vocabulary; nothing here is a scoring weight.
DIRECTIONS = (
    _direction("balanced", "Balanced (general content, split role)",
               {"content": "general", "role": "mixed"}, build_ratings.CATEGORIES),
    _direction("damage", "Damage dealer preset",
               {"content": "general", "role": "damage"}, _ALL_DAMAGE + ("recharge",)),
    _direction("hard_targets", "Hard targets (EB/AV) damage preset",
               {"content": "av", "role": "damage"}, ("single_target_damage", "survival")),
    _direction("tank", "Tank / survivor preset",
               {"content": "general", "role": "tank"}, ("survival", "resistance", "defense")),
    _direction("defense_softcap", "Target: 45% melee/ranged/AoE defense",
               {"content": "general", "role": "mixed",
                "custom_targets": {"defense": {"Melee": 45, "Ranged": 45, "AoE": 45},
                                   "recharge": 70, "recovery": 40}},
               ("defense", "survival")),
    _direction("resistance_cap", "Target: resistance to the archetype's cap",
               {"content": "general", "role": "mixed",
                "custom_targets": {"resistance": {t: 90 for t in _RES_TYPES},
                                   "recharge": 70, "recovery": 40}},
               ("resistance", "survival")),
    _direction("recharge_high", "Target: +150% recharge",
               {"content": "general", "role": "mixed",
                "custom_targets": {"recharge": 150, "recovery": 60}},
               ("recharge", "control") + _ALL_DAMAGE + _SUPPORT + _DEBUFF),
    _direction("endurance", "Target: +120% recovery",
               {"content": "general", "role": "mixed",
                "custom_targets": {"recovery": 120, "recharge": 70}},
               ("endurance",)),
    _direction("regeneration", "Target: +300% regeneration, +40% max HP",
               {"content": "general", "role": "mixed",
                "custom_targets": {"regen": 300, "max_hp": 40, "recharge": 70}},
               ("survival",)),
    _direction("buffer", "Buffer / support preset",
               {"content": "team", "role": "buffer"}, _SUPPORT + ("recharge",)),
    _direction("healer", "Healer preset",
               {"content": "team", "role": "healer"}, ("healing",)),
    _direction("controller", "Controller preset",
               {"content": "general", "role": "controller"}, ("control",) + _DEBUFF),
    _direction("debuffer", "Debuffer preset",
               {"content": "general", "role": "debuffer"}, _DEBUFF),
)


def plan_directions(objective_keys):
    """Directions serving a chosen objective first (catalogue order kept), then
    the rest: the run explores every direction it has budget for."""
    chosen = set(objective_keys)
    first = [d for d in DIRECTIONS if chosen & set(d["serves"])]
    return first + [d for d in DIRECTIONS if d not in first]


# a slot names its piece as piece_uid (solver/app) or uid (hand-built); both count
_SLOT_KEYS = ("piece_uid", "uid", "set_uid", "io_level", "level", "boost", "attuned")


def fingerprint(powers):
    """Stable id of a slotting: each picked power, its pick level and its pieces."""
    shape = sorted(
        (p.get("full_name") or "", p.get("pick_level"),
         [None if not isinstance(s, dict) else {k: s.get(k) for k in _SLOT_KEYS if k in s}
          for s in (p.get("slots") or [])])
        for p in powers if isinstance(p, dict))
    blob = json.dumps(shape, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def parse_request(body):
    """(objectives, floors, max_evaluations, max_seconds, max_size) or ValueError."""
    keys = body.get("objectives") or list(DEFAULT_OBJECTIVES)
    directions = body.get("directions") or {}
    if not isinstance(keys, list) or not isinstance(directions, dict):
        raise ValueError("objectives must be a list of category keys; directions a map")
    objectives = []
    for key in keys:
        if key not in build_ratings.CATEGORIES:
            raise ValueError(f"unknown objective {key!r}; choose from "
                             f"{', '.join(build_ratings.CATEGORIES)}")
        objectives.append(pareto.Objective(key, directions.get(key, pareto.MAXIMIZE)))
    floors = body.get("floors") or {}
    if not isinstance(floors, dict):
        raise ValueError("floors must map a category to {min} and/or {max}")
    for key, bound in floors.items():
        if key not in build_ratings.CATEGORIES or not isinstance(bound, dict) or not bound \
                or set(bound) - {"min", "max"} \
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           for v in bound.values()):
            raise ValueError(f"floor {key!r} must be a known category with numeric min/max")
    budget = body.get("max_evaluations", DEFAULT_MAX_EVALUATIONS)
    seconds = body.get("max_seconds")
    size = body.get("max_frontier_size")
    for name, v in (("max_evaluations", budget), ("max_seconds", seconds),
                    ("max_frontier_size", size)):
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 1):
            raise ValueError(f"{name} must be a positive number")
    return objectives, floors, min(int(budget), MAX_EVALUATIONS), seconds, \
        (int(size) if size else None)


def floor_violations(values, floors):
    out = []
    for key, bound in sorted(floors.items()):
        v = values.get(key)
        if not isinstance(v, (int, float)):
            out.append(f"{key}: not measured")
        elif "min" in bound and v < bound["min"]:
            out.append(f"{key}: {v:.4g} below the floor {bound['min']}")
        elif "max" in bound and v > bound["max"]:
            out.append(f"{key}: {v:.4g} above the limit {bound['max']}")
    return out


def search(start, *, objectives, floors, solve, validate, evaluate,
           max_evaluations=DEFAULT_MAX_EVALUATIONS, max_seconds=None, max_size=None,
           keep_sets=False, clock=time.monotonic):
    """Run the directions in order until they or the budget run out.

    solve(build, request) -> powers list (raises ValueError when it cannot)
    validate(build) -> list of legality errors
    evaluate(build) -> (evaluation, None) | (None, reason)
    """
    frontier = pareto.Frontier(objectives, max_size=max_size)
    keys = [o.key for o in objectives]
    began = clock()
    log, seen = [], {}
    evaluated = 0
    stop = "exhausted"
    start_values = None

    def offer(label, direction, build):
        nonlocal evaluated, start_values
        fp = fingerprint(build["powers"])
        if fp in seen:
            log.append({"candidate": label, "direction": direction, "fingerprint": fp,
                        "outcome": "same slotting as " + seen[fp]})
            return
        seen[fp] = label
        entry = {"candidate": label, "direction": direction, "fingerprint": fp}
        log.append(entry)
        errors = validate(build)
        if errors:
            entry.update(outcome="illegal", errors=list(errors)[:5])
            return
        evaluation, reason = evaluate(build)
        evaluated += 1
        if evaluation is None:
            entry.update(outcome="not evaluated", reason=reason)
            return
        values = build_ratings.measure(evaluation)
        if direction is None:
            start_values = values
        entry["values"] = {k: values.get(k) for k in keys}
        broken = floor_violations(values, floors)
        if broken:
            entry.update(outcome="below a floor", floors=broken)
            return
        outcome, detail = frontier.insert(
            fp, {k: values.get(k) for k in keys},
            {"label": label, "direction": direction, "build": build,
             "evaluation": evaluation, "values": values})
        entry["outcome"] = outcome
        if outcome == "dominated":
            entry["dominated_by"] = seen_label(detail)
        elif outcome == "admitted" and detail:
            entry["removed"] = [seen_label(fp) for fp in detail]
        elif outcome == "incomparable":
            entry["missing"] = detail

    def seen_label(fp):
        return seen.get(fp, fp)

    def out_of_budget():
        nonlocal stop
        if evaluated >= max_evaluations:
            stop = "evaluation_budget"
        elif max_seconds is not None and clock() - began >= max_seconds:
            stop = "time_budget"
        else:
            return False
        return True

    offer("Your build (as it is)", None, copy.deepcopy(start))
    planned = plan_directions(keys)
    tried = []
    for d in planned:
        if out_of_budget():
            break
        request = dict(d["request"], preserve=bool(keep_sets))
        tried.append(d["id"])
        try:
            powers = solve(copy.deepcopy(start), request)
        except ValueError as exc:
            log.append({"candidate": d["label"], "direction": d["id"],
                        "outcome": "solver refused", "reason": str(exc)})
            continue
        candidate = copy.deepcopy(start)
        candidate["powers"] = powers
        offer(d["label"], d["id"], candidate)
    return _result(frontier, keys, log, start_values, stop, evaluated, tried, planned,
                   clock() - began, keep_sets, floors)


def _result(frontier, keys, log, start_values, stop, evaluated, tried, planned, seconds,
            keep_sets, floors):
    members = []
    for fp, values, payload in frontier.members():
        ratings = (payload["evaluation"].get("ratings") or {}).get("categories") or {}
        members.append({
            "fingerprint": fp, "label": payload["label"], "direction": payload["direction"],
            "is_starting_build": payload["direction"] is None,
            "objectives": {k: values[k] for k in keys},
            "grades": {k: (ratings.get(k) or {}).get("grade") for k in build_ratings.CATEGORIES},
            "measurements": payload["values"],
            "change_from_start": None if start_values is None else {
                k: (None if payload["values"].get(k) is None or start_values.get(k) is None
                    else round(payload["values"][k] - start_values[k], 6))
                for k in build_ratings.CATEGORIES},
            "holds_out_on": frontier.strengths(fp),
            "offense_complete": (payload["evaluation"].get("confidence") or {})
            .get("offense_complete"),
            "build": payload["build"],
        })
    return {
        "ok": True, "kind": "discovered_frontier",
        "claim": "the nondominated builds among those this run evaluated; NOT proven to be "
                 "the global Pareto frontier",
        "frontier": frontier.describe(), "members": members,
        "starting_build": {"values": start_values,
                           "on_frontier": any(m["is_starting_build"] for m in members)},
        "search": {"stop_reason": stop, "evaluations": evaluated,
                   "max_evaluations_note": "the starting build counts as one evaluation",
                   "directions_tried": tried,
                   "directions_not_tried": [d["id"] for d in planned if d["id"] not in tried],
                   "seconds": round(seconds, 2),
                   "deterministic": stop != "time_budget",
                   "locked": ["picked powers"] + (["placed set pieces"] if keep_sets else []),
                   "floors": floors, "log": log},
    }
