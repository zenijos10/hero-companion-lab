"""VS ENEMY GROUP: how a build fares against each enemy group at +4 (owner,
2026-11-11: "a 'VS enemy group' where you can see specific matchups against
enemies based on their make up").

The groups come from data/critter_groups.json (tools/fetch_critter_data.py:
City of Data's copy of the game's critter records). For each group the rating
scenario's spawn (its enemy count, level shift and window) is refought with the
group's own make-up:
  * its damage arrives in the group's own Position|Type mix, against your
    defense (best of position and type) and capped resistance;
  * its accuracy is the spawn's rank mix (minion 1.0, lieutenant 1.15, boss 1.3);
  * its -Defense cascades from what the group really lands: share of attacks
    carrying -Defense, percent per hit and duration, against your DDR (the
    same fixed point as survival_profile.cascade);
  * your damage meets the group's own resistances, in your damage-type mix.
Reported per group: time to live (None = your sustain outlasts the spawn), the
damage per second that lands after mitigation, the steady -Defense with and
without your DDR, the share of your damage the group does not resist, and the
mez its attacks carry. Rating only: nothing here feeds the champion score.
"""
import json
import os

from first_principles import capped_resistance, defense_debuff_resistance, eroded_defense, incoming_hit
from survival_profile import fixed_point

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


def _hit(totals, sc, tohit, pos, dtype, debuff):
    return incoming_hit(eroded_defense(totals, [pos, dtype], debuff), tohit, sc)


def matchup(totals, inputs, sc, group, damage_types):
    """One group's matchup against a build (see the module docstring)."""
    cells = _cells(group)
    if not cells:
        return None
    sc_g = dict(sc, rank_acc=group.get("rank_accuracy") or sc.get("rank_acc", 1.0))
    tohit = inputs["tohit_debuff"]
    mean_hit = lambda d: sum(w * _hit(totals, sc_g, tohit, p, t, d)  # noqa: E731
                             for (p, t), w in cells.items())
    dd = group.get("def_debuff") or {}
    k = (sc["enemies"] * (group.get("attacks_per_second_per_critter") or 0.0)
         * (dd.get("attack_share") or 0.0) * (dd.get("percent_per_hit") or 0.0) / 100.0
         * (dd.get("seconds") or 0.0))
    ddr = defense_debuff_resistance(totals)
    debuff = fixed_point(k, ddr, mean_hit)
    without = fixed_point(k, 0.0, mean_hit)
    # past the build's best defense there is nothing left to take: what it LOSES
    # is capped there (the uncapped pile-up still drives the hit chance above)
    most = max([eroded_defense(totals, [p, t], 0.0) for (p, t) in cells] or [0.0])
    taken = sum(w * _hit(totals, sc_g, tohit, p, t, debuff) * (1.0 - capped_resistance(totals, t))
                for (p, t), w in cells.items())
    landing = sc["enemies"] * (group.get("dps_per_critter") or 0.0) * taken
    sustain = inputs["regen_hps"] + inputs["self_heal_hps"] + inputs["absorb_hps"]
    net = landing - sustain
    res = group.get("resistances") or {}
    shares = [(t.get("type"), t.get("damage_share")) for t in damage_types or []
              if t.get("damage_share") and t.get("type") in _TYPES]
    named = sum(s for _t, s in shares)
    kept = (sum(s * (1.0 - min(res.get(t, 0.0), 90.0) / 100.0) for t, s in shares) / named
            if named else None)
    by_type = {}
    for (_p, t), w in cells.items():
        by_type[t] = by_type.get(t, 0.0) + w
    top = sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    return {
        "time_to_live": round(inputs["hp"] / net, 1) if net > 0 else None,
        "damage_landing_per_second": round(landing, 1),
        "sustain_per_second": round(sustain, 1),
        "steady_def_debuff": round(min(debuff, most), 4),
        "steady_def_debuff_without_ddr": round(min(without, most), 4),
        "hit_chance": round(mean_hit(debuff), 4),
        "your_damage_unresisted": None if kept is None else round(kept, 3),
        "their_damage": [{"type": t, "share": round(s, 3)} for t, s in top],
        "mez": group.get("mez") or [],
    }


_TYPES = ("Smashing", "Lethal", "Fire", "Cold", "Energy", "Negative", "Psionic", "Toxic")


def display_name(group_key):
    """'CircleOfThorns' -> 'Circle Of Thorns', 'Fifth_Column' -> 'Fifth Column'
    (the game's group key, spaced; not a display name the game ships)."""
    out = []
    for ch in group_key.replace("_", " "):
        if ch.isupper() and out and out[-1] not in (" ",) and not out[-1].isupper():
            out.append(" ")
        out.append(ch)
    return "".join(out).strip()


def all_matchups(totals, inputs, sc, damage_types, data=None):
    """Every group's matchup, hardest first (shortest time to live; groups the
    build outlasts last, by damage landing)."""
    data = data if data is not None else load()
    if not data:
        return None
    rows = []
    for key, group in sorted((data.get("groups") or {}).items()):
        m = matchup(totals, inputs, sc, group, damage_types)
        if m:
            rows.append(dict(m, group=key, name=display_name(key)))
    rows.sort(key=lambda r: (r["time_to_live"] is None, r["time_to_live"] or 0.0,
                             -r["damage_landing_per_second"]))
    return {"source": data.get("source"), "revision": data.get("revision"),
            "basis": "the rating spawn refought with each group's own damage mix, rank "
                     "accuracy, -Defense and resistances (server/matchups.py)",
            "groups": rows}
