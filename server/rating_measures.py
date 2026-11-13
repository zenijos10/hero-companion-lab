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

import engine
import range_profile
import role_output

# Records that are not a player's own pick: what the rarity census leaves out.
_NOT_PLAYER = ("Boosts", "Pets", "Villain_Pets", "Mastermind_Pets", "Kheldian_Pets",
               "Incarnate_Pets", "Incarnate", "Temporary_Powers", "Redirects", "Set_Bonus")


# ── damage ───────────────────────────────────────────────────────────────────

_UNTYPED = ("None", "Special")          # the engine keeps these out of damage_types
UNREAD = "Unread"                       # damage dealt whose type the data does not name


def _type_split(rec, attack, records=None):
    """{damage type: share of the attack's damage}, from the record's PvE rows
    (scale x magnitude x chance); a patch summoner (no rows of its own) reads its
    pseudo-pet's rows; else an even split of the engine's types."""
    weights = {}
    rows = (rec or {}).get("damage_effects") or []
    if rec and not rows and records:
        rows = (engine.resolve_patch_pet(rec, records) or {}).get("damage_effects") or []
    for row in rows:
        if row.get("pv_mode") == 2 or row.get("damage_type") in _UNTYPED:
            continue
        chance = row.get("probability")
        chance = 1.0 if chance is None else chance        # unset reads 1.0, like the engine
        w = abs(row.get("scale") or 0.0) * (row.get("nmag") or 1.0) * chance
        if w > 0 and row.get("damage_type"):
            weights[row["damage_type"]] = weights.get(row["damage_type"], 0.0) + w
    if not weights:
        types = [t for t in attack.get("damage_types") or [] if t not in _UNTYPED]
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


def _ranked(attacks, records):
    """Damage types ranked by share of damage dealt, with share of attacks fired."""
    by_type, casts_by_type = {}, {}
    for rec, attack, uses in attacks:
        dealt = uses * (attack.get("damage") or 0.0)
        # damage whose type our data cannot name (a patch's proc rolls) is kept
        # as UNREAD, so the named types' shares are never overstated
        for t, share in (_type_split(rec, attack, records) or {UNREAD: 1.0}).items():
            by_type[t] = by_type.get(t, 0.0) + dealt * share
            casts_by_type[t] = casts_by_type.get(t, 0.0) + uses * share
    dealt_all, casts_all = sum(by_type.values()), sum(casts_by_type.values())
    return [{"type": t,
             "damage_share": round(by_type[t] / dealt_all, 3) if dealt_all else None,
             "attack_share": round(casts_by_type[t] / casts_all, 3) if casts_all else None}
            for t in sorted(by_type, key=lambda t: (-by_type[t], t))]


def _placed(rec, records):
    """The record that says where a power's damage lands: the power itself, or a
    patch summoner's pseudo-pet (Irradiated Ground has no reach; its patch has
    the radius)."""
    if rec and range_profile.band(rec) is None and not rec.get("damage_effects"):
        pet = engine.resolve_patch_pet(rec, records)
        if pet:
            return pet
    return rec


