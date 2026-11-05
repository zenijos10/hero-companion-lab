"""Fail-closed reconstruction of supported SKIF v5 builds into HC's native shape.

Power and enhancement identities must first be proven by sidekick_preview.
This is a *library conversion*, never a save, editor mutation, or claim that
the resulting build has passed Homecoming's complete slot/pick legality rules.

The original file is returned separately as source_skif for provenance. It
must not be mistaken for an export of later edits to the HC build.
"""

import copy
from pathlib import Path

from sidekick_preview import PreviewContractError, _contract, _read_json, preview_build
from skif_document import load_document


# The native HC editor cannot express these Sidekick state dimensions yet.
# Refuse *non-empty* values; empty state is equivalent to the reader's default.
_UNSUPPORTED = (
    "accolades", "incarnates", "slotOrder", "stances", "modes",
    "powerState", "procOverrides", "disabledProcCategories",
    "progress", "whatIfBuffs",
)
_KNOWN_BUILD = frozenset((
    "name", "dataset", "archetype", "origin", "level", "primary", "secondary",
    "pools", "epicPool", "attackChains", "inherents",
) + _UNSUPPORTED)
_KNOWN_POWER = frozenset(("internalName", "level", "slots", "powerset",
                          "isActive", "activeSubPower"))
_KNOWN_SLOT = {
    "io-set": frozenset(("type", "setId", "pieceNum", "attuned", "level", "booster")),
    "io-generic": frozenset(("type", "stat", "level", "booster")),
    "special": frozenset(("type", "category", "id", "relativeLevel")),
    "origin": frozenset(("type", "stat", "tier", "relativeLevel")),
}
# The seven inherents Hero Companion grants every character: one copy of
# app.js GRANTED_INHERENTS (tools/test_skif_reconstruct.py pins them equal).
HC_GRANTED_INHERENTS = frozenset((
    "Inherent.Inherent.Brawl", "Inherent.Inherent.Sprint", "Inherent.Inherent.Rest",
    "Inherent.Fitness.Swift", "Inherent.Fitness.Hurdle",
    "Inherent.Fitness.Health", "Inherent.Fitness.Stamina",
))
# Sidekick's own name -> full-name tables for the powers the game grants.
_SIDEKICK_INHERENT_TABLES = ("BASIC_INHERENT_POWERS", "INHERENT_FITNESS_POWERS",
                             "PRESTIGE_SPRINT_POWERS")
_SPECIAL_WITH_LEVEL = ("Hamidon_", "Synthetic_Hamidon_", "Titan_", "Hydra_",
                       "DSync_", "Dsync_")


def _issue(reason, where, detail):
    return {"reason": reason, "location": where, "detail": str(detail)}


def _positive_level(value):
    return type(value) is int and 1 <= value <= 50


def _resolve_class(build, root, hero_powersets, issues):
    catalog = _read_json(Path(root) / "archetypes.json", "Sidekick archetypes")
    entries = catalog.get("archetypes") if isinstance(catalog, dict) else None
    entry = entries.get(build.get("archetype")) if isinstance(entries, dict) else None
    class_name = (entry.get("stats") or {}).get("className") if isinstance(entry, dict) else None
    if not isinstance(class_name, str) or class_name not in hero_powersets.get("by_archetype", {}):
        issues.append(_issue("unknown_archetype", "build.archetype", build.get("archetype")))
        return None
    return class_name


def _resolve_sets(build, class_name, root, hero_powersets, issues):
    paths, _ = _contract(root)
    by_class = hero_powersets.get("by_archetype", {}).get(class_name, {})
    roles = (("primary", "primary"), ("secondary", "secondary"),
             ("epicPool", "epic"))
    mapped = {"primary": None, "secondary": None, "epic": None, "pools": []}

    def resolve(selection, role, where):
        if selection is None:
            return None
        source_id = selection["id"]
        path = paths.get(source_id)
        if not path:
            issues.append(_issue("unknown_source_set", where, source_id))
            return None
        shard = _read_json(path, f"Sidekick powerset {source_id}")
        if not isinstance(shard, dict) or shard.get("id") != source_id:
            issues.append(_issue("source_identity_mismatch", where, source_id))
            return None
        full = shard.get("setPath")
        if role == "pool":
            candidates = hero_powersets.get("pools") or []
        else:
            candidates = by_class.get(role) or []
        if (not isinstance(full, str)
                or sum(v.get("full_name") == full for v in candidates) != 1):
            issues.append(_issue("invalid_powerset_for_role", where, source_id))
            return None
        return full

    for source_key, native_key in roles:
        selected = build.get(source_key)
        mapped[native_key] = resolve(selected, native_key, f"build.{source_key}")
    for index, selection in enumerate(build.get("pools", [])):
        full = resolve(selection, "pool", f"build.pools[{index}]")
        if full:
            if full in mapped["pools"]:
                issues.append(_issue("duplicate_powerset", f"build.pools[{index}]", full))
            else:
                mapped["pools"].append(full)
    for mandatory in ("primary", "secondary"):
        if mapped[mandatory] is None:
            issues.append(_issue("required_selection_missing", f"build.{mandatory}", mandatory))
    if len(mapped["pools"]) > 4:
        issues.append(_issue("too_many_pools", "build.pools", len(mapped["pools"])))
    return mapped


