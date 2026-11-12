"""M3: team support measured per power (buffs, debuffs, heals, control).

Display only: nothing here feeds a score. Every magnitude, uptime and share
comes from the SAME helpers the score uses (role_output.row_peak_pct,
click_uptime, attack_share, _power_enh, power_control_uptime;
first_principles.player_effect_strength), so the ledger explains the score's
inputs instead of re-deriving them.

Per power and effect it reports magnitude, coverage (single target or area,
with the target cap), uptime, sustained vs burst, reliability (stated chance),
landing strength in the rating scenario and against an AV (purple patch, AV
debuff resistance, which never applies to -Resistance), and the opportunity
cost of running it (cast seconds and endurance per minute).
"""
import engine
import first_principles
import role_output

SUSTAINED_UPTIME = 0.98         # the same "perma" line power_control_uptime uses
EMERGENCY_HEAL_CYCLE = 60.0     # a heal on a cycle this long is an emergency button
# Mez protection by rank, the wiki-verified table quoted in first_principles
# SCENARIOS (Minion 1, Lieutenant 2, Boss 3, Elite Boss 6, AV 3+50 with its
# triangles up). A mez lands only when the summed magnitude EXCEEDS protection.
RANK_PROTECTION = (("minion", 1.0), ("lieutenant", 2.0), ("boss", 3.0),
                   ("elite_boss", 6.0), ("archvillain", 53.0))


def _record(ctx, power):
    pbf = ctx.get("power_by_full") or {}
    return pbf.get(power.get("full_name"))


def _enhanced_recharge(rec, slots, ctx, global_recharge):
    base = rec.get("base_recharge") or 0.0
    enh = role_output._power_enh(dict(rec, slots=slots), ctx, ("RechargeTime",))
    return base / (1.0 + global_recharge + enh["RechargeTime"]) if base > 0 else 0.0


def _coverage(rec):
    area = engine.is_aoe(rec)
    return {"area": "aoe" if area else "single_target",
            "max_targets": (rec.get("max_targets") or None) if area else 1}


def _cost(rec, enh_rech):
    """Animation seconds and endurance per minute of keeping the power running."""
    if (rec.get("power_type") or 0) in engine.ACTIVE_POWER_TYPES:
        period = rec.get("activate_period") or 0.0
        end = (rec.get("end_cost") or 0.0) * 60.0 / period if period > 0 else 0.0
        return {"cast_seconds_per_minute": 0.0, "endurance_per_minute": round(end, 2),
                "basis": "toggle/auto: endurance per activate period"}
    cast = rec.get("cast_time") or 0.0
    cycle = max(enh_rech, cast)
    casts = 60.0 / cycle if cycle > 0 else 0.0
    return {"cast_seconds_per_minute": round(cast * casts, 2),
            "endurance_per_minute": round((rec.get("end_cost") or 0.0) * casts, 2),
            "basis": "click cast on cooldown"}


def _strengths(effect, peak, scenario):
    """Peak landing strength against the rating scenario's foes and against an
    AV: purple patch at each shift, AV debuff resistance (not on -Resistance)."""
    av = first_principles.SCENARIOS["av"]
    resist = 0.0 if effect == "Resistance" else av.get("debuff_res", 0.0)
    return {
        "vs_scenario": round(peak * first_principles.player_effect_strength(scenario["shift"])
                             * (1.0 - (0.0 if effect == "Resistance"
                                       else scenario.get("debuff_res", 0.0))), 2),
        "vs_av": round(peak * first_principles.player_effect_strength(av["shift"])
                       * (1.0 - resist), 2),
    }


