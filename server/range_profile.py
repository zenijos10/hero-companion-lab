"""Where a build has to stand: the share of its output delivered in melee, at
midrange, and from full range (owner, 2026-11-11: "show where people will need
to operate as a ratio of melee to midrange to full range ... the range bit should
matter for all ratings").

A power's band comes from its own geometry in the game data:
  melee     a single-target power that reaches at most MELEE_MAX feet
  midrange  anything centred on you (a PBAoE or an aura: no range, a radius),
            a cone or targeted area that reaches at most MID_MAX feet, and any
            other power that reaches at most MID_MAX ("AoE melee attacks
            including cones", the owner's definition)
  range     everything that reaches farther
  None      a power that only affects you (Build Up, an armor toggle): it does
            not decide where you stand
The thresholds are stated constants (game ranges cluster at 7 and 9 feet for
melee and 40+ for ranged; nothing in the data sits between 20 and 40 except a
handful of cones).
"""
BANDS = ("melee", "midrange", "range")
MELEE_MAX = 15.0
MID_MAX = 30.0


def band(rec):
    """melee / midrange / range for one power record, or None for self-only."""
    reach = rec.get("range") or 0.0
    radius = rec.get("radius") or 0.0
    if reach <= 0:
        return "midrange" if radius > 0 else None
    area = radius > 0 or (rec.get("effect_area") or 1) not in (0, 1)
    if reach <= MELEE_MAX and not area:
        return "melee"
    return "midrange" if reach <= MID_MAX else "range"


def profile(weights):
    """{band: share} from [(record, weight)], or None when nothing positional
    carries any weight (a share of nothing is not a claim)."""
    totals = dict.fromkeys(BANDS, 0.0)
    for rec, weight in weights:
        b = band(rec) if rec else None
        if b and weight and weight > 0:
            totals[b] += weight
    whole = sum(totals.values())
    if whole <= 0:
        return None
    return {b: round(v / whole, 3) for b, v in totals.items()}


def blend(profiles):
    """The even mean of the profiles that exist: where the build operates
    overall, when it deals damage, controls and supports."""
    present = [p for p in profiles if p]
    if not present:
        return None
    return {b: round(sum(p[b] for p in present) / len(present), 3) for b in BANDS}


def describe(prof):
    """'60% melee, 30% midrange, 10% range' (bands with a share only)."""
    if not prof:
        return None
    parts = [f"{round(prof[b] * 100)}% {b}" for b in BANDS if round((prof.get(b) or 0) * 100)]
    return ", ".join(parts) or None
