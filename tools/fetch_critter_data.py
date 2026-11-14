"""Fetch Homecoming critter data from City of Data (cod.uberguy.net) and compile
data/critter_groups.json: per enemy group, what its standard level-50
minions, lieutenants and bosses throw at you.

Owner's ruling (2026-11-12): the matchups source is the game export when on his
PC, else a public source; City of Data serves the game's own critter records
(entity defaults + power records, the same fields as the client bins), which is
closer to the game than a wiki page. Labelled as such in the output.

Per group (numbers at level 54 = +4 to a level 50, from each critter's own
class table):
  critters             standard critters read, by rank
  rank_accuracy        the spawn's mean rank accuracy (stated rank mix)
  dps_per_critter      sustained damage per critter (attacks at their own cycle,
                       scaled down when the animations overlap)
  damage_mix           share of that damage by "Position|Type": positions are the
                       game's own attack_types (its "Area" = our AoE); an attack
                       tagged with several is one cell, "Ranged+AoE", defended by
                       the best of them; untagged attacks count as Ranged.
                       Damage over time counts every tick.
  def_debuff / tohit_debuff / res_debuff   share of attacks that land it,
                       percent per landed hit, seconds it lasts
  resistances          the group's passive self resistance by type, percent
                       (negative = a vulnerability; stacked past 100 = immune)
  mez                  mez types its attacks carry
Spawn rank mix (stated): 60% minions, 30% lieutenants, 10% bosses.

Polite by design: 4 parallel requests, every response cached under
tools/gamedata/_cod_cache/ (gitignored), so a rerun costs nothing.
Usage: python tools/fetch_critter_data.py [--refresh]
"""
import argparse
import concurrent.futures
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "tools", "gamedata", "_cod_cache")
OUT = os.path.join(ROOT, "data", "critter_groups.json")
BASE = "https://cod.uberguy.net/homecoming"
UA = "HeroCompanion-critter-fetch/1.0 (cached, 4 parallel)"
RANKS = {"VR_MINION": "minion", "VR_LIEUTENANT": "lieutenant", "VR_BOSS": "boss"}
TYPES = {"Smashing_Dmg": "Smashing", "Lethal_Dmg": "Lethal", "Fire_Dmg": "Fire",
         "Cold_Dmg": "Cold", "Energy_Dmg": "Energy", "Negative_Energy_Dmg": "Negative",
         "Psionic_Dmg": "Psionic", "Toxic_Dmg": "Toxic"}
POSITIONS = ("Melee", "Ranged", "AoE")
# The game's attack_types spell the area position "Area"; ours (and the
# defense totals) say "AoE". Translate the vocabulary (CLAUDE.md rule 5).
GAME_POSITIONS = {"Melee": "Melee", "Ranged": "Ranged", "Area": "AoE"}
# Entity keys that are not standard enemies (pets, objects, events, NPCs, heroes
# and level/role variants of the same critter).
SKIP_PREFIX = {"objects", "pets", "event", "npc", "base", "incarnatepets", "miscellaneous",
               "prisoners", "genericheroes", "genericvillains", "freedomcorps", "paragonpolice",
               "summerevent", "roguesgallery", "freedomphalanx", "vindicators", "paragonheroes",
               "reflections", "timeechoes", "frklk", "mastermindpets", "turrets"}
SKIP_TOKEN = re.compile(r"(^|_)(high|medium|noscale|enraged|gm|event|mission|pet|pets|special|"
                        r"tutorial|ally|npc|object|test|dummy|decoy|hostage|captive|civilian|"
                        r"contact|av|hero|monster|eb|giant|summon|spawn|zone)($|_)")
MIN_LEVEL_50 = 50          # the group must field this critter at level 50+
MIN_ENTITIES = 3           # a group needs this many standard critters to be listed
# Groups that are not enemies a build fights at +4 (stated, by name): event
# crowds, allied forces and mission decoys. Critters the game marks as allies
# (entity "ally": Hero / Villain) are dropped individually as well.
NOT_ENEMY_GROUPS = {"WeddingGuestsHeroes", "WeddingGuestsVillains", "RedCapsEvent",
                    "Vanguard_Shield", "Vanguard_Sword", "Romans_Good", "GoodTurrets",
                    "KnivesOfArtemisFake", "MaltaFake"}
LEVEL_INDEX = 53           # class tables are per level, 0-based: level 54 = +4 to 50
# Stated constants: a spawn's rank mix (critters, not entity counts) and the
# game's per-rank accuracy multipliers (minion 1.0, lieutenant 1.15, boss 1.3).
SPAWN_RANK_WEIGHTS = {"minion": 0.6, "lieutenant": 0.3, "boss": 0.1}
RANK_ACCURACY = {"minion": 1.0, "lieutenant": 1.15, "boss": 1.3}


