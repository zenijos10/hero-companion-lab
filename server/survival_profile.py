"""Toughness: how much incoming damage a build can take, per damage type and
position, and the same number as a multiple of a bare character of its archetype.

Idea from the community Survivability Tool (Homecoming forums topic 12212,
v3.0 spreadsheet): its "Max DPS for survival duration" and its score against an
unbuffed character of the same archetype. The arithmetic is OURS: the same
helpers and inputs the encounter's time-to-live uses (first_principles
incoming_hit / eroded_defense / capped_resistance / incoming_def_debuff, the
-ToHit the build lands, regeneration + self heals + absorb). What differs is the
incoming damage: the untyped encounter prices every hit as Smashing (defense =
best of melee/smashing/lethal or ranged/AoE/energy), while each cell here reads
its own type, so a build with one strong type and a hole elsewhere can show a
long time to live and a low toughness. That gap is the point of the grid.

  cell(position, type) = incoming damage per second, as the enemies deal it,
                         that the build outlasts for `window` seconds
                       = (hp / window + sustain) / (hit chance x (1 - resistance))
  toughness            = the same for an EVEN mix of all 24 cells (exact for
                         that mix: the harmonic mean of the cells, so a hole in
                         one type pulls it down)
  vs_archetype         = toughness / the bare archetype's (its base hit points
                         and regeneration, no defense, resistance or heals)

The bare archetype's damage taken is the same in every cell, so the multiple
answers "how much tougher than a bare <archetype>" without peer cohorts.
"""
from first_principles import (_REGEN_PER_SEC, capped_resistance, eroded_defense,
                              incoming_hit)

TYPES = ("Smashing", "Lethal", "Fire", "Cold", "Energy", "Negative", "Psionic", "Toxic")
POSITIONS = ("Melee", "Ranged", "AoE")


def _taken(totals, inputs, sc, position, dtype):
    """Share of the enemies' raw damage that lands: hit chance x unresisted part."""
    defense = eroded_defense(totals, [position, dtype], inputs["def_debuff_in"])
    hit = incoming_hit(defense, inputs["tohit_debuff"], sc)
    return hit * (1.0 - capped_resistance(totals, dtype))


def _capacity(hp, sustain, taken, window):
    return (hp / window + sustain) / taken


def profile(totals, inputs, sc, base_hp, window):
    """The toughness grid, its even-mix summary and the bare-archetype multiple."""
    sustain = inputs["regen_hps"] + inputs["self_heal_hps"] + inputs["absorb_hps"]
    hp = inputs["hp"]
    grid, takens = {}, []
    for position in POSITIONS:
        grid[position] = {}
        for dtype in TYPES:
            taken = _taken(totals, inputs, sc, position, dtype)
            takens.append((taken, position, dtype))
            grid[position][dtype] = round(_capacity(hp, sustain, taken, window), 1)
    mean_taken = sum(t for t, _p, _d in takens) / len(takens)
    toughness = _capacity(hp, sustain, mean_taken, window)
    worst = round(_capacity(hp, sustain, max(t for t, _p, _d in takens), window), 1)
    # every cell at the worst value (ties are common: no defense means all three
    # positions tie, and unresisted types tie with each other)
    weakest = [[p, d] for p in POSITIONS for d in TYPES if grid[p][d] == worst]
    bare = _capacity(base_hp, base_hp * _REGEN_PER_SEC, incoming_hit(0.0, 0.0, sc), window)
    return {
        "window_seconds": window,
        "toughness": round(toughness, 1),
        "break_even": round(sustain / mean_taken, 1),
        "weakest": {"value": worst, "cells": weakest},
        "bare_archetype": round(bare, 1),
        "vs_archetype": round(toughness / bare, 2),
        "grid": grid,
    }