def _source_state_issues(doc):
    issues = []
    build = doc["build"]
    for key, value in build.items():
        if key not in _KNOWN_BUILD or (key in _UNSUPPORTED and value):
            issues.append(_issue("unsupported_source_state", f"build.{key}", key))
    for bucket in ("primary", "secondary", "epicPool"):
        selection = build.get(bucket)
        if selection:
            _power_field_issues(issues, selection, f"build.{bucket}")
    for i, selection in enumerate(build.get("pools", [])):
        _power_field_issues(issues, selection, f"build.pools[{i}]")
    for i, power in enumerate(build.get("inherents", [])):
        _one_power_issues(issues, power, f"build.inherents[{i}]")
    return issues


def _power_field_issues(issues, selection, where):
    unknown_set_fields = set(selection) - {"id", "powers"}
    for field in sorted(unknown_set_fields):
        issues.append(_issue("unsupported_source_state", f"{where}.{field}", field))
    for i, power in enumerate(selection.get("powers", [])):
        _one_power_issues(issues, power, f"{where}.powers[{i}]")


def _one_power_issues(issues, power, power_where):
    for key in sorted(set(power) - _KNOWN_POWER):
        issues.append(_issue("unsupported_source_state", f"{power_where}.{key}", key))
    if power.get("isActive") is True or power.get("activeSubPower"):
        issues.append(_issue("unsupported_source_state", power_where, "active power mode"))
    for j, slot in enumerate(power["slots"]):
        if slot is None:
            continue
        for key in sorted(set(slot) - _KNOWN_SLOT[slot["type"]]):
            issues.append(_issue("unsupported_source_state",
                                 f"{power_where}.slots[{j}].{key}", key))


def _sidekick_inherent_names(root, issues):
    """Sidekick's own internalName -> fullName table, or None (with an issue)."""
    try:
        levels = _read_json(Path(root) / "levels.json", "Sidekick inherent table")
    except PreviewContractError as exc:
        issues.append(_issue("inherent_contract_missing", "build.inherents", exc))
        return None
    names = {}
    for table in _SIDEKICK_INHERENT_TABLES:
        for entry in (levels.get(table) or []) if isinstance(levels, dict) else []:
            if isinstance(entry, dict) and isinstance(entry.get("internalName"), str):
                names.setdefault(entry["internalName"], set()).add(entry.get("fullName"))
    return names


def _translate_inherents(body, root, hero_powers_by_full, enhancements,
                         default_io_level, issues, encountered):
    """Seat Sidekick's slotted inherents on the inherents HC grants.

    Identity comes from Sidekick's own name table, and must land on one of
    HC_GRANTED_INHERENTS; anything else (prestige runs, archetype inherents)
    refuses. The shape mirrors app.js ensureInherents: granted, never picked.
    """
    inherents = body.get("inherents") or []
    if not inherents:
        return []
    names = _sidekick_inherent_names(root, issues)
    if names is None:
        return []
    native = []
    for i, power in enumerate(inherents):
        where = f"build.inherents[{i}]"
        full_names = names.get(power["internalName"], set())
        if len(full_names) != 1:
            issues.append(_issue("unknown_inherent", where, power["internalName"]))
            continue
        full = next(iter(full_names))
        rec = hero_powers_by_full.get(full)
        if full not in HC_GRANTED_INHERENTS or not isinstance(rec, dict):
            issues.append(_issue("unsupported_inherent", where, full))
            continue
        if full in encountered:
            issues.append(_issue("duplicate_power", where, full))
            continue
        encountered.add(full)
        slots = []
        for j, source_slot in enumerate(power["slots"]):
            resolved = enhancements.get(f"{where}.slots[{j}]")
            slots.append(_native_slot(source_slot, resolved, f"{where}.slots[{j}]",
                                      default_io_level, issues)
                         if source_slot is not None and resolved else None)
        # Sidekick may omit an unenhanced inherent's base slot. Hero
        # Companion always exposes that granted slot (ensureInherents).
        if not slots:
            slots = [None]
        native.append({
            "full_name": full,
            "display_name": rec["display_name"],
            "powerset_full_name": rec["powerset_full_name"],
            "accepted_set_category_ids": copy.deepcopy(rec.get("accepted_set_category_ids", [])),
            "accepted_set_categories": copy.deepcopy(rec.get("accepted_set_categories", [])),
            "power_type": rec.get("power_type"),
            "include_in_totals": rec.get("power_type") == 1,
            "earned_slot_count": len(slots),
            "slotCount": len(slots),
            "slots": slots,
        })
    return native


