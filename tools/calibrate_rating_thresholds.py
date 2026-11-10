"""Write data/rating_thresholds.json: the fixed starting numbers for the M4
S-F ratings (server/build_ratings.py).

Owner's ruling (2026-11-10): start with FIXED thresholds, use the shipped
champion builds as GUIDELINES, move the numbers as more builds come in. The
champions are not the comparison population; they are optimized itrial
builds, so their quantiles are a yardstick, not a percentile claim.

Method (stated in the file): a deterministic, archetype-stratified sample of
champion contexts is rebuilt AS SERVED (tools/evaluate_first.evaluate_picks:
the banked slotting layer, else the certification pipeline's re-solve), then
evaluated at the rating scenario. For each category the cut points are the
sample's quantiles (S >= p90, A >= p70, B >= p50, C >= p30, D >= p10). For a
capability category (control, buffs, debuffs, heals) only champions that
HAVE it set the cuts; absence is graded None, not F.

Hand edits are allowed and expected; bump `version` when you make one.
Usage: python tools/calibrate_rating_thresholds.py [--per-archetype N]
"""
import argparse
import datetime
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "server")]

import build_evaluation  # noqa: E402
import build_ratings  # noqa: E402
import evaluate_first  # noqa: E402
import first_principles  # noqa: E402
import server as srv  # noqa: E402

QUANTILES = {"S": 0.90, "A": 0.70, "B": 0.50, "C": 0.30, "D": 0.10}


def quantile(sorted_vals, q):
    """Linear-interpolated quantile of an ascending list."""
    if not sorted_vals:
        return None
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def sample_keys(champions, per_archetype):
    """Every k-th itrial context per archetype, in sorted order: deterministic."""
    by_at = defaultdict(list)
    for key in sorted(champions):
        parts = key.split("|")
        if len(parts) >= 4 and parts[3] == "itrial":
            by_at[parts[0]].append(key)
    keys = []
    for at in sorted(by_at):
        pool = by_at[at]
        step = max(1, len(pool) // per_archetype)
        keys += pool[::step][:per_archetype]
    return keys


def served_build(key, entry):
    at, prim, sec, content = key.split("|")[:4]
    role = (srv.ai_build.CONTENT_PRESETS.get(content or "", {}).get("default_role")
            or srv._AT_DEFAULT_ROLE.get(at, "damage"))
    solved = []
    score, _dt = evaluate_first.evaluate_picks(at, prim, sec, content, entry["picks"], role,
                                               slotting=entry.get("slotting"), solved_out=solved)
    if score is None or not solved:
        return None
    return {"archetype": at, "primary": prim, "secondary": sec, "powers": solved[0]}


def evaluate(build):
    at = srv.ARCH_BY_NAME[build["archetype"]]
    res_cap = round(at["res_cap"] * 100, 1)
    ctx = srv._stat_ctx(build["archetype"])
    return build_evaluation.evaluate(
        build, build_evaluation.DEFAULT_SCENARIO, ctx=ctx, set_bonuses=srv.SET_BONUSES,
        res_cap=res_cap, archetype_record=at, db_name=srv.DB_NAME,
        db_version=srv.DB_VERSION, app_version=srv.APP_VERSION,
        prepare=lambda b: srv._prepare_incarnate_fields(b, ctx, res_cap),
        powers_by_set=srv.POWERS, power_help=srv.POWER_HELP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-archetype", type=int, default=10)
    args = ap.parse_args()
    champions = json.load(open(os.path.join(ROOT, "benchmarks", "champions.json"), encoding="utf-8"))
    keys = sample_keys(champions, args.per_archetype)
    values = defaultdict(list)
    used, skipped, fingerprint = [], [], None
    for i, key in enumerate(keys, 1):
        build = served_build(key, champions[key])
        if not build:
            skipped.append(key)
            continue
        ev = evaluate(build)
        fingerprint = ev["versions"]["scenario_fingerprint"]
        offense_ok = ev["confidence"]["offense_complete"]
        for cat, value in build_ratings.measure(ev).items():
            kind = build_ratings.CATEGORIES[cat][3]
            if value is None or (kind == "offense" and not offense_ok):
                continue
            if kind in ("capability", "pets") and value <= 0:
                continue
            values[cat].append(value)
        used.append(key)
        print(f"[{i}/{len(keys)}] {key}", flush=True)
    categories = {}
    for cat in build_ratings.CATEGORIES:
        vals = sorted(values.get(cat, []))
        cuts = {g: round(quantile(vals, q), 3) for g, q in QUANTILES.items()} if len(vals) >= 5 else None
        categories[cat] = {"cuts": cuts, "sample_size": len(vals)}
    out = {
        "version": 1,
        "created": datetime.date.today().isoformat(),
        "scenario": build_evaluation.DEFAULT_SCENARIO,
        "scenario_fingerprint": fingerprint,
        "model_version": first_principles.MODEL_VERSION,
        "database_version": srv.DB_VERSION,
        "method": ("PROVISIONAL fixed numbers (owner, 2026-11-10). Cut points = quantiles of "
                   "an archetype-stratified sample of shipped itrial champions, rebuilt as "
                   "served and evaluated at the rating scenario: S>=p90 A>=p70 B>=p50 "
                   "C>=p30 D>=p10, else F. Champions are a guideline, NOT the comparison "
                   "population. Capability categories are cut from champions that have "
                   "the capability. Edit by hand and bump version as builds come in."),
        "sample": {"contexts": len(used), "skipped": skipped, "per_archetype": args.per_archetype},
        "categories": categories,
    }
    path = os.path.join(ROOT, "data", "rating_thresholds.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(f"wrote data/rating_thresholds.json: {len(used)} contexts, {len(skipped)} skipped")


if __name__ == "__main__":
    main()
