"""Conservative, read-only SKIF v5 -> Hero Companion power identity preview.

A Sidekick *contract directory* is supplied by the caller; no game data is
downloaded and no Sidekick Rust code runs. All resolution is grounded in its
manifest, powerset shard setPath and Mids name bridge, plus HC's shipped powers.
No partial result produced here is a playable imported build.
"""

import json
from pathlib import Path

from skif_document import load_document
from sidekick_enhancements import EnhancementResolver


class PreviewContractError(ValueError):
    """The supplied Homecoming contract is missing, unsafe, or inconsistent."""


def _read_json(path, description):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise PreviewContractError(f"{description}: {exc}") from exc


def _contract(root):
    root = Path(root).resolve()
    manifest = _read_json(root / "manifest.json", "Sidekick manifest")
    mids = _read_json(root / "mids-names.json", "Sidekick Mids name bridge")
    if not isinstance(manifest, dict) or manifest.get("dataset") != "homecoming":
        raise PreviewContractError("Sidekick contract must be Homecoming")
    if not isinstance(mids, dict) or any(
            not isinstance(mids.get(k), dict) for k in ("nameReverse", "nameMap")):
        raise PreviewContractError("Sidekick name bridge is missing name maps")
    shards = manifest.get("shards")
    if not isinstance(shards, list):
        raise PreviewContractError("Sidekick manifest has no shard list")
    paths = {}
    for entry in shards:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise PreviewContractError("Invalid shard entry")
        name = entry.get("path")
        if not isinstance(name, str) or not name:
            raise PreviewContractError(f"Missing shard path for {entry['id']}")
        target = (root / name).resolve()
        if not target.is_relative_to(root) or target == root:
            raise PreviewContractError(f"Unsafe shard path for {entry['id']}")
        if entry["id"] in paths:
            raise PreviewContractError(f"Duplicate shard id: {entry['id']}")
        paths[entry["id"]] = target
    return paths, mids


def _issue(reason, location, detail):
    return {"reason": reason, "location": location, "detail": str(detail)}


def _index_powers(powers_by_full):
    by_folded = {}
    for name in powers_by_full:
        by_folded.setdefault(name.casefold(), []).append(name)
    return by_folded


def _resolve_power(name, set_path, shard, mids, by_folded, where, issues):
    source_names = [p.get("internalName") for p in shard["powers"]
                    if isinstance(p, dict)]
    if source_names.count(name) != 1:
        issues.append(_issue("unknown_source_power", where, name))
        return None

    set_key = set_path.casefold()
    reverse = mids["nameReverse"].get(set_key, {})
    forward = mids["nameMap"].get(set_key, {})
    if not isinstance(reverse, dict) or not isinstance(forward, dict):
        raise PreviewContractError(f"Invalid name map for {set_path}")

    mapped = reverse.get(name.casefold())
    if mapped is None:
        claimed = forward.get(name.casefold())
        if claimed is not None and claimed.casefold() != name.casefold():
            issues.append(_issue("power_name_conflict", where, name))
            return None
        mapped = name
    if not isinstance(mapped, str) or not mapped:
        raise PreviewContractError(f"Invalid reverse name mapping for {where}")

    full = f"{set_path}.{mapped}"
    matches = by_folded.get(full.casefold(), [])
    if len(matches) != 1:
        issues.append(_issue("unknown_hero_power" if not matches else
                             "ambiguous_hero_power", where, full))
        return None
    return matches[0]