def _native_slot(slot, mapping, where, default_io_level, issues):
    """Translate validated HC UID evidence without losing level semantics."""
    native = copy.deepcopy(mapping["hero_slot"])
    kind = mapping["type"]
    if kind in ("io-set", "io-generic"):
        level = mapping.get("io_level")
        if level is None and (kind == "io-generic" or not mapping.get("attuned")):
            if default_io_level is None:
                issues.append(_issue("io_level_not_embedded", where,
                                     "provide default_io_level from the Sidekick session"))
            else:
                level = default_io_level
        if level is not None:
            native["io_level"] = level
        booster = mapping.get("booster", 0)
        attuned = mapping.get("attuned", False)
        if not isinstance(booster, int) or booster > 5:
            issues.append(_issue("unsupported_booster", where, booster))
        elif booster and attuned:
            # Attuned IOs take no boosters; the engine would ignore it silently.
            issues.append(_issue("booster_on_attuned_io", where, booster))
        elif booster:
            native["boost"] = booster
        native["attuned"] = attuned
    elif kind in ("special", "origin"):
        relative = mapping.get("relative_level", 0)
        uid = mapping["source_uid"]
        if kind == "origin":
            issues.append(_issue("origin_enhancement_not_modeled", where, uid))
        elif uid.startswith(_SPECIAL_WITH_LEVEL):
            # Mirror mids_import's HO convention: +3 is a level-53 HO. The game's
            # HOs exist only at 50..53, so any other grade is refused, never priced.
            if not 0 <= relative <= 3:
                issues.append(_issue("unsupported_special_relative_level", where, relative))
            elif relative:
                native["io_level"] = 50 + relative
        elif relative:
            issues.append(_issue("unmodeled_special_relative_level", where, uid))
        native["attuned"] = False
    return native



def _translate_attack_chains(body, preview, issues):
    """Preserve Sidekick's saved cast order as reference metadata only.

    A chain is NOT simulated or optimized. Every power address must resolve
    to exactly one of the imported powers, otherwise reject the whole build.
    Both Sidekick's stable address and HC's full name travel with the save.
    """
    selected = {}
    for power in preview["resolved"]:
        key = (power["sidekick_set"], power["sidekick_power"])
        selected.setdefault(key, set()).add(power["hero_power"])

    seen_ids = set()
    translated = []
    for i, chain in enumerate(body.get("attackChains") or []):
        where = f"build.attackChains[{i}]"
        unknown = set(chain) - {"id", "name", "powers"}
        for field in sorted(unknown):
            issues.append(_issue("unsupported_attack_chain_field",
                                 f"{where}.{field}", field))
        if chain["id"] in seen_ids:
            issues.append(_issue("duplicate_attack_chain_id", f"{where}.id", chain["id"]))
        seen_ids.add(chain["id"])
        mapped = []
        for j, address in enumerate(chain["powers"]):
            powerset, sep, name = address.partition(":")
            matches = selected.get((powerset, name), set()) if sep else set()
            if len(matches) != 1:
                issues.append(_issue("unknown_attack_chain_power",
                                     f"{where}.powers[{j}]", address))
            else:
                mapped.append(next(iter(matches)))
        translated.append({
            "id": chain["id"],
            "name": chain["name"],
            "powers": mapped,
            "source_powers": copy.deepcopy(chain["powers"]),
        })
    return translated

