"""Rating measurements that break a build's output down the way players read it
(owner, 2026-11-11): damage by type and by how often it fires; control split
single target vs area; every buff and debuff type on its own, weighted by how
rare the game makes it; where the build has to stand (range_profile); and the
debuff resistance that keeps a defense build standing.

Display and rating only: nothing here feeds the champion score. Every number
is read from what /build/evaluate already computed (the engine's attack chain,
the score's control per power, the M3 support ledger) or from the game data.
"""
import math

import range_profile
import role_output

# Records that are not a player's own pick: what the rarity census leaves out.
_NOT_PLAYER = ("Boosts", "Pets", "Villain_Pets", "Mastermind_Pets", "Kheldian_Pets",
               "Incarnate_Pets", "Incarnate", "Temporary_Powers", "Redirects", "Set_Bonus")


# ── damage ───────────────────────────────────────────────────────────────────

def _type_split(rec, attack):
    """{damage type: share of the attack's damage}, from the record's PvE rows
    (scale x magnitude x chance), else an even split of the engine's types."""
    weights = {}
    for row in (rec or {}).get("damage_effects") or []:
        if row.get("pv_mode") == 2:
            continue
        chance = row.get("probability")
        chance = 1.0 if chance is None else chance        # unset reads 1.0, like the engine
        w = abs(row.get("scale") or 0.0) * (row.get("nmag") or 1.0) * chance
        if w > 0 and row.get("damage_type"):
            weights[row["damage_type"]] = weights.get(row["damage_type"], 0.0) + w
    if not weights:
        types = attack.get("damage_types") or []
        weights = {t: 1.0 for t in types}
    whole = sum(weights.values())
    return {t: w / whole for t, w in weights.items()} if whole else {}


def _uses(attack):
    """How often an attack fires: its casts in the engine's attack chain; an area
    attack outside the single-target chain fires on cooldown (casts per 120 s)."""
    casts = attack.get("chain_casts") or 0
    if casts or not attack.get("is_aoe"):
        return float(casts)            # a single-target attack the chain skips never fires
    cycle = (attack.get("cast_time") or 0.0) + (attack.get("recharge") or 0.0)
    return 120.0 / cycle if cycle > 0 else 0.0


def _ranked(attacks):
    """Damage types ranked by share of damage dealt, with share of attacks fired."""
    by_type, casts_by_type = {}, {}
    for rec, attack, uses in attacks:
        dealt = uses * (attack.get("damage") or 0.0)
        for t, share in _type_split(rec, attack).items():
            by_type[t] = by_type.get(t, 0.0) + dealt * share
            casts_by_type[t] = casts_by_type.get(t, 0.0) + uses * share
    dealt_all, casts_all = sum(by_type.values()), sum(casts_by_type.values())
    return [{"type": t,
             "damage_share": round(by_type[t] / dealt_all, 3) if dealt_all else None,
             "attack_share": round(casts_by_type[t] / casts_all, 3) if casts_all else None}
            for t in sorted(by_type, key=lambda t: (-by_type[t], t))]


def damage(offense, records):
    """Damage types ranked by share of damage dealt and of attacks fired (all
    attacks, single-target ones, area ones), plus where each is delivered."""
    st, aoe = [], []
    for a in offense.get("attacks") or []:
        (aoe if a.get("is_aoe") else st).append((records.get(a.get("full_name")), a, _uses(a)))
    weights = lambda rows: [(rec, uses * (a.get("damage") or 0.0)) for rec, a, uses in rows]  # noqa: E731
    return {"types": _ranked(st + aoe),
            "types_single_target": _ranked(st),
            "types_aoe": _ranked(aoe),
            "basis": "attack chain uses (area attacks outside the chain: casts per 120 s on "
                     "cooldown) x damage per hit, split by each attack's own damage rows",
            "profiles": {"single_target_damage": range_profile.profile(weights(st)),
                         "aoe_damage": range_profile.profile(weights(aoe)),
                         "damage": range_profile.profile(weights(st + aoe))}}


def describe_types(types, limit=3):
    """'mostly Fire (72%), then Cold (18%), Smashing (10%)'."""
    rows = [t for t in types or [] if t.get("damage_share")]
    if not rows:
        return None
    head, rest = rows[0], rows[1:limit]
    text = f"mostly {head['type']} ({round(head['damage_share'] * 100)}%)"
    if rest:
        text += ", then " + ", ".join(f"{t['type']} ({round(t['damage_share'] * 100)}%)"
                                      for t in rest)
    return text


# ── control ──────────────────────────────────────────────────────────────────

def control(powers, ctx):
    """The score's control proxy per power, split single target vs area (the
    proxy's own rule: a power with a radius locks a group)."""
    records = ctx.get("power_by_full") or {}
    rows, st, aoe = [], [], []
    for p in powers:
        rec = records.get(p.get("full_name"))
        if not rec:
            continue
        score = role_output.power_control_output(rec, ctx)
        if score <= 0:
            continue
        area = "aoe" if (rec.get("radius") or 0) > 0 else "single_target"
        rows.append({"power": rec["full_name"], "display_name": rec.get("display_name"),
                     "area": area, "band": range_profile.band(rec),
                     "proxy_score": round(score, 2)})
        (aoe if area == "aoe" else st).append((rec, score))
    return {"single_target": round(sum(s for _r, s in st), 1),
            "aoe": round(sum(s for _r, s in aoe), 1),
            "by_power": sorted(rows, key=lambda r: -r["proxy_score"]),
            "profiles": {"control_single_target": range_profile.profile(st),
                         "control_aoe": range_profile.profile(aoe),
                         "control": range_profile.profile(st + aoe)}}


