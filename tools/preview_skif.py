"""Read-only, offline Sidekick v5 power identity inspection; never mutates saves."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from sidekick_preview import PreviewContractError, preview_build
from skif_document import SkifFormatError


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
        report = preview_build(document, by_full, args.sidekick_contract)
    except (OSError, ValueError, SkifFormatError, PreviewContractError, KeyError) as exc:
        print(f"Sidekick preview refused: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
