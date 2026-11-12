"""Toughness: how much incoming damage a build can take, per damage type and
position, and the same number as a multiple of a bare character of its archetype.

Idea from the community Survivability Tool (Homecoming forums topic 12212,
v3.0 spreadsheet): its "Max DPS for survival duration" and its score against an
unbuffed character of the same archetype. The arithmetic is OURS: the same
helpers and inputs the encounter's time-to-live uses (first_principles
incoming_hit / eroded_defense / capped_resistance / defense_debuff_resistance,
the -ToHit the build lands, regeneration + self heals + absorb). What differs is
the incoming damage: the untyped encounter prices every hit as Smashing, while
each cell here reads its own type, so a build with one strong type and a hole
elsewhere can show a long time to live and a low toughness.

  cell(position, type) = incoming damage per second, as the enemies deal it,
                         that the build outlasts for `window` seconds
                       = (hp / window + sustain) / (hit chance x (1 - resistance))
  toughness            = the same for the incoming mix: melee, ranged and AoE
                         attacks a third each, the 8 types evenly (a hole pulls
                         it down), with the melee third scaled by MELEE REACH.

MELEE REACH (owner, 2026-11-12): "Melee npcs will try to enter melee distance,
ranged ones will stay at range ... running out of melee range won't work as the
enemy will follow you, so you need a method to keep them at bay (controls or
soft controls) or kill them before they get to you." So ranged and AoE attacks
always land, and melee attacks land on everyone who fights up close; on a build
that fights from range they land except while the build keeps the spawn at bay
(an area root, knockback or repel, by its uptime) and while the spawn is still
closing the distance (ENGAGE_FEET at the critters' run speed, slowed by the
build's -Speed, as a share of the fight):
    reach = close + range x (1 - keep_at_bay) x (1 - approach / window)
  vs_archetype         = toughness / the bare archetype's (its base hit points
                         and regeneration, no defense, resistance or heals)

THE DEFENSE CASCADE (owner, 2026-11-11: "What I have monster DR how did he hit
me?"). Enemies always keep a 5% floor to hit, and many of their attacks carry
-Defense. Every landed debuffing hit lowers defense, which raises the next hit
chance, which lands more debuffs. The steady state is the fixed point
    D = K x (1 - DDR) x mean hit chance(defense - D),
    K = enemies x def_debuff_pressure (per critter: attacks/s x share carrying
        -Defense x fraction per landed hit x its duration),
reached by iterating from D = 0 (the debuff piles up from nothing, so the
sequence climbs to the first stable point). Defense debuff resistance (DDR)
scales every landed debuff. The pressure is the game data's mean over 106
enemy groups (data/critter_groups.json, copied into
build_evaluation.RATING_SCENARIOS); a scenario without it falls back to the
encounter's flat incoming -Defense. Rating only: the champion score keeps
the flat model (a model change is the owner's call).
"""
from first_principles import (_REGEN_PER_SEC, capped_resistance, defense_debuff_resistance,
                              eroded_defense, incoming_hit)

TYPES = ("Smashing", "Lethal", "Fire", "Cold", "Energy", "Negative", "Psionic", "Toxic")
POSITIONS = ("Melee", "Ranged", "AoE")
CASCADE_KEYS = ("def_debuff_pressure", "def_debuff_hit_rate")
# Melee reach constants (stated): a ranged fight opens about 60 ft out, and
# critters close at roughly the base run speed of 21 mph (30.8 ft/s); -Speed
# slows them, capped at 90% (a slowed critter still crawls).
ENGAGE_FEET = 60.0
CRITTER_RUN_FEET_PER_SECOND = 30.8
SLOW_CAP = 0.9


def melee_reach(operating, keep_at_bay=0.0, slow=0.0, window=30.0):
    """The share of melee attacks that land (see the module docstring)."""
    close = 1.0 if not operating else operating.get("melee", 0.0) + operating.get("midrange", 0.0)
    far = 0.0 if not operating else operating.get("range", 0.0)
    whole = close + far
    close, far = (close / whole, far / whole) if whole > 0 else (1.0, 0.0)
    speed = CRITTER_RUN_FEET_PER_SECOND * (1.0 - min(max(slow, 0.0), SLOW_CAP))
    approach = ENGAGE_FEET / speed
    closing = max(0.0, 1.0 - approach / window) if window > 0 else 1.0
    reach = close + far * (1.0 - min(max(keep_at_bay, 0.0), 1.0)) * closing
    return {"reach": round(reach, 4), "approach_seconds": round(approach, 2),
            "keep_at_bay": round(min(max(keep_at_bay, 0.0), 1.0), 3), "range_share": round(far, 3)}


def position_weights(reach=1.0):
    """Incoming weight per position: a third each, melee scaled by its reach
    (melee attacks the build keeps away never land, so the weights need not
    sum to one)."""
    return {"Melee": reach / 3.0, "Ranged": 1.0 / 3.0, "AoE": 1.0 / 3.0}


def sustain_per_second(inputs):
    """Regeneration + self heals + absorb: the one copy (toughness, matchups)."""
    return inputs["regen_hps"] + inputs["self_heal_hps"] + inputs["absorb_hps"]


