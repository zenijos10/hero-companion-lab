"""Toughness: how much incoming damage a build can take, per damage type and
position, and the same number as a multiple of a bare character of its archetype.

Idea from the community Survivability Tool (Homecoming forums topic 12212,
v3.0 spreadsheet): its "Max DPS for survival duration" and its score against an
unbuffed character of the same archetype. The arithmetic here is OURS, the same
the encounter's time-to-live uses (first_principles.incoming_hit, the best of
positional and typed defense, DDR-eroded incoming -Defense, the -ToHit the build
lands, AT-capped resistance, regeneration + self heals + absorb), so the grid
cannot disagree with the survival score.

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
from first_principles import _REGEN_PER_SEC, incoming_hit

TYPES = ("Smashing", "Lethal", "Fire", "Cold", "Energy", "Negative", "Psionic", "Toxic")
POSITIONS = ("Melee", "Ranged", "AoE")


def _value(totals, group, key):
    row = (totals.get(group) or {}).get(key) or {}
    return (row.get("value") or 0.0) / 100.0


def _taken(totals, inputs, sc, position, dtype):
    """Share of the enemies' raw damage that lands: hit chance x unresisted part."""
    defense = max(_value(totals, "defense", position), _value(totals, "defense", dtype))
    defense = max(defense - inputs["def_debuff_in"], 0.0)
    hit = incoming_hit(defense, inputs["tohit_debuff"], sc)
    return hit * (1.0 - min(_value(totals, "resistance", dtype), 0.90))


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
    worst_taken, worst_pos, worst_type = max(takens, key=lambda t: t[0])   # first of ties
    bare = _capacity(base_hp, base_hp * _REGEN_PER_SEC, incoming_hit(0.0, 0.0, sc), window)
    return {
        "window_seconds": window,
        "toughness": round(toughness, 1),
        "break_even": round(sustain / mean_taken, 1),
        "weakest": {"position": worst_pos, "type": worst_type,
                    "value": round(_capacity(hp, sustain, worst_taken, window), 1)},
        "bare_archetype": round(bare, 1),
        "vs_archetype": round(toughness / bare, 2),
        "grid": grid,
    }
