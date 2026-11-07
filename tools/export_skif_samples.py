"""Write Hero Companion's .skif exports of real Sidekick builds, for Sidekick to re-open.

Each sample is a real published Sidekick build imported into Hero Companion and
exported again. CI hands the files to tools/sidekick_verify (Sidekick's own
decoder). Usage: python tools/export_skif_samples.py <out_dir>
Requires the pinned upstream checkout in _sidekick_contract_fixture.
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "tools")]
from preview_skif import _enhancement_lookups
from sidekick_reconstruct import reconstruct_build
from skif_export import dumps, export_build

UPSTREAM = ROOT / "_sidekick_contract_fixture"
CONTRACT = UPSTREAM / "contract/homecoming"


def _load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def v5_from_v4(name, buckets=("primary", "secondary", "pools", "inherents")):
    """Sidekick's v4 sample `name` in v5 shape. v5 drops each power's "name",
    writes the archetype as its id, and splits v4's slot "boost" into an IO's
    "booster" and a special's "relativeLevel"; nothing else is changed."""
    old = json.loads((UPSTREAM / f"fixtures/skif/v4/{name}.skif")
                     .read_text(encoding="utf-8"))["build"]

    def slot(sl):
        if not sl or "boost" not in sl:
            return sl
        out = {k: v for k, v in sl.items() if k != "boost"}
        out["relativeLevel" if sl["type"] in ("special", "origin") else "booster"] = sl["boost"]
        return out

    def power(p):
        out = {k: v for k, v in p.items() if k in ("internalName", "level")}
        out["slots"] = [slot(sl) for sl in p["slots"]]
        if p.get("isActive"):           # Sidekick writes the switch only when on
            out["isActive"] = True
        return out

    def selection(sel):
        return {"id": sel["id"], "powers": [power(p) for p in sel["powers"]]}
    build = {"dataset": "homecoming", "archetype": old["archetype"]["id"],
             "level": old["level"], "name": old.get("name") or name}
    for bucket in buckets:
        value = old.get(bucket)
        if bucket == "pools":
            build["pools"] = [selection(p) for p in value or []]
        elif bucket == "inherents":
            build["inherents"] = [power(p) for p in value or []]
        elif value:
            build[bucket] = selection(value)
    return {"version": 5, "build": build}


def sample_documents():
    published = json.loads((UPSTREAM / "fixtures/skif/v5/rb5d_browser_pass.skif")
                           .read_text(encoding="utf-8"))
    controller = json.loads((UPSTREAM / "fixtures/skif/v4/homecoming-troller.skif")
                            .read_text(encoding="utf-8"))
    rich = copy.deepcopy(published)
    rich["build"]["inherents"] = [{k: v for k, v in p.items() if k != "name"}
                                  for p in controller["build"]["inherents"]]
    rich["build"]["incarnates"] = {
        "alpha": {"power": "Incarnate.Alpha.Agility_Core_Paragon", "active": True},
        "destiny": {"power": "Incarnate.Destiny.Ageless_Core_Epiphany", "active": False}}
    pooled = copy.deepcopy(published)
    pooled["build"]["pools"] = [{"id": "leaping", "powers": [
        {"internalName": "Combat_Jumping", "level": 4, "slots": [None]}]}]
    pooled["build"]["epicPool"] = {"id": "melee_psionic_mastery", "powers": [
        {"internalName": "Mental_Blast", "level": 35, "slots": [None]}]}
    return {"published": published, "inherents-incarnates": rich,
            "pool-renamed-epic": pooled,
            # Four pools, real inherents, and Artillery (our Crafted_Shrapnel_*).
            "controller-four-pools": v5_from_v4("homecoming-troller"),
            # Form attacks travel inside their powerset (ours: Inherent.Inherent).
            "peacebringer-forms": v5_from_v4("homecoming-kheldian"),
            # Base set named, each Crab Spider pick names its branch.
            "arachnos-crab-branch": v5_from_v4("homcoming-level-up-arachnos"),
            # A D-Sync: Sidekick's DSync_* is our Dsync_*.
            "blaster-dsync": v5_from_v4("sojourner_1784025393210"),
            # Sidekick's slot-by-level history, passed back verbatim.
            "controller-slot-history": _with_slot_order("homecoming-troller"),
            # Its accolades, as Sidekick's reader stores them (lower-cased).
            "arachnos-accolades": _with_accolades("homcoming-level-up-arachnos"),
            # Per-proc controls, re-addressed the way Sidekick's v5 reader stores them.
            "scrapper-proc-settings": proc_settings_sample()}


def proc_settings_sample():
    """The "proc test" sample with its two overrides re-addressed the way
    Sidekick's v5 reader stores them ("<powerset>:<power>:<slot index>"), plus a
    disabled category. One copy, shared by the tests."""
    doc = v5_from_v4("proc test", ("primary", "secondary", "pools", "inherents", "epicPool"))
    doc["build"]["procOverrides"] = {
        "body_mastery:Physical_Perfection:5": {"enabled": True, "mode": "hp", "hpPct": 50},
        "scrapper/energy-aura:Kinetic_Shield:0": {"enabled": False, "mode": "hp", "hpPct": 60}}
    doc["build"]["disabledProcCategories"] = ["Defense"]
    return doc


def _with_accolades(name):
    doc = v5_from_v4(name)
    doc["build"]["accolades"] = [a["id"] for a in json.loads(
        (UPSTREAM / f"fixtures/skif/v4/{name}.skif").read_text(encoding="utf-8")
    )["build"]["accolades"]]
    return doc


def _with_slot_order(name):
    doc = v5_from_v4(name)
    doc["build"]["slotOrder"] = json.loads(
        (UPSTREAM / f"fixtures/skif/v4/{name}.skif").read_text(encoding="utf-8")
    )["build"]["slotOrder"]
    return doc


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    powers = _load("data/powers.json")
    hero = {p["full_name"]: p for group in powers.values() for p in group}
    powersets = _load("data/powersets.json")
    incarnates = _load("data/incarnates.json")
    pieces = _enhancement_lookups()
    for name, doc in sample_documents().items():
        imported = reconstruct_build(doc, hero, powersets, CONTRACT, pieces,
                                     incarnate_catalog=incarnates, default_io_level=50)
        if not imported["ok"]:
            raise SystemExit(f"{name}: import refused: {imported['issues'][:3]}")
        exported = export_build(imported["build"], hero, CONTRACT, powersets, name=name,
                                hero_piece_by_uid=pieces)
        if not exported["ok"]:
            raise SystemExit(f"{name}: export refused: {exported['issues'][:3]}")
        (out / f"{name}.skif").write_text(dumps(exported["skif"]), encoding="utf-8")
        print(f"wrote {name}.skif")


if __name__ == "__main__":
    main(sys.argv[1])