# ── buffs and debuffs, every type ────────────────────────────────────────────

ABSOLUTE_TYPES = ("HitPoints",)      # stated in hit points, not percent


def support_types(team_support, records):
    """Per effect type: the team buff (time-averaged, sustained and burst alike),
    the debuff landing on an AV from EVERY power (an area debuff lands on the AV
    too), the debuff landing across a spawn from area powers, and instant drains
    as a rate. Each with where it is delivered."""
    buffs, av, spawn, drain = {}, {}, {}, {}
    weights = {}
    for entry in team_support.get("powers") or []:
        if entry.get("conditional"):
            continue
        rec = records.get(entry.get("power"))
        for b in entry.get("buffs") or []:
            if b.get("instant") or b.get("average_percent") is None:
                continue
            buffs[b["effect"]] = buffs.get(b["effect"], 0.0) + b["average_percent"]
            weights.setdefault("buff:" + b["effect"], []).append((rec, b["average_percent"]))
        for d in entry.get("debuffs") or []:
            land = d.get("landing_peak_percent") or {}
            key = "debuff:" + d["effect"]
            if d.get("instant"):
                rate = d.get("landing_per_second_vs_scenario")
                if rate:
                    drain[d["effect"]] = drain.get(d["effect"], 0.0) + rate
                    weights.setdefault(key, []).append((rec, rate))
                continue
            up = d.get("uptime") or 0.0
            av[d["effect"]] = av.get(d["effect"], 0.0) + (land.get("vs_av") or 0.0) * up
            if entry.get("area") == "aoe":
                spawn[d["effect"]] = spawn.get(d["effect"], 0.0) + (land.get("vs_scenario") or 0.0) * up
            weights.setdefault(key, []).append((rec, (land.get("vs_scenario") or 0.0) * up))
        for h in entry.get("heals") or []:
            if h.get("side") == "ally" and h.get("per_second"):
                weights.setdefault("healing", []).append((rec, h["per_second"]))
    # HitPoints rows sit on a heal table: the "percent" the shared helper returns
    # is absolute hit points x 100, so they are stated in hit points instead
    unit = lambda k: 0.01 if k in ABSOLUTE_TYPES else 1.0  # noqa: E731
    r = lambda d: {k: round(v * unit(k), 2) for k, v in sorted(d.items())}  # noqa: E731
    profiles = {k: range_profile.profile(v) for k, v in sorted(weights.items())}
    support_all = [w for k, v in weights.items() if k != "healing" for w in v]
    profiles["support"] = range_profile.profile(support_all)
    return {"buffs_average_percent": r(buffs), "debuffs_vs_av_percent": r(av),
            "debuffs_vs_spawn_percent": r(spawn), "drains_per_second_percent": r(drain),
            "profiles": profiles,
            "absolute_types": {t: "hit_points" for t in ABSOLUTE_TYPES},
            "basis": "buffs: peak x uptime, sustained and burst alike; debuffs: landing "
                     "strength (purple patch, AV debuff resistance) x uptime, vs an AV from "
                     "every power and vs the spawn from area powers; instant drains: "
                     "landing per cast / cycle"}


def _player_records(records):
    return [r for r in records.values()
            if r.get("full_name", "").split(".")[0] not in _NOT_PLAYER
            and (r.get("level_available") or 0) >= 1]


def rarity(records):
    """How rare the game makes each buff and debuff type: the number of player
    powersets offering it, and a weight log2(1 + most common / this), so the
    commonest type weighs 1 and a type 40 times rarer about 5.3."""
    sets = _census(records)
    out = {}
    for side, by in sets.items():
        top = max((len(v) for v in by.values()), default=0)
        out[side] = {e: {"powersets": len(v),
                         "weight": round(math.log2(1.0 + top / len(v)), 3)}
                     for e, v in sorted(by.items()) if e and v}
    return out


_CENSUS = {}


def _census(records):
    """The census once per power table (keyed by identity and size)."""
    key = (id(records), len(records))
    if key not in _CENSUS:
        _CENSUS.clear()
        sets = {"buff": {}, "debuff": {}}
        for rec in _player_records(records):
            ps = rec.get("powerset_full_name")
            for e in rec.get("buff_effects") or []:
                if e.get("pv_mode") == 2 or e.get("target") == "Self" or e.get("effect") == "Heal":
                    continue
                sets["buff"].setdefault(e.get("effect"), set()).add(ps)
            for e in rec.get("debuff_effects") or []:
                if e.get("pv_mode") == 2:
                    continue
                sets["debuff"].setdefault(e.get("effect"), set()).add(ps)
        _CENSUS[key] = sets
    return _CENSUS[key]


# ── debuff resistance ────────────────────────────────────────────────────────

# Debuff-resistance families the game has but our power data does not carry as
# effects (owner's mez_in / resistance-family rulings): stated, never read as zero.
NOT_READ = ("ToHit debuff resistance", "Endurance drain resistance",
            "Regeneration debuff resistance", "Recovery debuff resistance")


def debuff_resistance(totals):
    extras = totals.get("bonus_extras") or {}
    val = lambda k: (extras.get(k) or {}).get("value") or 0.0  # noqa: E731
    return {"defense_debuff": round(val("def_debuff_resist"), 2),
            "slow_and_recharge_debuff": round(val("slow_resist"), 2),
            "unit": "percent",
            "not_read": list(NOT_READ)}