def _effect_rows(rec, kind, ctx, enh, enh_rech, share):
    """Buff or debuff rows of one power keyed by effect, with the score's own
    aggregation (role_output.enhanced_debuff_totals / enhanced_team_buffs):
    rows SUM within (effect, damage type), then typed spreads collapse to the
    largest type so a template written once per type is not counted eight
    times. Peak and average are aggregated separately (each row carries its
    own uptime), so the average equals what the score credits for this power.
    Instant rows (a click effect with no duration) add to the peak only."""
    mod_tables = ctx.get("modifier_tables") or {}
    col = ctx.get("at_column")
    field = "debuff_effects" if kind == "debuff" else "buff_effects"
    click = (rec.get("power_type") or 0) == 0
    by_type = {}
    for d in rec.get(field) or []:
        if d.get("pv_mode") == 2 or d.get("target") == "Self":
            continue
        if kind == "buff" and d.get("effect") == "Heal":
            continue                                   # heals have their own section
        peak = role_output.row_peak_pct(d, mod_tables, col)
        if peak is None:
            continue
        effect = d.get("effect")
        if kind == "debuff" and effect in ("Defense", "ToHit"):
            peak *= 1.0 + enh[effect]                  # the score's v10 enhancement
        duration = d.get("duration") or 0.0
        cell = by_type.setdefault((effect, d.get("damage_type") or "None"),
                                  {"peak": 0.0, "average": 0.0, "timed": False, "chance": 0.0})
        cell["peak"] += peak
        cell["chance"] = max(cell["chance"], min(max(d.get("probability") or 1.0, 0.0), 1.0))
        if click and duration <= 0:
            continue                                   # instant: no lasting effect to average
        uptime = role_output.click_uptime(rec.get("power_type"), enh_rech, duration)
        if kind == "debuff" and rec.get("is_attack") and click:
            uptime *= share                            # one animation bar (v17)
        cell["average"] += peak * uptime
        cell["timed"] = True
    by_effect = {}
    for (effect, dtype), cell in by_type.items():
        row = by_effect.setdefault(effect, {"peak": 0.0, "average": 0.0, "timed": False,
                                            "types": set(), "chance": 0.0})
        row["types"].add(dtype)
        row["peak"] = max(row["peak"], cell["peak"])          # typed spread -> per-type value
        row["average"] = max(row["average"], cell["average"])
        row["timed"] = row["timed"] or cell["timed"]
        row["chance"] = max(row["chance"], cell["chance"])
    return by_effect


def _heal_rows(rec, ctx, enh_rech):
    mod_tables = ctx.get("modifier_tables") or {}
    col = ctx.get("at_column")
    rows = []
    group = min(int(rec.get("max_targets") or 6), 16) if (rec.get("radius") or 0) > 0 else 1
    cycle = max(enh_rech, rec.get("cast_time") or 0.0)
    for h in rec.get("heal_effects") or []:
        if h.get("pv_mode") == 2:
            continue
        ally = h.get("to_who") != 2
        per_cast = role_output._heal_mag(h, mod_tables, col)
        targets = group if ally else 1
        rows.append({
            "side": "ally" if ally else "self",
            "per_cast_per_target": round(per_cast, 3),
            "targets": targets,
            "per_second": round(per_cast * targets / cycle, 3) if cycle > 0 else None,
            "cycle_seconds": round(cycle, 1),
            "kind": "emergency" if cycle >= EMERGENCY_HEAL_CYCLE else "sustained",
            "unit": "model_heal_units (the score's heal scale, not literal HP)",
        })
    return rows


def _control_rows(rec, slots, ctx, global_recharge):
    mod_tables = ctx.get("modifier_tables") or {}
    col = ctx.get("at_column")
    enh = role_output._power_enh(dict(rec, slots=slots), ctx, ("RechargeTime", "Mez"))
    enh_rech = (rec.get("base_recharge") or 0.0) / (1.0 + global_recharge + enh["RechargeTime"])
    toggle = (rec.get("activate_period") or 0) > 0
    best = {}
    for c in rec.get("control_effects") or []:
        if role_output._is_pvp_variant(c):
            continue
        duration = abs(c.get("scale") or 0.0) * role_output._table_val(
            mod_tables, c.get("modifier_table"), col) * (1.0 + enh["Mez"])
        mag = (c.get("nmag") or 1.0) * min(max(c.get("probability") or 1.0, 0.0), 1.0)
        mez = c.get("mez")
        if mez not in best or (duration, mag) > (best[mez]["duration_seconds"], best[mez]["magnitude"]):
            uptime = 1.0 if toggle else (min(1.0, duration / enh_rech) if enh_rech > 0 else 1.0)
            best[mez] = {"mez": mez, "kind": c.get("kind"), "magnitude": round(mag, 2),
                         "duration_seconds": round(duration, 2), "uptime": round(uptime, 3),
                         "sustained": toggle or uptime >= SUSTAINED_UPTIME,
                         "affects_in_one_application": [rank for rank, prot in RANK_PROTECTION
                                                        if mag > prot]}
    return [best[k] for k in sorted(best)]