class FetchError(RuntimeError):
    """A record that could not be read (network, timeout, server error):
    never cached, so the next run tries again instead of remembering a gap."""


def _get(path, refresh=False):
    """JSON at BASE/path, cached on disk; None when the host says the record
    does not exist (404, cached as such) or keeps refusing it (403 after every
    retry: None for this run only, never cached, since a proxy or rate-limit
    refusal is not a fact about the record). Any other failure raises."""
    local = os.path.join(CACHE, path.replace("/", os.sep))
    if not refresh and os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            text = f.read()
        return json.loads(text) if text else None
    req = urllib.request.Request(f"{BASE}/{path}", headers={"User-Agent": UA,
                                                             "Accept-Encoding": "identity"})
    text = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            if raw[:2] == b"\x1f\x8b":          # the host gzips whatever we ask for
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                text = ""                      # absent: a fact worth caching
                break
            if e.code == 403 and attempt == 3:
                return None                    # refused 4 times: absent THIS run, never cached
            time.sleep(2 ** attempt)
        except OSError:
            time.sleep(2 ** attempt)
    if text is None:
        raise FetchError(f"could not read {path} after 4 attempts")
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "w", encoding="utf-8") as f:
        f.write(text)
    return json.loads(text) if text else None


def _fetch_all(paths, refresh):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        return dict(zip(paths, pool.map(lambda p: _get(p, refresh), paths)))


def candidates(names):
    return sorted({k for _, k in names
                   if k.split("_")[0] not in SKIP_PREFIX and not SKIP_TOKEN.search(k)})


def standard(entity):
    """(group, rank, class, power full names) for a standard level-50 enemy."""
    d = (entity or {}).get("defaults") or {}
    rank = RANKS.get(d.get("rank"))
    group = entity.get("group_name") if entity else None
    if (not rank or not group or (d.get("max_level") or 0) < MIN_LEVEL_50
            or group in NOT_ENEMY_GROUPS or entity.get("ally") in ("Hero", "Villain")):
        return None
    return (group, rank, (d.get("character_class_name") or "").lower(),
            [p for p in d.get("power_full_names") or [] if p.count(".") == 2])


def power_path(full_name):
    cat, pset, name = full_name.lower().split(".")
    return f"powers/{cat}/{pset}/{name}.json"


def _templates(power):
    for eff in power.get("effects") or []:
        if eff.get("is_pvp") == "PVP_ONLY":
            continue
        chance = eff.get("chance")
        for t in eff.get("templates") or []:
            yield t, (1.0 if chance is None else chance)
            for child in t.get("child_effects") or []:
                for ct in child.get("templates") or []:
                    yield ct, (1.0 if chance is None else chance)


def _seconds(text):
    m = re.match(r"([\d.]+)", str(text or ""))
    return float(m.group(1)) if m else 0.0


def _ticks(t):
    """How many times a damage template lands: once, or once at application and
    every application_period through its duration (a burn ticking 1 s for 3.1 s
    lands 4 times), each tick at its own tick_chance."""
    period = t.get("application_period") or 0.0
    chance = t.get("tick_chance")
    chance = 1.0 if chance is None else chance
    if period <= 0:
        return 1.0
    return (1 + int(_seconds(t.get("duration")) / period + 1e-9)) * chance


def _table(tables, name):
    """The class table value at the rating level (54 = +4 to a level 50)."""
    row = (tables or {}).get((name or "").lower())
    return abs(row[LEVEL_INDEX]) if row and len(row) > LEVEL_INDEX else 0.0


_FOE = ("AnyAffected", "Target", None)
_DEBUFF_ATTRIBS = {"Base_Defense": "def_debuff", "ToHit": "tohit_debuff"}


def attack_profile(power, tables):
    """What one critter power does to a player at level 54, or None if it is not
    an attack: damage by type (scale x chance x the class table), the game's
    positional attack types, the cycle, and the debuffs it lands."""
    if not power or not str(power.get("target_type", "")).startswith("Foe"):
        return None
    damage, debuffs, mez = {}, [], set()
    for t, chance in _templates(power):
        if t.get("target") not in _FOE:
            continue
        attribs, aspect = t.get("attribs") or [], t.get("aspect")
        mag = abs(t.get("scale") or 0.0) * _table(tables, t.get("table")) * chance
        if not mag:
            continue
        for a in attribs:
            if a in TYPES and aspect == "Absolute":
                damage[TYPES[a]] = damage.get(TYPES[a], 0.0) + mag * _ticks(t)
            elif a in _DEBUFF_ATTRIBS and aspect == "Current" and "debuff" in (t.get("table") or "").lower():
                debuffs.append((_DEBUFF_ATTRIBS[a], mag * 100.0, _seconds(t.get("duration"))))
            elif a in ("Held", "Stunned", "Sleep", "Immobilized", "Terrorized", "Confused"):
                mez.add(a)
        if aspect == "Resistance" and any(a in TYPES for a in attribs):
            debuffs.append(("res_debuff", mag * 100.0, _seconds(t.get("duration"))))
    if not damage:
        return None
    # an attack tagged with several positions is defended by the BEST of them
    # (the game's rule), so it is ONE cell keyed by all of them, e.g. "Ranged+AoE"
    tags = [GAME_POSITIONS[a] for a in power.get("attack_types") or [] if a in GAME_POSITIONS]
    pos = "+".join(p for p in POSITIONS if p in tags) or "Ranged"
    act = power.get("activation_time") or 0.0
    return {"damage": damage, "positions": pos, "activation": act,
            "cycle": act + (power.get("recharge_time") or 0.0),
            "debuffs": debuffs, "mez": sorted(mez)}


