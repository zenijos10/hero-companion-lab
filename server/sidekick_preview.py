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


# Sidekick keeps pools and epics in two grouped files, not per-set shards.
_GROUPED_SETS = (("power-pools.json", "pool"), ("epic-pools.json", "epic"))


class SourceSets:
    """Every Sidekick powerset by id: the manifest's shards plus the grouped
    pool and epic files. A set in neither stays unknown (fail closed)."""

    def __init__(self, root):
        self.paths, self.mids = _contract(root)
        self._grouped = {}
        base = Path(root).resolve()
        for name, category in _GROUPED_SETS:
            if not (base / name).is_file():
                continue  # an older contract folder: its pools stay unknown
            data = _read_json(base / name, f"Sidekick {category} sets")
            if not isinstance(data, dict):
                raise PreviewContractError(f"Sidekick {name} is malformed")
            for set_id, record in data.items():
                if (not isinstance(record, dict) or record.get("id") != set_id
                        or set_id in self.paths or set_id in self._grouped):
                    raise PreviewContractError(
                        f"Sidekick {category} set {set_id!r} is malformed or duplicated")
                self._grouped[set_id] = dict(record, category=category)

    def get(self, set_id):
        if set_id in self.paths:
            return _read_json(self.paths[set_id], f"Sidekick shard {set_id}")
        return self._grouped.get(set_id)

    def ids(self):
        return [*self.paths, *self._grouped]


def hero_set_path(record, mids, hero_powers_by_full, epic_choices=None):
    """Hero Companion's name for a Sidekick set, or None when nothing proves one.

    The game's own name is usually ours. Epics diverge systematically (the
    game's Epic.Melee_Psionic_Mastery is our Epic.Psionic_Mastery_ScrapStalk),
    so an epic name Hero Companion does not have resolves through Sidekick's
    own alias table, else to the ONE epic this archetype may take with the
    identical power roster: the two-signal rule tools/epic_set_name_bridge.json
    was proven with (all 12 of its pairs agree). A name we do have is never
    translated, so another archetype's epic is refused, not re-labelled.
    """
    set_path = record.get("setPath")
    if (record.get("category") != "epic" or epic_choices is None
            or set_path in epic_choices or _is_hero_set(set_path, hero_powers_by_full)):
        return set_path
    folded = {choice.casefold(): choice for choice in epic_choices}
    alias = {client.casefold(): ours for ours, client in (mids.get("powersetAlias") or {}).items()}
    named = folded.get(alias.get(set_path.casefold(), ""))
    if named:
        return named
    renames = mids["nameReverse"].get(set_path.casefold(), {})
    roster = {(renames.get(p["internalName"].casefold()) or p["internalName"]).casefold()
              for p in record.get("powers") or [] if isinstance(p, dict)}
    matches = [c for c in epic_choices if _leaf_roster(c, hero_powers_by_full) == roster]
    return matches[0] if len(matches) == 1 else None


def _is_hero_set(set_path, hero_powers_by_full):
    prefix = f"{set_path}."
    return any(full.startswith(prefix) for full in hero_powers_by_full)


def _leaf_roster(set_path, hero_powers_by_full):
    prefix = f"{set_path}."
    return {full[len(prefix):].casefold() for full in hero_powers_by_full
            if full.startswith(prefix) and "." not in full[len(prefix):]}


def _resolve_power(name, set_path, shard, mids, by_folded, where, issues, hero_set=None):
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

    full = f"{hero_set or set_path}.{mapped}"
    matches = by_folded.get(full.casefold(), [])
    if len(matches) != 1:
        issues.append(_issue("unknown_hero_power" if not matches else
                             "ambiguous_hero_power", where, full))
        return None
    return matches[0]


def _is_own_set(bucket):
    return bucket in ("primary", "secondary")


def _source_archetype_fits(shard, bucket, archetype):
    """A pool has no archetype, and an epic POOL's label is a hint only (Sidekick
    labels the VEAT epics "arachnos_soldier", which Widows take too): Hero
    Companion's own per-archetype epic list gates those. A primary or secondary
    always belongs to the build's own archetype."""
    if not _is_own_set(bucket) and shard.get("category") in ("pool", "epic"):
        return True
    return shard.get("archetype") in (None, archetype)


def _source_category_fits(shard, bucket):
    """Sidekick files the Kheldian and Arachnos primaries and secondaries under
    "epic", the game's own grouping for those archetypes."""
    if not _is_own_set(bucket):
        return True
    return shard.get("category") in (None, bucket, "epic")


GRANTED_SET = "Inherent.Inherent"