def preview_build(document, hero_powers_by_full, contract_root, hero_piece_by_uid=None):
    """Return verifiable power matches and unresolved facts, never an editable build.

    document: Sidekick v5 dict or JSON string.
    hero_powers_by_full: HC's POWER_BY_FULL mapping (or equivalent test mapping).
    contract_root: offline Sidekick contract/homecoming directory.
    hero_piece_by_uid: optional HC import lookup; if absent, enhancements
        remain explicitly unresolved. When present, all identities must be
        provable from Sidekick boost-index.json and HC's own import catalogue.
    """
    doc = load_document(document)
    build = doc["build"]
    if build["dataset"] != "homecoming":
        raise PreviewContractError("Only Homecoming builds can be previewed")
    if not isinstance(hero_powers_by_full, dict):
        raise PreviewContractError("Hero Companion power index must be a mapping")

    paths, mids = _contract(contract_root)
    hero_index = _index_powers(hero_powers_by_full)
    enhancement_bridge = (EnhancementResolver(contract_root, hero_piece_by_uid)
                          if hero_piece_by_uid is not None else None)
    issues = []
    resolved = []
    enhancements = []

    def visit(bucket, selection, position=None):
        if selection is None:
            return
        where = f"build.{bucket}" + (f"[{position}]" if position is not None else "")
        set_id = selection["id"]
        path = paths.get(set_id)
        if path is None:
            issues.append(_issue("unknown_source_set", where, set_id))
            return

        shard = _read_json(path, f"Sidekick shard {set_id}")
        if not isinstance(shard, dict) or shard.get("id") != set_id:
            issues.append(_issue("source_identity_mismatch", where, set_id))
            return
        set_path = shard.get("setPath")
        if not isinstance(set_path, str) or not set_path or not isinstance(shard.get("powers"), list):
            raise PreviewContractError(f"Malformed Sidekick shard: {set_id}")
        if shard.get("archetype") not in (None, build.get("archetype")):
            issues.append(_issue("source_archetype_mismatch", where, set_id))
            return
        if bucket in ("primary", "secondary") and shard.get("category") not in (None, bucket):
            issues.append(_issue("source_category_mismatch", where, set_id))
            return

        for i, power in enumerate(selection.get("powers", [])):
            location = f"{where}.powers[{i}]"
            name = power["internalName"]
            if power.get("powerset") and power["powerset"] != set_id:
                issues.append(_issue("cross_set_power_not_mapped", location, power["powerset"]))
                continue
            matched = _resolve_power(name, set_path, shard, mids, hero_index, location, issues)
            if matched is not None:
                resolved.append({
                    "location": location, "sidekick_set": set_id,
                    "sidekick_power": name, "hero_power": matched,
                    "level": power["level"], "slot_count": len(power["slots"]),
                })
            for j, slot in enumerate(power["slots"]):
                if slot is None:
                    continue
                slot_where = f"{location}.slots[{j}]"
                if enhancement_bridge is None:
                    issues.append(_issue("enhancement_not_mapped", slot_where, slot["type"]))
                    continue
                identity, problem = enhancement_bridge.resolve(
                    slot, character_origin=build.get("origin"))
                if problem:
                    issues.append(_issue(problem, slot_where, slot["type"]))
                else:
                    enhancements.append({"location": slot_where, **identity})
            for key in ("isActive", "activeSubPower"):
                if power.get(key):
                    issues.append(_issue("state_not_mapped", f"{location}.{key}", key))

    for bucket in ("primary", "secondary", "epicPool"):
        visit(bucket, build.get(bucket))
    for index, selection in enumerate(build.get("pools", [])):
        visit("pools", selection, index)

    for i, power in enumerate(build.get("inherents", [])):
        issues.append(_issue("inherent_not_mapped", f"build.inherents[{i}]",
                             power["internalName"]))
    # Not all of this data is reducible to Hero Companion's editor state yet.
    # Surface it explicitly even when all selected powers resolved.
    for key in ("incarnates", "slotOrder", "stances", "modes", "powerState",
                "procOverrides", "disabledProcCategories", "attackChains",
                "accolades", "origin"):
        if build.get(key):
            issues.append(_issue("state_not_mapped", f"build.{key}", key))

    return {
        "format": "skif-v5", "dataset": "homecoming",
        "name": build.get("name", ""), "resolved": resolved,
        "resolved_enhancements": enhancements,
        "unresolved": issues, "ready_for_import": False,
    }
