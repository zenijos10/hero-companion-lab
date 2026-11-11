"""Split each sniper's two EXCLUSIVE damage states, so a shot is not credited both
(owner's ruling 2026-11-11: "fix the Ranged Shot problem", scope = all snipers).

THE GAME'S RULE, in each record's own help: "If you are engaged in battle this
attack becomes instant-cast. If you are not engaged, it will do bonus damage."
Our records carry BOTH states as ordinary PvE damage rows - the out-of-combat
snipe (scale 4.5, or Energy Blast's 1.5 Energy + 3.0 Smashing split) and the
in-combat quick snipe (scale 2.28, sometimes split by nMag across types) - and
the engine sums every row, crediting one shot about 6.8 instead of one state.

TWO SIGNALS that the states are exclusive, not a base plus a bonus:
  * the help sentence above (engaged -> quick; not engaged -> bonus);
  * the Blaster Archery Ranged Shot splits them into two separate records,
    Redirects.Blaster_Archery.Ranged_Shot_Normal (4.5 alone) and _Quick: the
    out-of-combat shot carries 4.5 on its own, never 4.5 + 2.28.

WHAT IT DOES: for every record whose help states the rule and whose PvE rows
hold BOTH groups, the out-of-combat rows move from `damage_effects` to
`damage_effects_out_of_combat` (kept, never deleted; nothing prices that key).
The scenarios are sustained fights, where you are engaged, so the in-combat
state is what a cycled chain fires. Every other row stays: DoTs, the
Penetrating Ray riders, the tiny expression-carrying rows (2181.8 x 1e-5, whose
expression our data lacks), the PvP rows and the zero-probability copies.

SECOND PASS - a state our data is MISSING. Some records hold only the
out-of-combat group: Defender Proton Volley, and the Blaster versions, which
split the states into redirect twins (Redirects.<Set>.<Power>_Normal /_Quick)
whose Quick twin carries only a PvP row. For each, the in-combat rows are taken
from a SIBLING - the same power on another archetype, split in the first pass -
and only when that sibling's out-of-combat rows are IDENTICAL to the record's
(two signals: the same out-of-combat state proves the same mechanics; the
sibling supplies the in-combat state). The folded rows are marked
`snipe_state_fold`. The Normal twin's out-of-combat rows move aside like any
other; the pet channel then chains the Quick twin (its own, shorter cast time).

NOT IN SCOPE, stated: Dominator assault snipers carry a different pair (4.5 and
3.56 x 0.75) and Stalker epics carry crit rows; neither matches this rule and
both are recorded in KNOWN-GAPS. Cast times are left as they are.

Coverage: the rule must reach exactly EXPECTED_COUNT records.
⚠ powers.json is ONE LINE of plain json.dumps; a round trip must be byte-identical.
Usage:  python tools/patch_snipe_states.py [--check]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POWERS = os.path.join(ROOT, "data", "powers.json")
HELP = os.path.join(ROOT, "data", "power_help.json")

MOVED = "damage_effects_out_of_combat"
MOVED_AT = "damage_effects_out_of_combat_at"   # their original positions, for restoring
OUT_OF_COMBAT_TOTAL = 4.5      # the full-strength snipe
IN_COMBAT = 2.28               # the quick snipe
EXPECTED_COUNT = 24            # first pass: records holding both states
EXPECTED_FOLDS = {             # second pass: record or Quick twin -> folded from
    "Defender_Ranged.Radiation_Blast.Proton_Volley",
    "Redirects.Blaster_Archery.Ranged_Shot_Quick",
    "Redirects.Blaster_Assault_Rifle.Sniper_Rifle_Quick",
    "Redirects.Blaster_Radiation_Blast.Proton_Volley_Quick",
}
FOLD = "snipe_state_fold"
_EPS = 1e-9


def dumps(data):
    return json.dumps(data).encode("utf-8")


def states_the_rule(help_entry):
    text = help_entry[1] if isinstance(help_entry, (list, tuple)) and len(help_entry) > 1 else ""
    text = (text or "").lower()
    return "engaged" in text and "instant-cast" in text


def _pve(row):
    return row.get("pv_mode", 0) != 2 and (row.get("probability") or 0) > 0


def split(rec):
    """(out_of_combat_rows, kept_rows) when the record holds both groups, else None."""
    rows = rec.get("damage_effects") or []
    pve = [r for r in rows if _pve(r)]
    in_combat = [r for r in pve if abs(r["scale"] - IN_COMBAT) < _EPS]
    # k = the in-combat state's total nMag: 1 for a single shot, 0.25 for Proton
    # Volley's per-bolt rows; the out-of-combat state is the same fraction of 4.5
    k = sum(r.get("nmag", 1.0) for r in in_combat)
    if k <= 0:
        return None                       # no in-combat state in our data
    target = OUT_OF_COMBAT_TOTAL * k
    full = [r for r in pve if abs(r.get("nmag", 1.0) - 1.0) < _EPS
            and abs(r["scale"] - IN_COMBAT) > _EPS]
    single = [r for r in full if abs(r["scale"] - target) < 1e-6]
    if len(single) == 1:
        out = single
    else:
        # a type split (Sniper Blast: 1.5 Smashing + 3.0 Energy): the full-strength
        # rows of distinct damage types that together make the snipe
        out = [r for r in full if r["scale"] < target]
        if (not out or len({r["damage_type"] for r in out}) != len(out)
                or abs(sum(r["scale"] for r in out) - target) > 1e-6):
            return None
    ids = {id(r) for r in out}
    return out, [r for r in rows if id(r) not in ids]


def strip(data):
    """Put moved rows back and drop folded ones (idempotence and invariance)."""
    for lst in data.values():
        for p in lst:
            if any(r.get(FOLD) for r in p.get("damage_effects") or []):
                p["damage_effects"] = [r for r in p["damage_effects"] if not r.get(FOLD)]
            if MOVED in p:
                moved = p.pop(MOVED)
                at = p.pop(MOVED_AT)
                rows = list(p.get("damage_effects") or [])
                for i, r in sorted(zip(at, moved)):
                    rows.insert(i, r)
                p["damage_effects"] = rows


def _move(rec, out):
    """Move `out` (rows of rec's damage_effects) aside, remembering positions."""
    ids = {id(r) for r in out}
    rows = rec["damage_effects"]
    rec[MOVED_AT] = [i for i, r in enumerate(rows) if id(r) in ids]
    rec[MOVED] = [r for r in rows if id(r) in ids]
    rec["damage_effects"] = [r for r in rows if id(r) not in ids]


def _sig(rows):
    return sorted(json.dumps({k: r.get(k) for k in ("effect", "damage_type", "scale", "nmag",
                                                   "modifier_table", "pv_mode")},
                             sort_keys=True) for r in rows)


def _leaf(full_name):
    return full_name.rsplit(".", 1)[-1]


def second_pass(data, help_, split_records, check_only):
    """Fold the missing in-combat state from a split sibling. Returns the set of
    records folded and the reasons any candidate was refused."""
    by_full = {p["full_name"]: p for lst in data.values() for p in lst}
    # split siblings by power leaf: (out-of-combat signature, in-combat rows)
    sibs = {}
    for fn, out, kept in split_records:
        inc = [r for r in kept if _pve(r) and abs(r["scale"] - IN_COMBAT) < _EPS]
        sibs.setdefault(_leaf(fn), []).append((fn, _sig(out), inc))
    candidates = []                   # (target to fold into, record whose rows move, leaf)
    for lst in data.values():
        for p in lst:
            fn = p["full_name"]
            if not states_the_rule(help_.get(fn)) or MOVED in p:
                continue
            pve = [r for r in p.get("damage_effects") or [] if _pve(r)]
            if pve and not any(abs(r["scale"] - IN_COMBAT) < _EPS for r in pve):
                candidates.append((p, p, _leaf(fn)))
            for ps in p.get("pet_powersets") or []:
                if not ps.startswith("Redirects."):
                    continue
                normal = by_full.get(f"{ps}.{_leaf(fn)}_Normal")
                quick = by_full.get(f"{ps}.{_leaf(fn)}_Quick")
                if normal and quick and not any(_pve(r) for r in quick.get("damage_effects") or []):
                    candidates.append((quick, normal, _leaf(fn)))
    folded, refused = set(), []
    for target, source, leaf in candidates:
        out = [r for r in source.get("damage_effects") or [] if _pve(r)]
        match = [s for s in sibs.get(leaf, []) if s[1] == _sig(out) and s[2]]
        signatures = {json.dumps(_sig(s[2])) for s in match}
        if not match or len(signatures) != 1:
            refused.append((target["full_name"], "no split sibling with the identical "
                            "out-of-combat state" if not match else "siblings disagree"))
            continue
        inc = match[0][2]
        folded.add(target["full_name"])
        print(f"{target['full_name']}: in-combat "
              + " + ".join(f"{r['scale']}x{r.get('nmag', 1.0)} {r['damage_type']}" for r in inc)
              + f" folded from {', '.join(s[0] for s in match)}; out-of-combat moved from "
              + source["full_name"])
        if check_only:
            continue
        _move(source, out)
        target["damage_effects"] = (target.get("damage_effects") or []) + [
            dict(r, **{FOLD: [s[0] for s in match]}) for r in inc]
    return folded, refused


def main():
    check_only = "--check" in sys.argv
    raw = open(POWERS, "rb").read()
    data = json.loads(raw.decode("utf-8"))
    if dumps(data) != raw:
        print("FAIL: powers.json does not round-trip byte-identically; refusing")
        sys.exit(2)
    strip(data)
    baseline = dumps(data)
    help_ = json.load(open(HELP, encoding="utf-8"))

    rule_records = touched = 0
    unmatched = []
    split_records = []
    for lst in data.values():
        for p in lst:
            if not states_the_rule(help_.get(p["full_name"])) or not p.get("damage_effects"):
                continue
            rule_records += 1
            got = split(p)
            if not got:
                unmatched.append(p["full_name"])
                continue
            out, kept = got
            touched += 1
            split_records.append((p["full_name"], out, kept))
            print(f"{p['full_name']}: out-of-combat "
                  + " + ".join(f"{r['scale']} {r['damage_type']}" for r in out)
                  + f" moved; in-combat {IN_COMBAT} kept")
            if check_only:
                continue
            _move(p, out)

    print(f"{touched} of {EXPECTED_COUNT} expected sniper records split "
          f"({rule_records} records state the rule and carry damage)")
    for fn in unmatched:
        if fn not in EXPECTED_FOLDS:
            print(f"  STATED EXCLUSION, the rule is stated but the two-state pair is not "
                  f"this shape: {fn}")
    folded, refused = second_pass(data, help_, split_records, check_only)
    print(f"{len(folded & EXPECTED_FOLDS)} of {len(EXPECTED_FOLDS)} expected missing "
          f"in-combat states folded from a split sibling")
    for fn, why in refused:
        print(f"  STATED EXCLUSION, not folded: {fn} - {why}")
    if touched != EXPECTED_COUNT or folded != EXPECTED_FOLDS:
        print("FAIL: coverage moved; look before re-pinning EXPECTED_COUNT / EXPECTED_FOLDS")
        sys.exit(1)
    if check_only:
        return
    out_bytes = dumps(data)
    probe = json.loads(out_bytes.decode("utf-8"))
    strip(probe)
    if dumps(probe) != baseline:
        print("INVARIANCE FAILED: restoring the moved rows does not reproduce the baseline")
        sys.exit(2)
    print("invariance: restoring the moved rows reproduces the baseline exactly")
    open(POWERS, "wb").write(out_bytes)
    print(f"wrote {POWERS} ({len(out_bytes):,} bytes, was {len(raw):,})")


if __name__ == "__main__":
    main()
