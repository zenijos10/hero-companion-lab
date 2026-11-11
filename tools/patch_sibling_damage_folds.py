"""Fold a patch power's damage onto a player record that has none, from its
proven SIBLINGS (backlog 2b, owner's pick 2026-11-11).

THE CASE: Fire Manipulation's Burn (Blaster) carries NO effect rows. Its damage
lives on the pseudo-pet patch `Pets.Burn.Burn` (an Auto that pulses every 0.8 s),
and the engine's pet channel cannot price a pulsing Auto (no cast time, no
recharge), so the power was credited zero damage. Every Fiery Aura Burn
(Brute, Scrapper, Sentinel, Stalker, Tanker) summons THE SAME `Pets.Burn` patch
with the same cast time, recharge, radius, target cap and area, and each carries
the patch's damage FOLDED onto its own record (Fire 1.44, Melee_Damage, PvE) -
the data's established convention for patch summoners.

THE RULE (generic, no hand list): a pickable player record with no damage rows
whose `pet_powersets` (none under Redirects.*, which the engine prices by its
redirect channel) are shared by >= 2 SIBLING records that
  * carry damage rows, and
  * match it on power_type, cast_time, base_recharge, radius and max_targets
    (the caster half of the mechanic; effect_area is NOT compared - the
    siblings themselves differ on it, 1 vs 2, while carrying the identical
    fold, so it does not decide the damage),
takes the damage rows COMMON TO EVERY sibling (whole-row equality, probability
> 0). A row only some siblings carry (the Brute/Tanker extra row, probability
0.0 = unset) is not taken. Siblings that disagree on the caster half refuse the
fold. The rows are priced by the engine at the CASTER's archetype column, exactly
as the siblings' are, and marked `sibling_fold` with the sibling list.

Two signals, per the evidence rule: the shared pet record itself (the same
patch) and the siblings' agreeing fold. The patch's lifetime is not in our data;
the fold carries it implicitly (1.44 = 0.06 per pulse x 24 pulses of 0.8 s).

⚠ powers.json is ONE LINE written by plain json.dumps (default separators,
ASCII). Read binary, build all bytes, then write; a round trip is byte-identical.
Usage:  python tools/patch_sibling_damage_folds.py [--check]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POWERS = os.path.join(ROOT, "data", "powers.json")

MARK = "sibling_fold"
NOT_PLAYER = ("Incarnate", "Pets", "Villain_Pets", "Mastermind_Pets",
              "Kheldian_Pets", "Temporary_Powers", "Inherent", "Redirects")
CASTER_HALF = ("power_type", "cast_time", "base_recharge", "radius", "max_targets")
# The records this rule is known to reach (coverage denominator: the rule must
# reach exactly these; a new reach or a lost one is a data change to look at).
EXPECTED = {"Blaster_Support.Fire_Manipulation.Burn"}


def dumps(data):
    return json.dumps(data).encode("utf-8")


def _row_key(row):
    return json.dumps({k: v for k, v in row.items() if k != MARK}, sort_keys=True)


def strip(data):
    """Remove this tool's own rows and restore what it changed (idempotence)."""
    for lst in data.values():
        for p in lst:
            fx = p.get("damage_effects")
            if fx and any(r.get(MARK) for r in fx):
                p["damage_effects"] = [r for r in fx if not r.get(MARK)]
            if "is_attack_was" in p:
                p["is_attack"] = p.pop("is_attack_was")
            p.pop("sibling_fold_from", None)


def plan(data):
    records = [p for lst in data.values() for p in lst]
    by_pets = {}
    for p in records:
        key = tuple(p.get("pet_powersets") or [])
        if key and p.get("damage_effects"):
            by_pets.setdefault(key, []).append(p)
    out = []
    for p in records:
        fn = p["full_name"]
        pets = tuple(p.get("pet_powersets") or [])
        if (p.get("damage_effects") or not pets or (p.get("level_available") or 0) < 1
                or fn.split(".")[0] in NOT_PLAYER
                or any(ps.startswith("Redirects.") for ps in pets)):
            continue
        sibs = [s for s in by_pets.get(pets, []) if s["full_name"] != fn]
        if len(sibs) < 2:
            continue
        mine = tuple(p.get(k) for k in CASTER_HALF)
        if any(tuple(s.get(k) for k in CASTER_HALF) != mine for s in sibs):
            out.append((fn, None, sibs, "REFUSED: siblings differ on the caster half"))
            continue
        common = None
        for s in sibs:
            keys = {_row_key(r) for r in s["damage_effects"] if (r.get("probability") or 0) > 0}
            common = keys if common is None else common & keys
        rows = [json.loads(k) for k in sorted(common or [])]
        if not rows:
            out.append((fn, None, sibs, "REFUSED: no damage row common to every sibling"))
            continue
        out.append((fn, rows, sibs, "ok"))
    return out


def main():
    check_only = "--check" in sys.argv
    raw = open(POWERS, "rb").read()
    data = json.loads(raw.decode("utf-8"))
    if dumps(data) != raw:
        print("FAIL: powers.json does not round-trip byte-identically; refusing")
        sys.exit(2)
    strip(data)
    baseline = dumps(data)
    by_full = {p["full_name"]: p for lst in data.values() for p in lst}

    folds = plan(data)
    reached = {fn for fn, rows, _s, _w in folds if rows}
    for fn, rows, sibs, why in folds:
        print(f"{fn}: {why}; siblings {', '.join(s['full_name'] for s in sibs)}")
        if not rows:
            continue
        p = by_full[fn]
        for r in rows:
            print(f"    + {r['effect']} {r['damage_type']} scale {r['scale']} "
                  f"{r['modifier_table']} pv_mode {r.get('pv_mode')}")
        if check_only:
            continue
        p["damage_effects"] = [dict(r, **{MARK: True}) for r in rows]
        p["sibling_fold_from"] = sorted(s["full_name"] for s in sibs)
        if all(s.get("is_attack") for s in sibs) and not p.get("is_attack"):
            p["is_attack_was"] = p.get("is_attack")
            p["is_attack"] = True

    print(f"{len(reached & EXPECTED)} of {len(EXPECTED)} expected records folded")
    if reached != EXPECTED:
        print(f"FAIL: the rule reached {sorted(reached)}, expected {sorted(EXPECTED)}")
        sys.exit(1)
    if check_only:
        return

    out = dumps(data)
    probe = json.loads(out.decode("utf-8"))
    strip(probe)
    if dumps(probe) != baseline:
        print("INVARIANCE FAILED: stripping the fold does not reproduce the baseline")
        sys.exit(2)
    print("invariance: stripping the fold reproduces the baseline exactly")
    open(POWERS, "wb").write(out)
    print(f"wrote {POWERS} ({len(out):,} bytes, was {len(raw):,})")


if __name__ == "__main__":
    main()