class _Branches:
    """The Arachnos branch sets (Crab/Bane, Night Widow/Fortunata) an archetype
    may draw from beside its base set, as Sidekick's archetypes.json states them."""

    _KEYS = {"primary": ("primarySets", "primarySet"),
             "secondary": ("secondarySets", "secondarySet")}

    def __init__(self, root, archetype):
        path = Path(root) / "archetypes.json"
        # No catalog, no branches: every pick stays in its selection's own set.
        catalog = _read_json(path, "Sidekick archetypes") if path.is_file() else {}
        entry = ((catalog.get("archetypes") or {}).get(archetype)
                 if isinstance(catalog, dict) else None)
        self._entry = entry if isinstance(entry, dict) else {}
        self._branches = [b for b in (self._entry.get("branches") or {}).values()
                          if isinstance(b, dict)]
        self.branch_ids = {b.get(key) for b in self._branches
                           for _, key in self._KEYS.values()} - {None}

    def branch_of(self, set_id):
        """The branch (crab-spider, fortunata, ...) a set belongs to, else None."""
        hits = [key for key, b in (self._entry.get("branches") or {}).items()
                if isinstance(b, dict) and set_id in (b.get("primarySet"), b.get("secondarySet"))]
        return hits[0] if len(hits) == 1 else None

    def family(self, bucket, set_id):
        """Every set a pick in this selection may come from: the base set and
        its branches, or the selection's own set alone."""
        if bucket not in self._KEYS or not self._branches:
            return {set_id}
        bases, key = self._KEYS[bucket]
        family = set(self._entry.get(bases) or []) | {b.get(key) for b in self._branches}
        family.discard(None)
        return family if set_id in family else {set_id}


def _source_record(shard, name):
    """The one source power record named `name`; Sidekick's own lookup ignores case
    (an older file writes Ws_Wide_Area_Web_Grenade for WS_Wide_Area_Web_Grenade)."""
    records = [p for p in (shard or {}).get("powers") or [] if isinstance(p, dict)]
    for same in (lambda n: n == name, lambda n: n.casefold() == name.casefold()):
        hits = [p for p in records if isinstance(p.get("internalName"), str)
                and same(p["internalName"])]
        if hits:
            return hits[0] if len(hits) == 1 else None
    return None


def _source_of(power, set_id, shard, family, sources):
    """(source set id, source record) for one pick; (None, None) when it names a
    set outside its selection's family. An older Sidekick file files a branch
    pick under the base set; like Sidekick, look in the branches for it."""
    name, named = power["internalName"], power.get("powerset")
    if named and named not in family:
        return None, None
    if named and named != set_id:
        return named, _source_record(sources.get(named), name)
    record = _source_record(shard, name)
    if record is not None or named:
        return set_id, record
    hits = [(other, found) for other in sorted(family - {set_id})
            if (found := _source_record(sources.get(other), name)) is not None]
    return hits[0] if len(hits) == 1 else (set_id, None)


def _resolve_source_power(record, source, mids, hero_powers_by_full, hero_index, where,
                          issues, epic_choices):
    """Hero Companion's power for one source record. A power the game grants
    (Sidekick: autoIssue + free, e.g. Bright Nova Bolt, Energy Flight; its own
    requires names our Inherent.Inherent record) lands on that record."""
    hero_set = hero_set_path(source, mids, hero_powers_by_full, epic_choices)
    if hero_set is None:
        issues.append(_issue("unknown_hero_powerset", where, source.get("setPath")))
        return None
    found = []
    matched = _resolve_power(record["internalName"], source["setPath"], source, mids,
                             hero_index, where, found, hero_set=hero_set)
    if matched is None and record.get("autoIssue") is True and record.get("free") is True:
        granted = hero_index.get(f"{GRANTED_SET}.{record['internalName']}".casefold(), [])
        if len(granted) == 1:
            return granted[0]
    issues.extend(found)
    return matched