def damage(offense, records):
    """Damage types ranked by share of damage dealt and of attacks fired (all
    attacks, single-target ones, area ones), plus where each is delivered."""
    st, aoe = [], []
    for a in offense.get("attacks") or []:
        (aoe if a.get("is_aoe") else st).append((records.get(a.get("full_name")), a, _uses(a)))
    weights = lambda rows: [(_placed(rec, records), uses * (a.get("damage") or 0.0))  # noqa: E731
                            for rec, a, uses in rows]
    return {"types": _ranked(st + aoe, records),
            "types_single_target": _ranked(st, records),
            "types_aoe": _ranked(aoe, records),
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
        area = entry.get("area") == "aoe"
        for d in entry.get("debuffs") or []:
            land = d.get("landing_peak_percent") or {}
            e = d["effect"]
            if d.get("instant"):
                # spawn-facing like the timed spawn bucket: area powers only
                rate = d.get("landing_per_second_vs_scenario")
                if rate and area:
                    drain[e] = drain.get(e, 0.0) + rate
                    weights.setdefault("drain:" + e, []).append((rec, rate))
                continue
            up = d.get("uptime") or 0.0
            on_av = (land.get("vs_av") or 0.0) * up
            av[e] = av.get(e, 0.0) + on_av
            weights.setdefault("debuff_av:" + e, []).append((rec, on_av))
            if area:
                on_spawn = (land.get("vs_scenario") or 0.0) * up
                spawn[e] = spawn.get(e, 0.0) + on_spawn
                weights.setdefault("debuff_spawn:" + e, []).append((rec, on_spawn))
        for h in entry.get("heals") or []:
            if h.get("side") == "ally" and h.get("per_second"):
                weights.setdefault("healing", []).append((rec, h["per_second"]))
    # HitPoints rows sit on a heal table: the "percent" the shared helper returns
    # is absolute hit points x 100, so they are stated in hit points instead
    unit = lambda k: 0.01 if k in ABSOLUTE_TYPES else 1.0  # noqa: E731
    r = lambda d: {k: round(v * unit(k), 2) for k, v in sorted(d.items())}  # noqa: E731
    profiles = {k: range_profile.profile(v) for k, v in sorted(weights.items())}
    # one unit per bucket family is not shared (percent vs rate), so the overall
    # support profile reads the percent buckets: buffs and debuffs, not drains
    support_all = [w for k, v in weights.items()
                   if k.split(":")[0] in ("buff", "debuff_av", "debuff_spawn") for w in v]
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
                if e.get("pv_mode") == 2 or e.get("target") == "Self":   # a self crash
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


# ── keeping melee at bay ─────────────────────────────────────────────────────

# Area controls that hold a spawn where it is or push it away (owner,
# 2026-11-12: a root keeps them in place, knockback and repel push them off).
# Fear and holds stop attacks outright; that is control's own grade, not
# positioning, so they are not counted here.
KEEP_AT_BAY = ("Immobilized", "Knockback", "Knockup", "Repel")
KNOCK_SECONDS = 3.0         # one knock keeps a foe off its feet ~3 s (role_output's rule)
# The rating spawn's rank mix (tools/fetch_critter_data.py SPAWN_RANK_WEIGHTS,
# pinned equal by tools/test_matchups.py): a root holds only the ranks its
# magnitude beats (support_ledger.RANK_PROTECTION).
SPAWN_RANK_WEIGHTS = {"minion": 0.6, "lieutenant": 0.3, "boss": 0.1}


def _holds_at_range(rec, toggle):
    """A control keeps a closing spawn away only if it lands before they arrive:
    one aimed at range, or a self-centred toggle (a repel or knock aura pushes
    them out as they step in). A self-centred click lands only on foes already
    in melee, after they have swung."""
    if rec is None:
        return True
    centred = (rec.get("range") or 0.0) <= 0 and (rec.get("radius") or 0.0) > 0
    return toggle or not centred


def _ranks_held(control):
    """Share of the spawn a root holds: the ranks its magnitude beats. Knocks and
    repels push every rank (rank protection is mez protection, not knockback)."""
    if control["mez"] != "Immobilized" or "affects_in_one_application" not in control:
        return 1.0
    held = control.get("affects_in_one_application") or []
    return sum(w for rank, w in SPAWN_RANK_WEIGHTS.items() if rank in held)


def positioning(team_support, records=None):
    """How much of the fight the build keeps melee foes at bay: the best area
    root, knockback or repel by its uptime (a toggle holds it the whole time; a
    click root lasts its duration per cycle; a knock buys ~3 s per cast), times
    the share of the spawn it holds, counting only controls that land before the
    spawn reaches you."""
    records = records or {}
    best, source = 0.0, None
    for entry in team_support.get("powers") or []:
        if entry.get("area") != "aoe":
            continue
        cost = entry.get("cost") or {}
        toggle = str(cost.get("basis", "")).startswith("toggle")
        if not _holds_at_range(records.get(entry.get("power")), toggle):
            continue
        for c in entry.get("controls") or []:
            if c.get("mez") not in KEEP_AT_BAY:
                continue
            if toggle:
                up = 1.0
            elif c["mez"] == "Immobilized":
                up = c.get("uptime") or 0.0
            else:
                # the ledger's knock "duration" is a magnitude, not seconds:
                # a knock buys KNOCK_SECONDS per cast, once per recharge cycle
                cycle = c.get("cycle_seconds") or 0.0
                up = min(1.0, KNOCK_SECONDS / cycle) if cycle > 0 else 0.0
            up *= _ranks_held(c)
            if up > best:
                best, source = up, {"power": entry.get("power"), "mez": c["mez"],
                                    "uptime": round(up, 3)}
    return {"keep_at_bay": round(best, 3), "source": source,
            "basis": "best area root/knockback/repel by uptime x the share of the spawn it "
                     "holds (a root only the ranks its magnitude beats); aimed controls and "
                     "self-centred toggles only (a self-centred click lands after they "
                     "arrive); fear and holds are control, not positioning"}
