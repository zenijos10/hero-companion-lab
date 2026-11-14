"""MAX STRIKE: the hardest the build hits when it lines everything up (owner,
2026-11-14: "If you purposefully stacked any damage increasing powers and fired
off the hardest hitting attacks how strong? ... there are reasons you might want
somebody with massive single target or massive AOE max strikes and other times
you want something that's a little bit more sustained").

The sustained damage grades average a click damage buff (Build Up, Aim, Tidal
Forces) over its whole recharge (engine._mode_duty_cycle, a deliberate
understatement). The strike reads the same build the other way: every
damage-buff click fired at once, then the order of attacks that deals the
most damage before the buffs run out. Two lenses on one build, neither
replacing the other; how often a fight gives you the opening is not modelled.

  buffs     every click that buffs your damage and deals none itself, switched
            on at full strength (the engine recalculates with it on, the same
            way the emergency ledger measures a click). Power Boost is not one:
            our data has it amplify mez, defense, heals, absorb and speed.
  window    STRIKE_SECONDS (10 s), the length of Build Up and Aim: a strike is a
            burst. Every damage-buff click in the data lasts at least that long
            (Rage 120 s, Meltdown 60 s), so all of them are up throughout; the
            window never stretches to a long buff's duration.
  chain     the order of attacks that deals the most damage inside the window:
            any ready attack, again once it recharges (at the buffed recharge),
            every animation finishing inside the window. An exact search, so a
            position with more attacks to choose from never strikes lower.
            Momentum-gated attacks are left out (they cannot open a fight), and
            so is Defiance's per-attack stacking (an understatement, stated).
  running   what keeps dealing damage while you attack: damage auras and
            toggles, patches already laid (Whirlpool, Irradiated Ground) and
            your pets, each at its sustained rate for the whole window. A patch
            is counted as down when the strike opens; pets as already summoned.
  fight     the rating scenario's hit chance (with the buffs' +ToHit) and
            purple patch, the same factors the sustained grades use.
  position  standing at range only range attacks reach; at midrange, midrange
            and range ones; in melee, everything. The graded value is the strike
            from wherever the build's attacks reach (everything); the positions
            ride beside it.
Single target counts every attack (an area attack hits the main target too)
plus your pets; area counts area attacks and area auras/patches only, per
target. vs_sustained compares the strike with the build's own sustained damage
over the same seconds on the SAME basis (the chain, pets, hit chance and level
penalty; Hasten, slows, the inherent meter and endurance left out of both).
Rating only: nothing here feeds the champion score.
"""
import copy

import engine
import first_principles
import range_profile

STRIKE_SECONDS = 10.0       # the strike's window: Build Up's and Aim's own duration
POSITIONS = ("melee", "midrange", "range")
REACHES_FROM = {"melee": ("melee", "midrange", "range"),
                "midrange": ("midrange", "range"),
                "range": ("range",)}


def _buff_duration(rec):
    """The duration of a click's damage buff, or 0 when it is not a pure
    damage-buff click. Defiance is not one: its per-cast bonus rides an
    attack's own record, or a patch summoner's (Whirlpool, Dark Pit), as a flat
    value on a `*_Ones` table (7 records), where every real buff (Build Up, Aim,
    Tidal Forces, Fiery Embrace: 157 records) reads an archetype buff table."""
    if (rec.get("power_type") or 0) != 0 or rec.get("damage_effects"):
        return 0.0
    rows = [fx for fx in rec.get("self_effects") or []
            if fx.get("mode") and fx.get("effect") == "DamageBuff"
            and (fx.get("scale") or 0) > 0 and not fx.get("delay")
            and not str(fx.get("modifier_table") or "").endswith("_Ones")]
    return max((fx.get("duration") or 0.0 for fx in rows), default=0.0)


def buff_clicks(powers, records):
    """[(index, record, buff seconds)] for the build's damage-buff clicks."""
    out = []
    for i, p in enumerate(powers):
        rec = records.get(p.get("full_name"))
        if not rec or p.get("_exemplar_off"):
            continue
        seconds = _buff_duration(rec)
        if seconds > 0:
            out.append((i, rec, seconds))
    return out


SEARCH_NODES = 200000        # the exact search's budget; past it the best found is used


