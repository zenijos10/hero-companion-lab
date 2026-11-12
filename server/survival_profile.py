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
  toughness            = the same for the incoming mix where the build operates
                         (range_profile): up close every position hits you
                         (melee, ranged, AoE a third each); at full range only
                         ranged and AoE attacks reach (half each). Each position
                         carries the 8 types evenly, so a hole pulls it down.
  vs_archetype         = toughness / the bare archetype's (its base hit points
                         and regeneration, no defense, resistance or heals)

THE DEFENSE CASCADE (owner, 2026-11-11: "What I have monster DR how did he hit
me?"). Enemies always keep a 5% floor to hit, and many of their attacks carry
-Defense. Every landed debuffing hit lowers defense, which raises the next hit
chance, which lands more debuffs. The steady state is the fixed point
    D = K x (1 - DDR) x mean hit chance(defense - D),
    K = enemies x attacks per enemy per second x share of attacks with -Defense
        x -Defense per landed hit x its duration,
reached by iterating from D = 0 (the debuff piles up from nothing, so the
sequence climbs to the first stable point). Defense debuff resistance (DDR)
scales every landed debuff. The K constants are stated assumptions in the rating
scenario (build_evaluation.RATING_SCENARIOS); a scenario without them falls back
to the encounter's flat incoming -Defense. Rating only: the champion score keeps
the flat model (a model change is the owner's call).
"""
from first_principles import (_REGEN_PER_SEC, capped_resistance, defense_debuff_resistance,
                              eroded_defense, incoming_hit)

TYPES = ("Smashing", "Lethal", "Fire", "Cold", "Energy", "Negative", "Psionic", "Toxic")
POSITIONS = ("Melee", "Ranged", "AoE")
CASCADE_KEYS = ("enemy_attacks_per_second", "def_debuff_attack_share",
                "def_debuff_per_hit", "def_debuff_seconds")


def position_weights(operating):
    """Incoming weight per position for a {melee, midrange, range} profile."""
    close = 1.0 if not operating else (operating.get("melee", 0.0) + operating.get("midrange", 0.0))
    far = 0.0 if not operating else operating.get("range", 0.0)
    whole = close + far
    close, far = (close / whole, far / whole) if whole > 0 else (1.0, 0.0)
    return {"Melee": close / 3.0, "Ranged": close / 3.0 + far / 2.0,
            "AoE": close / 3.0 + far / 2.0}


def _hit(totals, sc, tohit, position, dtype, debuff):
    return incoming_hit(eroded_defense(totals, [position, dtype], debuff), tohit, sc)


def _mean_hit(totals, sc, tohit, weights, debuff):
    return sum(w * _hit(totals, sc, tohit, p, t, debuff) / len(TYPES)
               for p, w in weights.items() for t in TYPES)


def _steady_debuff(totals, sc, tohit, weights, ddr):
    """The cascade's fixed point (see the module docstring)."""
    k = sc["enemies"]
    for key in CASCADE_KEYS:
        k *= sc[key]
    debuff = 0.0
    for _ in range(500):
        nxt = k * (1.0 - ddr) * _mean_hit(totals, sc, tohit, weights, debuff)
        if abs(nxt - debuff) < 1e-7:
            return nxt
        debuff = nxt
    return debuff


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
    landing = (sc["enemies"] * sc["enemy_attacks_per_second"] * sc["def_debuff_attack_share"]
               * after * 60.0)
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


def profile(totals, inputs, sc, base_hp, window, operating=None):
    """The toughness grid, its summary for where the build operates, toughness
    up close and at range, the defense cascade and the bare-archetype multiple."""
    sustain = inputs["regen_hps"] + inputs["self_heal_hps"] + inputs["absorb_hps"]
    hp, tohit = inputs["hp"], inputs["tohit_debuff"]
    weights = position_weights(operating)
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
        "up_close": round(_capacity(hp, sustain, _mixed(takens, position_weights(None)), window), 1),
        "at_range": round(_capacity(hp, sustain, _mixed(takens, position_weights({"range": 1.0})),
                                    window), 1),
        "position_weights": {p: round(w, 3) for p, w in weights.items()},
        "break_even": round(sustain / mixed, 1),
        "weakest": {"value": worst, "cells": weakest},
        "bare_archetype": round(bare, 1),
        "vs_archetype": round(toughness / bare, 2),
        "defense_cascade": casc,
        "grid": grid,
    }
