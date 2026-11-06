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
            "pool-renamed-epic": pooled}


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
                                     incarnate_catalog=incarnates)
        if not imported["ok"]:
            raise SystemExit(f"{name}: import refused: {imported['issues'][:3]}")
        exported = export_build(imported["build"], hero, CONTRACT, powersets, name=name)
        if not exported["ok"]:
            raise SystemExit(f"{name}: export refused: {exported['issues'][:3]}")
        (out / f"{name}.skif").write_text(dumps(exported["skif"]), encoding="utf-8")
        print(f"wrote {name}.skif")


if __name__ == "__main__":
    main(sys.argv[1])