def power_ledger(power, ctx, global_recharge, scenario, share):
    """Every support output of one picked power, or None if it has none."""
    rec = _record(ctx, power)
    if not rec:
        return None
    slots = power.get("slots") or []
    enh = role_output._power_enh(dict(rec, slots=slots), ctx, ("Defense", "ToHit", "RechargeTime"))
    enh_rech = _enhanced_recharge(rec, slots, ctx, global_recharge)
    out = {}
    click = (rec.get("power_type") or 0) == 0
    for kind in ("buff", "debuff"):
        rows = []
        for effect, r in sorted(_effect_rows(rec, kind, ctx, enh, enh_rech, share).items()):
            instant = not r["timed"]
            uptime = (r["average"] / r["peak"]) if (not instant and r["peak"] > 0) else None
            row = {"effect": effect, "types": sorted(r["types"]),
                   "peak_percent": round(r["peak"], 2),
                   "uptime": None if uptime is None else round(uptime, 3),
                   "average_percent": None if instant else round(r["average"], 2),
                   "sustained": uptime is not None and uptime >= SUSTAINED_UPTIME,
                   "instant": instant, "chance": r["chance"]}
            if kind == "debuff":
                row["landing_peak_percent"] = _strengths(effect, r["peak"], scenario)
                cycle = max(enh_rech, rec.get("cast_time") or 0.0)
                if instant and cycle > 0 and r["peak"] > 0:
                    # an instant drain lands once per cast: a rate, not an average
                    # (an attack shares the one animation bar, like timed debuffs)
                    per_cast = row["landing_peak_percent"]["vs_scenario"]
                    bar = share if (rec.get("is_attack") and click) else 1.0
                    # the peak is already chance-weighted (role_output.row_peak_pct)
                    row["landing_per_second_vs_scenario"] = round(per_cast * bar / cycle, 3)
            rows.append(row)
        if rows:
            out[kind + "s"] = rows
    heals = _heal_rows(rec, ctx, enh_rech)
    if heals:
        out["heals"] = heals
    controls = _control_rows(rec, slots, ctx, global_recharge)
    if controls:
        out["controls"] = controls
    if not out:
        return None
    if rec.get("is_resurrect"):
        out["conditional"] = "resurrect: its buffs land only on an ally it revives"
    return dict({"power": rec["full_name"], "display_name": rec.get("display_name")},
                **_coverage(rec), cost=_cost(rec, enh_rech), **out)


def _summary(ledger):
    """Per effect: sustained vs burst buffs, and debuffs split single-target
    (what an AV fight runs on) vs area (what a spawn runs on)."""
    buffs = {"sustained": {}, "burst": {}}
    debuffs = {"single_target_vs_av": {}, "aoe_vs_scenario": {}}
    for entry in ledger:
        if entry.get("conditional"):
            continue                       # a rez's buffs are not a standing team buff
        for b in entry.get("buffs") or []:
            if b["instant"]:
                continue
            bucket = buffs["sustained" if b["sustained"] else "burst"]
            bucket[b["effect"]] = round(bucket.get(b["effect"], 0.0) + b["average_percent"], 2)
        for d in entry.get("debuffs") or []:
            if d["instant"]:
                continue
            strength = d["landing_peak_percent"]
            key, value = (("aoe_vs_scenario", strength["vs_scenario"]) if entry["area"] == "aoe"
                          else ("single_target_vs_av", strength["vs_av"]))
            debuffs[key][d["effect"]] = round(debuffs[key].get(d["effect"], 0.0)
                                              + value * d["uptime"], 2)
    heals = {"sustained_per_second": 0.0, "emergency_per_second": 0.0}
    for entry in ledger:
        for h in entry.get("heals") or []:
            if h["side"] == "ally" and h["per_second"]:
                heals[h["kind"] + "_per_second"] = round(heals[h["kind"] + "_per_second"]
                                                         + h["per_second"], 3)
    return {"buffs_average_percent": buffs, "debuffs_landing_average_percent": debuffs,
            "ally_heals": heals,
            "basis": "average = peak x uptime (instant effects and resurrect buffs excluded); landing = after purple patch and AV debuff "
                     "resistance (none on -Resistance); single-target debuffs judged vs an AV, "
                     "area debuffs vs the rating scenario's spawn"}


def build_ledger(powers, ctx, global_recharge, scenario):
    """The support ledger of a build plus its summary."""
    share = role_output.attack_share(powers, ctx, global_recharge)
    ledger = [e for e in (power_ledger(p, ctx, global_recharge, scenario, share)
                          for p in powers) if e]
    return {"powers": ledger, "summary": _summary(ledger), "attack_share": round(share, 3)}
