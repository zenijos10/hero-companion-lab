"""Fetch how each damage patch lives, from City of Data (the game's own records).

    python tools/fetch_patch_pets.py [--refresh]

Owner, 2026-11-15 ("archery doesnt have data? Go get it!"): 65 pickable powers
deal their damage through a pulsing pseudo-pet (Rain of Arrows, Rain of Fire,
Blizzard, Whirlpool, Lightning Rod, Shield Charge...), and the pet's pulse has
no animation time, so the engine's pet chain never priced it: every one was
credited zero damage.

For each such power (the census: a pickable record with no damage rows of its
own whose pet_powersets hold a pulsing damage record) this walks the power's
CoD record to every Create_Entity effect (child effects included): which entity
it creates, after what delay and for how long, then the entity's own record for
its class and power list. Written to data/patch_pets.json:

  {"powers": {summoner: {"entities": [{"entity", "delay", "lifetime", "class",
                                        "pulse_powers": [our pet records],
                                        "redirect": true when the patch has no
                                        entity of its own (class None: the
                                        caster's tables)}]}},
   "missing": {summoner: reason}, "source", "revision", "fetched"}

An entity whose powers carry no damage in our data (a visual) is recorded with
an empty pulse_powers list, so the engine prices exactly the damage entity. The
damage itself stays OUR data's rows (the same rows the pet channel reads);
CoD supplies only what our data lacks: lifetimes, delays and the mapping.
Polite: cached, 4 at a time (tools/fetch_critter_data.py's client).
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import fetch_critter_data as cod  # noqa: E402

OUT = os.path.join(ROOT, "data", "patch_pets.json")
# patches whose damage hangs on a condition the build cannot promise, stated
# rather than priced (read from their City of Data records, 2026-11-15)
STATED = {
    "Oil_Slick_Arrow": "the slick burns only once a Fire attack ignites it (a second entity, "
                       "created on that condition); unpriced until a scenario says who ignites it",
    "Storm_Cell": "the cloud's lightning strikes foes that the caster's own Storm Blast attacks "
                  "hit (triggered, not pulsing); unpriced",
}


def census(powers_by_set, powersets):
    """Pickable records that deal damage only through a pulsing pet."""
    offered = {ps["full_name"] for sets in powersets["by_archetype"].values()
               for group in sets.values() for ps in group}
    offered |= {ps["full_name"] for ps in powersets.get("pools") or []}
    out = []
    for ps in sorted(offered):
        for rec in powers_by_set.get(ps) or []:
            if rec.get("damage_effects") or (rec.get("level_available") or 0) < 1:
                continue
            for pps in rec.get("pet_powersets") or []:
                if any(_pulses(t) for t in powers_by_set.get(pps) or []):
                    out.append(rec["full_name"])
                    break
    return out


def _pulses(rec):
    """A pet record that deals PvE damage on its own period, with no animation."""
    return (not (rec.get("cast_time") or 0) and (rec.get("activate_period") or 0) > 0
            and any(d.get("pv_mode", 0) != 2 for d in rec.get("damage_effects") or []))


def _seconds(text):
    m = re.match(r"\s*([\d.]+)", str(text or ""))
    return float(m.group(1)) if m else 0.0


def _leaf(name):
    return name.rsplit(".", 1)[-1].replace("_", "").lower()


def ours(name, summoner, by_full, powers_by_set):
    """Our record for a power the game names: the same full name, else the one
    record with the same leaf inside the summoner's own pet powersets (the
    game's `Pets.Sleet.Sleet` is our `Villain_Pets.Sleet.Sleet`): two signals,
    the leaf and the summoner's own link, never a leaf alone."""
    if name in by_full:
        return name
    hits = [r["full_name"] for ps in summoner.get("pet_powersets") or []
            for r in powers_by_set.get(ps) or [] if _leaf(r["full_name"]) == _leaf(name)]
    return hits[0] if len(hits) == 1 else None


def _damages(rec):
    return any(d.get("pv_mode", 0) != 2 for d in rec.get("damage_effects") or [])


