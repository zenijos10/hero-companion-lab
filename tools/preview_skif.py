"""Read-only, offline Sidekick v5 power identity inspection; never mutates saves."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from sidekick_preview import PreviewContractError, preview_build
from sidekick_enhancements import EnhancementContractError
from sidekick_reconstruct import reconstruct_build
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
    return import_catalog.build_sidekick_piece_lookups(sets, commons)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview Sidekick SKIF v5 IDs against Hero Companion")
    parser.add_argument("skif", type=Path)
    parser.add_argument("--sidekick-contract", type=Path, required=True,
                        help="Local Sidekick contract/homecoming folder; no network access")
    parser.add_argument("--reconstruct", action="store_true",
                        help="Fail-closed native build structure; no editor/save mutation")
    parser.add_argument("--default-io-level", type=int,
                        help="Explicit Sidekick session IO level when a crafted IO omits its level")
    args = parser.parse_args(argv)

    try:
        document = args.skif.read_text(encoding="utf-8")
        with (ROOT / "data" / "powers.json").open(encoding="utf-8") as handle:
            powers = json.load(handle)
        by_full = {p["full_name"]: p for group in powers.values() for p in group}
        catalog = _enhancement_lookups()
        if args.reconstruct:
            with (ROOT / "data" / "powersets.json").open(encoding="utf-8") as handle:
                powersets = json.load(handle)
            with (ROOT / "data" / "incarnates.json").open(encoding="utf-8") as handle:
                incarnates = json.load(handle)
            report = reconstruct_build(
                document, by_full, powersets, args.sidekick_contract, catalog,
                default_io_level=args.default_io_level, incarnate_catalog=incarnates)
        else:
            report = preview_build(document, by_full, args.sidekick_contract,
                                   hero_piece_by_uid=catalog)
    except (OSError, ValueError, SkifFormatError, PreviewContractError,
            EnhancementContractError, KeyError) as exc:
        print(f"Sidekick preview refused: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return (0 if report["ok"] else 2) if args.reconstruct else (
        2 if report["unresolved"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