def _hit(totals, sc, tohit, position, dtype, debuff):
    """Hit chance of one attack: defense = the best of its positions ("Ranged+AoE"
    tags carry both) and its type, after the cascade."""
    keys = position.split("+") + [dtype]
    return incoming_hit(eroded_defense(totals, keys, debuff), tohit, sc)


def _mean_hit(totals, sc, tohit, weights, debuff):
    return sum(w * _hit(totals, sc, tohit, p, t, debuff) / len(TYPES)
               for p, w in weights.items() for t in TYPES)


def fixed_point(k, ddr, mean_hit):
    """The cascade's steady -Defense: D = k x (1 - DDR) x mean_hit(D), climbed
    from D = 0 (the debuff piles up from nothing). One copy, shared with the
    enemy-group matchups (server/matchups.py)."""
    debuff = 0.0
    for _ in range(500):
        nxt = k * (1.0 - ddr) * mean_hit(debuff)
        if abs(nxt - debuff) < 1e-7:
            return nxt
        debuff = nxt
    return debuff


def _steady_debuff(totals, sc, tohit, weights, ddr):
    """The cascade's fixed point (see the module docstring)."""
    k = sc["enemies"] * sc["def_debuff_pressure"]
    return fixed_point(k, ddr, lambda d: _mean_hit(totals, sc, tohit, weights, d))


def cascade(totals, inputs, sc, weights):
    """Steady-state incoming -Defense, with the build's DDR and without it."""
    tohit = inputs["tohit_debuff"]
    if not all(k in sc for k in CASCADE_KEYS):
        flat = inputs["def_debuff_in"]
        return {"model": "flat", "steady_def_debuff": round(flat, 4), "debuff": flat}
    ddr = defense_debuff_resistance(totals)
    debuff = _steady_debuff(totals, sc, tohit, weights, ddr)
    without = _steady_debuff(totals, sc, tohit, weights, 0.0)
    before = _mean_hit(totals, sc, tohit, weights, 0.0)
    after = _mean_hit(totals, sc, tohit, weights, debuff)
    landing = sc["enemies"] * sc["def_debuff_hit_rate"] * after * 60.0
    return {"model": "cascade", "debuff": debuff,
            "defense_debuff_resistance": round(ddr, 3),
            "steady_def_debuff": round(debuff, 4),
            "steady_def_debuff_without_ddr": round(without, 4),
            "hit_chance_before": round(before, 4),
            "hit_chance_after": round(after, 4),
            "hit_chance_floor": round(incoming_hit(1.0, tohit, sc), 4),
            "landed_def_debuff_hits_per_minute": round(landing, 2),
            "constants": {k: sc[k] for k in CASCADE_KEYS}}


def _taken(totals, sc, tohit, position, dtype, debuff):
    """Share of the enemies' raw damage that lands: hit chance x unresisted part."""
    return _hit(totals, sc, tohit, position, dtype, debuff) * (1.0 - capped_resistance(totals, dtype))


def _capacity(hp, sustain, taken, window):
    return (hp / window + sustain) / taken


def _mixed(takens, weights):
    return sum(weights[p] * t / len(TYPES) for (p, _d), t in takens.items())


def profile(totals, inputs, sc, base_hp, window, operating=None, keep_at_bay=0.0, slow=0.0):
    """The toughness grid, its summary for where the build operates (melee
    reach), toughness up close and at range, the defense cascade and the
    bare-archetype multiple."""
    sustain = sustain_per_second(inputs)
    hp, tohit = inputs["hp"], inputs["tohit_debuff"]
    reach = melee_reach(operating, keep_at_bay, slow, window)
    far = melee_reach({"range": 1.0}, keep_at_bay, slow, window)
    weights = position_weights(reach["reach"])
    casc = cascade(totals, inputs, sc, weights)
    takens = {(p, d): _taken(totals, sc, tohit, p, d, casc["debuff"])
              for p in POSITIONS for d in TYPES}
    grid = {p: {d: round(_capacity(hp, sustain, takens[(p, d)], window), 1) for d in TYPES}
            for p in POSITIONS}
    mixed = _mixed(takens, weights)
    reached = [p for p in POSITIONS if weights[p] > 0]
    worst = min(grid[p][d] for p in reached for d in TYPES)
    # every cell at the worst value (ties are common: no defense means all three
    # positions tie, and unresisted types tie with each other)
    weakest = [[p, d] for p in reached for d in TYPES if grid[p][d] == worst]
    bare = _capacity(base_hp, base_hp * _REGEN_PER_SEC, incoming_hit(0.0, 0.0, sc), window)
    toughness = _capacity(hp, sustain, mixed, window)
    casc.pop("debuff")
    return {
        "window_seconds": window,
        "toughness": round(toughness, 1),
        "up_close": round(_capacity(hp, sustain, _mixed(takens, position_weights(1.0)), window), 1),
        "at_range": round(_capacity(hp, sustain, _mixed(takens, position_weights(far["reach"])),
                                    window), 1),
        "melee_reach": reach,
        "position_weights": {p: round(w, 3) for p, w in weights.items()},
        "break_even": round(sustain / mixed, 1),
        "weakest": {"value": worst, "cells": weakest},
        "bare_archetype": round(bare, 1),
        "vs_archetype": round(toughness / bare, 2),
        "defense_cascade": casc,
        "grid": grid,
    }