def creates(effects):
    """Every Create_Entity in an effect list (child effects included), skipping
    groups the game gates on a condition we cannot evaluate (requires)."""
    out = []
    for group in effects or []:
        if group.get("requires"):
            continue
        for t in group.get("templates") or []:
            params = t.get("params") or {}
            attribs = t.get("attribs") or []
            row = {"delay": float(t.get("delay") or 0.0), "lifetime": _seconds(t.get("duration"))}
            if "Execute_Power" in attribs and params.get("power_names"):
                # the power runs ONCE (Spring Attack's landing, Power Surge's crash pulse)
                out.append(dict(row, entity=None, lifetime=0.0, execute=True,
                                redirects=list(params["power_names"])))
                continue
            if "Create_Entity" not in attribs:
                continue
            if params.get("entity_def"):
                out.append(dict(row, entity=params["entity_def"]))
            elif params.get("redirects"):
                # a redirect patch: no entity of its own, the record names the
                # powers it runs; it prices with the CASTER's tables (the
                # Caltrops Page 4 note: "now inherits AT modifiers")
                out.append(dict(row, entity=None, redirects=list(params["redirects"]),
                                display_name=params.get("display_name")))
        out.extend(creates(group.get("child_effects")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    with open(os.path.join(ROOT, "data", "powers.json"), encoding="utf-8") as f:
        powers_by_set = json.load(f)
    with open(os.path.join(ROOT, "data", "powersets.json"), encoding="utf-8") as f:
        powersets = json.load(f)
    by_full = {r["full_name"]: r for pw in powers_by_set.values() for r in pw}
    summoners = census(powers_by_set, powersets)
    print(f"{len(summoners)} summoners deal damage only through a pulsing pet", flush=True)
    fetched = cod._fetch_all([cod.power_path(n) for n in summoners], args.refresh)
    plan, missing, entities = {}, {}, set()
    for n in summoners:
        rec = fetched[cod.power_path(n)]
        if rec is None:
            missing[n] = "no City of Data record"
            continue
        made = creates(rec.get("effects"))
        if not made:
            missing[n] = "its record creates no entity"
            continue
        plan[n] = made
        entities |= {m["entity"] for m in made if m.get("entity")}
    ent_recs = cod._fetch_all([f"entities/{e.lower()}.json" for e in sorted(entities)], args.refresh)
    out = {}
    for n, made in plan.items():
        rows = []
        for m in made:
            if not m.get("entity"):
                names = [ours(p, by_full[n], by_full, powers_by_set) for p in m["redirects"]]
                fires = _damages if m.get("execute") else _pulses
                rows.append({"entity": m.get("display_name"), "delay": m["delay"],
                             "lifetime": m["lifetime"], "class": None, "redirect": True,
                             "execute": bool(m.get("execute")),
                             "pulse_powers": [p for p in names if p and fires(by_full[p])]})
                continue
            ent = ent_recs.get(f"entities/{m['entity'].lower()}.json")
            if not ent:
                missing[n] = f"entity {m['entity']} has no City of Data record"
                break
            d = ent.get("defaults") or {}
            names = [p for p in d.get("power_full_names") or [] if p in by_full]
            rows.append(dict(m, **{"class": "Class_" + (d.get("character_class_name") or "").title()
                                   if d.get("character_class_name") else None,
                                   "pulse_powers": [p for p in names if _pulses(by_full[p])],
                                   "copy_creator_mods": bool(ent.get("copy_creator_mods"))}))
        else:
            if any(r["pulse_powers"] for r in rows):
                out[n] = {"entities": rows}
            else:
                missing[n] = "no created entity carries a pulsing damage power in our data"
    for k in missing:
        if k.rsplit(".", 1)[-1] in STATED:
            missing[k] = STATED[k.rsplit(".", 1)[-1]]
    expected = len(summoners)
    print(f"{len(out)} of {expected} expected summoners mapped; {len(missing)} not: "
          + "; ".join(f"{k}: {v}" for k, v in sorted(missing.items())[:12]))
    index = cod._get("index.json") or {}
    data = {"source": "City of Data (cod.uberguy.net), the game's own power and entity records",
            "revision": index.get("revision") or index.get("version"),
            "fetched": datetime.date.today().isoformat(),
            "method": __doc__.split("Polite:")[0].strip(),
            "powers": out, "missing": missing}
    blob = (json.dumps(data, indent=1, sort_keys=True) + "\n").encode("utf-8")
    with open(OUT, "wb") as f:
        f.write(blob)
    print(f"wrote data/patch_pets.json: {len(out)} summoners")
    return 0


if __name__ == "__main__":
    sys.exit(main())
