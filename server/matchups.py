"""VS ENEMY GROUP: how a build fares against each enemy group at +4 (owner,
2026-11-11: "a 'VS enemy group' where you can see specific matchups against
enemies based on their make up").

The groups come from data/critter_groups.json (tools/fetch_critter_data.py:
City of Data's copy of the game's critter records). For each group the rating
scenario's spawn (its enemy count, level shift and window) is refought with the
group's own make-up:
  * its damage arrives in the group's own Position|Type mix, against your
    defense (best of the attack's positions and type) and capped resistance;
  * its melee attacks land as far as MELEE REACH lets them (survival_profile:
    melee critters close on a ranged build unless it keeps them at bay or they
    are still closing the distance); ranged and area attacks always land;
  * its accuracy is the spawn's rank mix (minion 1.0, lieutenant 1.15, boss 1.3);
  * its -Defense cascades from what the group really lands: share of attacks
    carrying -Defense, percent per hit and duration, against your DDR (the
    same fixed point as survival_profile.cascade);
  * your damage meets the group's own resistances, in your damage-type mix.
Reported per group: time to live (None = your sustain outlasts their damage)
and whether you outlast the fight (time to live at least the spawn's window), the
damage per second that lands after mitigation, the steady -Defense with and
without your DDR, the share of your damage the group does not resist, and the
mez its attacks carry. Rating only: nothing here feeds the champion score.
"""
import json
import os

from first_principles import capped_resistance, defense_debuff_resistance, eroded_defense
from survival_profile import TYPES, _hit, fixed_point, sustain_per_second

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "critter_groups.json")
_CACHE = {}


def load(path=DATA):
    """The compiled critter groups, or None when the file is absent."""
    if path not in _CACHE:
        try:
            with open(path, encoding="utf-8") as f:
                _CACHE[path] = json.load(f)
        except (OSError, ValueError):
            _CACHE[path] = None
    return _CACHE[path]


def _cells(group):
    out = {}
    for key, share in (group.get("damage_mix") or {}).items():
        pos, dtype = key.split("|", 1)
        out[(pos, dtype)] = share
    return out


def matchup(totals, inputs, sc, group, damage_types, reach=1.0):
    """One group's matchup against a build (see the module docstring); reach =
    the share of melee attacks that land (survival_profile.melee_reach)."""
    cells = {(p, t): w * (reach if "Melee" in p.split("+") else 1.0)
             for (p, t), w in _cells(group).items()}
    if not cells:
        return None
    sc_g = dict(sc, rank_acc=group.get("rank_accuracy") or sc.get("rank_acc", 1.0))
    tohit = inputs["tohit_debuff"]
    mean_hit = lambda d: sum(w * _hit(totals, sc_g, tohit, p, t, d)  # noqa: E731
                             for (p, t), w in cells.items())
    k = sc["enemies"] * (group.get("def_debuff_pressure") or 0.0)
    ddr = defense_debuff_resistance(totals)
    debuff = fixed_point(k, ddr, mean_hit)
    without = fixed_point(k, 0.0, mean_hit)
    # past the build's best defense there is nothing left to take: what it LOSES
    # is capped there (the uncapped pile-up still drives the hit chance above)
    most = max([eroded_defense(totals, p.split("+") + [t], 0.0) for (p, t) in cells] or [0.0])
    taken = sum(w * _hit(totals, sc_g, tohit, p, t, debuff) * (1.0 - capped_resistance(totals, t))
                for (p, t), w in cells.items())
    landing = sc["enemies"] * (group.get("dps_per_critter") or 0.0) * taken
    sustain = sustain_per_second(inputs)
    net = landing - sustain
    ttl = inputs["hp"] / net if net > 0 else None
    res = group.get("resistances") or {}
    shares = [(t.get("type"), t.get("damage_share")) for t in damage_types or []
              if t.get("damage_share") and t.get("type") in TYPES]
    named = sum(s for _t, s in shares)
    # a vulnerability (negative resistance) lifts your damage above 100%
    kept = (sum(s * (1.0 - min(res.get(t, 0.0), 90.0) / 100.0) for t, s in shares) / named
            if named else None)
    by_type = {}
    for (_p, t), w in cells.items():
        by_type[t] = by_type.get(t, 0.0) + w
    top = sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    return {
        "time_to_live": None if ttl is None else round(ttl, 1),
        "outlasts": ttl is None or ttl >= sc["length"],
        "melee_reach": round(reach, 3),
        "damage_landing_per_second": round(landing, 1),
        "sustain_per_second": round(sustain, 1),
        "steady_def_debuff": round(min(debuff, most), 4),
        "steady_def_debuff_without_ddr": round(min(without, most), 4),
        "hit_chance": round(mean_hit(debuff), 4),
        "your_damage_unresisted": None if kept is None else round(kept, 3),
        "their_damage": [{"type": t, "share": round(s, 3)} for t, s in top],
        "mez": group.get("mez") or [],
    }


def display_name(group_key):
    """'CircleOfThorns' -> 'Circle Of Thorns', 'Fifth_Column' -> 'Fifth Column'
    (the game's group key, spaced; not a display name the game ships)."""
    out = []
    for ch in group_key.replace("_", " "):
        if ch.isupper() and out and out[-1] not in (" ",) and not out[-1].isupper():
            out.append(" ")
        out.append(ch)
    return "".join(out).strip()


def all_matchups(totals, inputs, sc, damage_types, data=None, reach=1.0):
    """Every group's matchup, hardest first (shortest time to live; groups whose
    damage the build's sustain outpaces last, by damage landing)."""
    data = data if data is not None else load()
    if not data:
        return None
    rows = []
    for key, group in sorted((data.get("groups") or {}).items()):
        m = matchup(totals, inputs, sc, group, damage_types, reach)
        if m:
            rows.append(dict(m, group=key, name=display_name(key)))
    rows.sort(key=lambda r: (r["time_to_live"] is None, r["time_to_live"] or 0.0,
                             -r["damage_landing_per_second"]))
    return {"source": data.get("source"), "revision": data.get("revision"),
            "basis": "the rating spawn refought with each group's own damage mix, rank "
                     "accuracy, -Defense and resistances; melee attacks land as far as the "
                     "build's melee reach lets them (server/matchups.py)",
            "window_seconds": sc["length"],
            "groups": rows}