def reconstruct_build(skif, hero_powers_by_full, hero_powersets,
                      contract_root, hero_piece_by_uid, *, default_io_level=None):
    """Reconstruct only when no known source semantics would be lost.

    Returns {ok, name, issues, preview, source_skif}; on success also build.
    A successful *structural* conversion still needs HC's legality validation
    before an editor or solver may accept it.
    """
    if default_io_level is not None and not _positive_level(default_io_level):
        raise ValueError("default_io_level must be an integer from 1 through 50")
    doc = load_document(skif)
    preview = preview_build(doc, hero_powers_by_full, contract_root,
                            hero_piece_by_uid=hero_piece_by_uid)
    # The identity-only preview predates reconstruction and flags origin as
    # unmapped. This layer retains that declared origin verbatim in HC's
    # native build metadata; no other preview issue may be waived.
    issues = [copy.deepcopy(issue) for issue in preview["unresolved"]
              if not (issue["reason"] == "state_not_mapped"
                      and issue["location"] in ("build.origin", "build.attackChains"))
              # Inherent identity is decided below from Sidekick's own table.
              and issue["reason"] != "inherent_not_mapped"]
    issues.extend(_source_state_issues(doc))
    body = doc["build"]
    attack_chains = _translate_attack_chains(body, preview, issues)
    class_name = _resolve_class(body, contract_root, hero_powersets, issues)
    sets = _resolve_sets(body, class_name, contract_root, hero_powersets, issues)

    native_powers = []
    matches = {p["location"]: p for p in preview["resolved"]}
    enhancements = {p["location"]: p for p in preview["resolved_enhancements"]}
    encountered = set()
    for bucket in ("primary", "secondary", "epicPool", "pools"):
        selections = body.get(bucket, []) if bucket == "pools" else [body.get(bucket)]
        for index, selection in enumerate(selections):
            if selection is None:
                continue
            location = (f"build.pools[{index}]" if bucket == "pools"
                        else f"build.{bucket}")
            role = ("epic" if bucket == "epicPool" else
                    "pool" if bucket == "pools" else bucket)
            selected_set = (sets["pools"][index] if role == "pool" and
                            index < len(sets["pools"]) else sets.get(role))
            for i, power in enumerate(selection.get("powers", [])):
                where = f"{location}.powers[{i}]"
                matched = matches.get(where)
                if not matched:
                    continue
                full = matched["hero_power"]
                if full in encountered:
                    issues.append(_issue("duplicate_power", where, full))
                    continue
                encountered.add(full)
                rec = hero_powers_by_full.get(full)
                if (not isinstance(rec, dict)
                        or rec.get("full_name") != full
                        or rec.get("powerset_full_name") != selected_set):
                    issues.append(_issue("inconsistent_power_identity", where, full))
                    continue
                slots = []
                for j, source_slot in enumerate(power["slots"]):
                    if source_slot is None:
                        slots.append(None)
                        continue
                    slot_where = f"{where}.slots[{j}]"
                    resolved = enhancements.get(slot_where)
                    slots.append(_native_slot(source_slot, resolved, slot_where,
                                              default_io_level, issues)
                                 if resolved else None)
                native_powers.append({
                    "full_name": full,
                    "display_name": rec["display_name"],
                    "powerset_full_name": selected_set,
                    "accepted_set_category_ids": copy.deepcopy(
                        rec.get("accepted_set_category_ids", [])),
                    "accepted_set_categories": copy.deepcopy(
                        rec.get("accepted_set_categories", [])),
                    "power_type": rec.get("power_type"),
                    "level_available": rec.get("level_available"),
                    "pick_level": power["level"],
                    "earned_slot_count": len(slots),
                    "slotCount": len(slots),
                    "slots": slots,
                })
    native_powers.extend(_translate_inherents(
        body, contract_root, hero_powers_by_full, enhancements,
        default_io_level, issues, encountered))
    result = {
        "ok": not issues,
        "name": body.get("name") or "Imported Sidekick build",
        "issues": issues,
        "preview": preview,
        "source_skif": doc,
        "editor_imported": False,
    }
    if issues:
        return result

    result["build"] = {
        "archetype": class_name, **sets,
        "char_level": body["level"],
        "origin": body.get("origin"),
        "incarnates": {},
        "sidekick_attack_chains": attack_chains,
        "powers": native_powers,
    }
    return result