def self_resistance(power, tables):
    """{type: percent} of a passive self resistance power (Auto/Toggle on self)."""
    if not power or power.get("type") not in ("Auto", "Toggle"):
        return {}
    out = {}
    for t, _chance in _templates(power):
        if t.get("target") not in ("Self", "Caster", None) or t.get("aspect") != "Resistance":
            continue
        mag = (t.get("scale") or 0.0) * _table(tables, t.get("table")) * 100.0
        for a in t.get("attribs") or []:
            if a in TYPES and mag:                 # negative = a vulnerability, kept
                out[TYPES[a]] = out.get(TYPES[a], 0.0) + mag
    return out


def critter(names, powers, tables):
    """One critter's sustained output: attacks fire at their own cycle, scaled
    down when their animations would need more than the whole time."""
    attacks = [a for a in (attack_profile(powers.get(n), tables) for n in names) if a]
    busy = sum(a["activation"] / a["cycle"] for a in attacks if a["cycle"] > 0)
    scale = 1.0 / busy if busy > 1.0 else 1.0
    out = {"dps": 0.0, "mix": {}, "attacks_per_second": 0.0, "debuffs": {}, "mez": set(),
           "res": {}}
    for a in attacks:
        rate = scale / a["cycle"] if a["cycle"] > 0 else 0.0
        out["attacks_per_second"] += rate
        for t, d in a["damage"].items():
            out["dps"] += rate * d
            key = f"{a['positions']}|{t}"
            out["mix"][key] = out["mix"].get(key, 0.0) + rate * d
        for kind, mag, dur in a["debuffs"]:
            cell = out["debuffs"].setdefault(kind, [0.0, 0.0, 0.0])   # rate, rate*mag, rate*dur
            cell[0] += rate
            cell[1] += rate * mag
            cell[2] += rate * dur
        out["mez"].update(a["mez"])
    for n in names:
        for t, v in self_resistance(powers.get(n), tables).items():
            out["res"][t] = out["res"].get(t, 0.0) + v
    # stacked resistance past 100% is immunity, not more than immune; a
    # vulnerability is kept (it raises the damage a build lands)
    out["res"] = {t: max(min(v, 100.0), -100.0) for t, v in out["res"].items()}
    return out


def compile_groups(members, powers, class_tables):
    groups = {}
    for group, rank, klass, names in members:
        c = critter(names, powers, class_tables.get(klass))
        if c["dps"] <= 0:
            continue
        groups.setdefault(group, []).append((rank, c))
    out = {}
    for group, crits in sorted(groups.items()):
        if len(crits) < MIN_ENTITIES:
            continue
        # a spawn's rank mix (stated): each rank's critters averaged, then weighted
        by_rank = {}
        for rank, c in crits:
            by_rank.setdefault(rank, []).append(c)
        weights = {r: SPAWN_RANK_WEIGHTS[r] for r in by_rank}
        whole_w = sum(weights.values())
        def avg(get):
            return sum(weights[r] / whole_w * sum(get(c) for c in cs) / len(cs)
                       for r, cs in by_rank.items())
        mix_keys = {k for _r, c in crits for k in c["mix"]}
        mix = {k: avg(lambda c, k=k: c["mix"].get(k, 0.0)) for k in mix_keys}
        dps = sum(mix.values())
        aps = avg(lambda c: c["attacks_per_second"])
        debuffs = {}
        for kind in ("def_debuff", "tohit_debuff", "res_debuff"):
            rate = avg(lambda c, kind=kind: c["debuffs"].get(kind, [0, 0, 0])[0])
            mag = avg(lambda c, kind=kind: c["debuffs"].get(kind, [0, 0, 0])[1])
            dur = avg(lambda c, kind=kind: c["debuffs"].get(kind, [0, 0, 0])[2])
            debuffs[kind] = {"attack_share": round(rate / aps, 3) if aps else 0.0,
                             "percent_per_hit": round(mag / rate, 2) if rate else 0.0,
                             "seconds": round(dur / rate, 1) if rate else 0.0}
        res_types = {t for _r, c in crits for t in c["res"]}
        out[group] = {
            "critters": {r: len(cs) for r, cs in sorted(by_rank.items())},
            "rank_accuracy": round(sum(weights[r] / whole_w * RANK_ACCURACY[r]
                                       for r in by_rank), 3),
            "dps_per_critter": round(dps, 1),
            "attacks_per_second_per_critter": round(aps, 3),
            "damage_mix": {k: round(v / dps, 4) for k, v in sorted(mix.items()) if v / dps >= 0.0005},
            **debuffs,
            "def_debuff_pressure": round(
                aps * debuffs["def_debuff"]["attack_share"]
                * debuffs["def_debuff"]["percent_per_hit"] / 100.0
                * debuffs["def_debuff"]["seconds"], 5),
            "resistances": {t: round(avg(lambda c, t=t: c["res"].get(t, 0.0)), 1)
                            for t in sorted(res_types)},
            "mez": sorted({m for _r, c in crits for m in c["mez"]}),
        }
    return out