def preview_build(document, hero_powers_by_full, contract_root, hero_piece_by_uid=None,
                  epic_choices=None):
    """Return verifiable power matches and unresolved facts, never an editable build.

    document: Sidekick v5 dict or JSON string.
    hero_powers_by_full: HC's POWER_BY_FULL mapping (or equivalent test mapping).
    contract_root: offline Sidekick contract/homecoming directory.
    hero_piece_by_uid: optional HC import lookup; if absent, enhancements
        remain explicitly unresolved. When present, all identities must be
        provable from Sidekick boost-index.json and HC's own import catalogue.
    epic_choices: optional full names of the epics this archetype may take;
        without them only an epic Hero Companion names identically resolves.
    """
    doc = load_document(document)
    build = doc["build"]
    if build["dataset"] != "homecoming":
        raise PreviewContractError("Only Homecoming builds can be previewed")
    if not isinstance(hero_powers_by_full, dict):
        raise PreviewContractError("Hero Companion power index must be a mapping")

    sources = SourceSets(contract_root)
    mids = sources.mids
    hero_index = _index_powers(hero_powers_by_full)
    enhancement_bridge = (EnhancementResolver(contract_root, hero_piece_by_uid)
                          if hero_piece_by_uid is not None else None)
    branches = _Branches(contract_root, build.get("archetype"))
    issues = []
    resolved = []
    enhancements = []
    seats, families = {}, {}

    def resolve_slots(power, location):
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

    def visit(bucket, selection, position=None):
        if selection is None:
            return
        where = f"build.{bucket}" + (f"[{position}]" if position is not None else "")
        set_id = selection["id"]
        shard = sources.get(set_id)
        if shard is None:
            issues.append(_issue("unknown_source_set", where, set_id))
            return
        if not isinstance(shard, dict) or shard.get("id") != set_id:
            issues.append(_issue("source_identity_mismatch", where, set_id))
            return
        set_path = shard.get("setPath")
        if not isinstance(set_path, str) or not set_path or not isinstance(shard.get("powers"), list):
            raise PreviewContractError(f"Malformed Sidekick shard: {set_id}")
        if not _source_archetype_fits(shard, bucket, build.get("archetype")):
            issues.append(_issue("source_archetype_mismatch", where, set_id))
            return
        if not _source_category_fits(shard, bucket):
            issues.append(_issue("source_category_mismatch", where, set_id))
            return
        if hero_set_path(shard, mids, hero_powers_by_full, epic_choices) is None:
            issues.append(_issue("unknown_hero_powerset", where, set_path))
            return

        family = branches.family(bucket, set_id)
        used_branches = set()
        for i, power in enumerate(selection.get("powers", [])):
            location = f"{where}.powers[{i}]"
            source_id, record = _source_of(power, set_id, shard, family, sources)
            if source_id is None:
                issues.append(_issue("cross_set_power_not_mapped", location, power["powerset"]))
                continue
            if record is None:
                issues.append(_issue("unknown_source_power", location, power["internalName"]))
            else:
                if source_id in branches.branch_ids:
                    used_branches.add(source_id)
                source = shard if source_id == set_id else sources.get(source_id)
                matched = _resolve_source_power(record, source, mids, hero_powers_by_full,
                                                hero_index, location, issues, epic_choices)
                if matched is not None:
                    resolved.append({
                        "location": location, "sidekick_set": source_id,
                        "sidekick_power": record["internalName"], "hero_power": matched,
                        "hero_set": hero_powers_by_full[matched].get("powerset_full_name"),
                        "level": power["level"], "slot_count": len(power["slots"]),
                    })
            resolve_slots(power, location)
            for key in ("isActive", "activeSubPower"):
                if power.get(key):
                    issues.append(_issue("state_not_mapped", f"{location}.{key}", key))
        if len(used_branches) > 1:
            issues.append(_issue("mixed_branch_sets", where, ", ".join(sorted(used_branches))))
        seats[bucket] = next(iter(used_branches)) if len(used_branches) == 1 else set_id
        if bucket in ("primary", "secondary"):   # pools share one bucket name; never keyed here
            families[bucket] = sorted(filter(None, (
                hero_set_path(sources.get(member) or {}, mids, hero_powers_by_full,
                              epic_choices)
                for member in family)))

    for bucket in ("primary", "secondary", "epicPool"):
        visit(bucket, build.get(bucket))
    for index, selection in enumerate(build.get("pools", [])):
        visit("pools", selection, index)
    # One branch choice sets both: Crab primary with Bane secondary is impossible.
    chosen = {branches.branch_of(seats.get(b)) for b in ("primary", "secondary")} - {None}
    if len(chosen) > 1:
        issues.append(_issue("mixed_branch_sets", "build.secondary", ", ".join(sorted(chosen))))

    # The power identity of an inherent is the reconstruction layer's job
    # (Sidekick's own name table); its enhancements resolve here like any slot.
    for i, power in enumerate(build.get("inherents", [])):
        issues.append(_issue("inherent_not_mapped", f"build.inherents[{i}]",
                             power["internalName"]))
        resolve_slots(power, f"build.inherents[{i}]")
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
        "resolved_enhancements": enhancements, "seats": seats,
        "families": families,
        "unresolved": issues, "ready_for_import": False,
    }