def chain(attacks, window):
    """The order of casts that deals the most damage inside the window: any
    ready attack may fire, each again once it recharges (counted from the end of
    its animation), and every animation must finish inside the window. An exact
    branch-and-bound search, so more attacks to choose from can never strike
    lower. Returns (casts in order, seconds spent animating, whether the
    search finished inside SEARCH_NODES: False means the best order found)."""
    order = sorted((a for a in attacks if (a.get("cast_time") or 0) > 0),
                   key=lambda a: (-(a.get("damage") or 0.0), a.get("name") or ""))
    if not order:
        return [], 0.0, True
    casts = [a["cast_time"] for a in order]
    dmg = [a.get("damage") or 0.0 for a in order]
    rech = [a.get("recharge") or 0.0 for a in order]
    by_rate = sorted(range(len(order)), key=lambda i: -dmg[i] / casts[i])
    best = {"damage": -1.0, "seq": []}
    nodes = [0]
    seen = {}

    def bound(clock, ready):
        """The most damage the time left could still hold: each attack at most
        as often as its recharge allows, the time filled best-rate first (a
        fractional knapsack, so it never undercounts)."""
        left, total = window - clock, 0.0
        for i in by_rate:
            if left <= 0:
                break
            start = max(clock, ready[i])
            if start + casts[i] > window + 1e-9:
                continue
            n = 1 + int((window - start - casts[i]) // (casts[i] + rech[i]) + 1e-9)
            take = min(n * casts[i], left)
            total += take * dmg[i] / casts[i]
            left -= take
        return total

    def search(clock, ready, total, seq):
        nodes[0] += 1
        if total > best["damage"]:
            best["damage"], best["seq"] = total, list(seq)
        if nodes[0] > SEARCH_NODES or total + bound(clock, ready) <= best["damage"] + 1e-9:
            return
        # the same moment with the same cooldowns left: only a better total goes on
        key = (round(clock, 3), tuple(round(max(0.0, r - clock), 3) for r in ready))
        if seen.get(key, -1.0) >= total - 1e-9:
            return
        seen[key] = total
        for i in range(len(order)):
            start = max(clock, ready[i])
            end = start + casts[i]
            if end > window + 1e-9:
                continue
            was = ready[i]
            ready[i] = end + rech[i]
            seq.append(i)
            search(end, ready, total + dmg[i], seq)
            seq.pop()
            ready[i] = was

    search(0.0, [0.0] * len(order), 0.0, [])
    picked = [order[i] for i in best["seq"]]
    return picked, sum(a["cast_time"] for a in picked), nodes[0] <= SEARCH_NODES


def _running(attack):
    """A row that deals damage without being clicked into the chain: an aura or
    toggle (host type 1/2), or a patch summoner's pulse (no animation of its own)."""
    return attack.get("host_type") in (1, 2) or attack.get("dpa") is None


def _usable(attack, records):
    return ((attack.get("cast_time") or 0) > 0 and not _running(attack)
            and attack.get("name") not in engine.MOMENTUM_GATED_DISPLAY
            and records.get(attack.get("full_name")) is not None)


def _summary(picked, used, exact, factor, records, running=0.0):
    damage = sum((a.get("damage") or 0.0) for a in picked) * factor + running
    names = []
    for a in picked:                    # 'Blaze x2' for a refired attack, first-cast order
        n = a.get("name")
        if n not in names:
            names.append(n)
    counts = {n: sum(1 for a in picked if a.get("name") == n) for n in names}
    return {"damage": round(damage, 1), "seconds_used": round(used, 2), "exact": exact,
            "running_damage": round(running, 1),
            "attacks": [n if counts[n] == 1 else f"{n} x{counts[n]}" for n in names],
            "where": range_profile.profile([(records.get(a.get("full_name")),
                                             (a.get("damage") or 0.0)) for a in picked])}


def _factor(totals, sc):
    hit = first_principles.outgoing_hit(first_principles._pct(totals, "tohit"),
                                        first_principles._pct(totals, "accuracy"), sc)
    return hit, hit * first_principles.player_effect_strength(sc.get("shift", 0))


def strike(build_powers, totals, sc, records, recalculate, pet_dps=0.0):
    """The max strike (see the module docstring). recalculate(powers) returns
    engine totals for a power list (the evaluation's own calculate_build);
    pet_dps = the pets' damage per second in the rating fight (already after
    their own hit chance and level penalty)."""
    fired = buff_clicks(build_powers, records)
    if fired:
        powers = copy.deepcopy(build_powers)
        for i, _rec, _s in fired:
            powers[i]["include_in_totals"] = True
        buffed = recalculate(powers)
    else:
        buffed = totals
    window = STRIKE_SECONDS
    rows = (buffed.get("offense") or {}).get("attacks") or []
    attacks = [a for a in rows if _usable(a, records)]
    hit, factor = _factor(buffed, sc)
    pets = (pet_dps or 0.0) * window
    run_st = sum((a.get("dps_spam") or 0.0) for a in rows if _running(a)) * window * factor
    run_aoe = sum((a.get("dps_spam") or 0.0) for a in rows
                  if _running(a) and a.get("is_aoe")) * window * factor
    band = {a.get("full_name"): range_profile.band(records[a["full_name"]]) or "midrange"
            for a in attacks}

    def lens(pool, running):
        out = {}
        for pos in POSITIONS:
            reach = [a for a in pool if band[a.get("full_name")] in REACHES_FROM[pos]]
            out[pos] = _summary(*chain(reach, window), factor, records, running)
        return out

    single = lens(attacks, run_st + pets)
    area = lens([a for a in attacks if a.get("is_aoe")], run_aoe)
    # the sustained side of vs_sustained, on the strike's own basis
    off = totals.get("offense") or {}
    _hit0, factor0 = _factor(totals, sc)
    sustained = {"single_target": ((off.get("st_dps") or 0.0) * factor0 + (pet_dps or 0.0)) * window,
                 "aoe_per_target": (off.get("aoe_dps") or 0.0) * factor0 * window}
    for lens_key, row in (("single_target", single["melee"]), ("aoe_per_target", area["melee"])):
        row["vs_sustained"] = (round(row["damage"] / sustained[lens_key], 2)
                               if sustained[lens_key] > 0 else None)
    return {
        "window_seconds": window,
        "buffs": [r.get("display_name") or r.get("full_name") for _i, r, _s in fired],
        "hit_chance": round(hit, 4),
        "single_target": dict(single["melee"], by_position=single),
        "aoe_per_target": dict(area["melee"], by_position=area),
        "basis": "every damage-buff click fired at full strength, then the order of "
                 "attacks that deals the most damage in 10 seconds (exact search; "
                 "refires once recharged), plus auras, patches already laid and pets at their "
                 "sustained rate; the rating fight's hit chance and level penalty; Defiance "
                 "stacking and momentum-gated attacks left out (server/strike.py)",
    }
