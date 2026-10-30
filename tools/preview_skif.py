"""Read-only, offline Sidekick v5 power identity inspection; never mutates saves."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from sidekick_preview import PreviewContractError, preview_build
from sidekick_enhancements import EnhancementContractError
import import_catalog
from skif_document import SkifFormatError


def _enhancement_lookups():
    """HC's import identity lookup, built without loading the Flask server.

    Set pieces, special origins and the Crafted_/Attuned_ aliases come from the
    server's own builder (import_catalog), so this can never drift from what the
    app imports. Common IOs are added as plain uids: the server resolves them by
    a separate map, and they have no attuned form to alias.
    """
    with (ROOT / "data" / "enhancement_sets.json").open(encoding="utf-8") as stream:
        sets = json.load(stream)
    with (ROOT / "data" / "common_ios.json").open(encoding="utf-8") as stream:
        commons = json.load(stream)
    pieces, _ = import_catalog.build_piece_lookups(sets, commons)
    lookup = import_catalog.build_import_aliases(pieces)
    for entry in commons.get("common_ios", []):
        uid = entry.get("uid")
        if uid and uid not in lookup:
            lookup[uid] = {"piece_uid": uid, "piece_name": entry.get("name") or uid}
    return lookup


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview Sidekick SKIF v5 IDs against Hero Companion")
    parser.add_argument("skif", type=Path)
    parser.add_argument("--sidekick-contract", type=Path, required=True,
                        help="Local Sidekick contract/homecoming folder; no network access")
    args = parser.parse_args(argv)

    try:
        document = args.skif.read_text(encoding="utf-8")
        with (ROOT / "data" / "powers.json").open(encoding="utf-8") as handle:
            powers = json.load(handle)
        by_full = {p["full_name"]: p for group in powers.values() for p in group}
        report = preview_build(document, by_full, args.sidekick_contract,
                               hero_piece_by_uid=_enhancement_lookups())
    except (OSError, ValueError, SkifFormatError, PreviewContractError,
            EnhancementContractError, KeyError) as exc:
        print(f"Sidekick preview refused: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