def def_debuff_pressure(group):
    """One group's -Defense landed per critter per second at a 100% hit chance
    (attacks/s x share carrying it x fraction per hit x seconds it lasts)."""
    return group["def_debuff_pressure"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    revision = (_get("index.json", args.refresh) or {}).get("revision")
    names = _get("entity_names.json", args.refresh) or []
    keys = candidates(names)
    print(f"{len(keys)} candidate entities", flush=True)
    entities = _fetch_all([f"entities/{k}.json" for k in keys], args.refresh)
    absent = sorted(k for k, e in entities.items() if e is None)
    print(f"{len(keys) - len(absent)} of {len(keys)} expected entity records read", flush=True)
    if absent:            # every candidate comes from the host's own entity index
        print(f"FAIL: {len(absent)} indexed entities are unreadable: {absent[:10]}")
        return 1
    members = [m for m in (standard(e) for e in entities.values()) if m]
    print(f"{len(members)} standard level-50 enemies", flush=True)
    classes = sorted({k for _g, _r, k, _n in members if k})
    raw_tables = _fetch_all([f"tables/{k}.json" for k in classes], args.refresh)
    class_tables = {k: {n.lower(): v for n, v in ((raw_tables[f"tables/{k}.json"] or {})
                                                  .get("named_tables") or {}).items()}
                    for k in classes}
    read = sum(1 for v in class_tables.values() if v)
    print(f"{read} of {len(classes)} expected class tables read")
    if read < len(classes):
        print(f"FAIL: class tables unread: {[k for k, v in class_tables.items() if not v]}")
        return 1
    wanted = sorted({n for _g, _r, _k, ns in members for n in ns})
    fetched = _fetch_all([power_path(n) for n in wanted], args.refresh)
    powers = {n: fetched[power_path(n)] for n in wanted}
    missing = [n for n, p in powers.items() if p is None]
    print(f"{len(wanted) - len(missing)} of {len(wanted)} expected power records read", flush=True)
    if missing:
        print(f"FAIL: power records unread: {missing[:10]}")
        return 1
    groups = compile_groups(members, powers, class_tables)
    vals = list(groups.values())
    mean = lambda f: round(sum(f(g) for g in vals) / len(vals), 4) if vals else 0.0  # noqa: E731
    # The rating cascade's inputs, as the MEAN OF EACH GROUP'S OWN product (a
    # product of separate means would misstate groups whose share and duration
    # pull opposite ways):
    #   def_debuff_pressure  -Defense (fraction x seconds) landed per critter per
    #                        second at a 100% hit chance = attacks/s x share x per hit x seconds
    #   def_debuff_hit_rate  attacks/s that carry -Defense, per critter
    all_groups = {"def_debuff_pressure": mean(def_debuff_pressure),
                  "def_debuff_hit_rate": mean(lambda g: g["attacks_per_second_per_critter"]
                                              * g["def_debuff"]["attack_share"]),
                  "groups": len(vals),
                  "groups_landing_def_debuff": sum(1 for g in vals if def_debuff_pressure(g) > 0)}
    out = {"source": "City of Data (cod.uberguy.net), the game's own critter records",
           "all_groups_mean": all_groups,
           "revision": revision, "fetched": datetime.date.today().isoformat(),
           "method": __doc__.split("Polite by design")[0].strip(),
           "groups": groups, "unread_powers": len(missing),
           "spawn_rank_weights": SPAWN_RANK_WEIGHTS}
    data = (json.dumps(out, indent=1, sort_keys=True) + "\n").encode("utf-8")
    with open(OUT, "wb") as f:
        f.write(data)
    print(f"wrote data/critter_groups.json: {len(groups)} groups")


if __name__ == "__main__":
    sys.exit(main())
