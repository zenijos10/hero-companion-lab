"""Fail-closed export of a native Hero Companion build to Sidekick SKIF v5.

The mirror of sidekick_reconstruct: every identity is looked up in the same
Sidekick contract the importer reads, and a power is written under the
Sidekick name that the importer's own resolver maps back to it. Anything
without an exact Sidekick identity refuses the whole export (no partial file).

Proven by tools/test_skif_export_sidekick.py: a real Sidekick build imported,
exported and imported again yields the identical Hero Companion build.
"""
import json
from pathlib import Path

from sidekick_preview import (GRANTED_SET, SourceSets, _Branches, _index_powers,
                              _read_json, _resolve_power, _source_archetype_fits,
                              _source_category_fits, hero_set_path)
from sidekick_reconstruct import HC_GRANTED_INHERENTS, accolade_records, slot_shape
from sidekick_enhancements import EnhancementResolver
from skif_document import SkifFormatError, load_document

_INHERENT_TABLES = ("BASIC_INHERENT_POWERS", "INHERENT_FITNESS_POWERS",
                    "PRESTIGE_SPRINT_POWERS")
_ROLE_CATEGORY = {"primary": "primary", "secondary": "secondary", "epicPool": "epic"}


def _issue(reason, where, detail):
    return {"reason": reason, "location": where, "detail": str(detail)}


class _Contract:
    """Reverse lookups over one Sidekick contract folder."""

    def __init__(self, root, hero_powers_by_full, epic_choices, hero_piece_by_uid=None):
        self.root = Path(root)
        self.sources = SourceSets(root)
        self.mids = self.sources.mids
        self.shards = [self.sources.get(set_id) for set_id in self.sources.ids()]
        self.hero = hero_powers_by_full
        self.epic_choices = epic_choices
        self.by_folded = _index_powers(hero_powers_by_full)
        self.boosts = _read_json(self.root / "boost-index.json", "Sidekick boost index")
        folded = {}
        for uid in self.boosts:
            folded.setdefault(uid.casefold(), []).append(uid)
        # The same uid but for case (our Dsync_*, Sidekick's DSync_*), where unique.
        self.boosts_folded = {key: uids[0] for key, uids in folded.items() if len(uids) == 1}
        archetypes = _read_json(self.root / "archetypes.json", "Sidekick archetypes")
        self.archetype_slugs = {
            (entry.get("stats") or {}).get("className"): slug
            for slug, entry in (archetypes.get("archetypes") or {}).items()
            if isinstance(entry, dict)}
        self._levels = None
        self._branches = {}
        self.inverse = (_invert_set_pieces(root, self.boosts, hero_piece_by_uid)
                        if hero_piece_by_uid is not None else {})

    def inherent_names(self):
        if self._levels is None:
            levels = _read_json(self.root / "levels.json", "Sidekick inherent table")
            self._levels = {entry["fullName"]: entry["internalName"]
                            for table in _INHERENT_TABLES for entry in levels.get(table) or []
                            if isinstance(entry, dict)}
        return self._levels

    def shard_for(self, set_full, role, archetype_slug):
        """The one Sidekick powerset the importer maps to `set_full` in this role.

        Uses the importer's own hero_set_path, so a renamed epic exports under
        the Sidekick record that imports back to it, never a lookalike."""
        found = []
        for s in self.shards:
            if not isinstance(s, dict):
                continue
            category = s.get("category")
            if role == "pools":
                fits = category == "pool"
            elif role == "epicPool":
                fits = category == "epic"
            else:
                fits = (_source_category_fits(s, role)
                        and _source_archetype_fits(s, role, archetype_slug))
            if fits and self.hero_set(s) == set_full:
                found.append(s)
        return found[0] if len(found) == 1 else None

    def family(self, role, seat, archetype_slug):
        """(selection id, {hero set: shard}) for a primary or secondary. An
        Arachnos build names its BASE set, as Sidekick does, and each branch pick
        names its branch; every other build is its one seated set."""
        if archetype_slug not in self._branches:
            self._branches[archetype_slug] = _Branches(self.root, archetype_slug)
        branches = self._branches[archetype_slug]
        members = branches.family(role, seat["id"])
        bases = members - branches.branch_ids
        selection_id = next(iter(bases)) if len(members) > 1 and len(bases) == 1 else seat["id"]
        shards = {}
        for member in members:
            shard = seat if member == seat["id"] else self.sources.get(member)
            if isinstance(shard, dict):
                shards[self.hero_set(shard)] = shard
        return selection_id, shards

    def granted_name(self, shards, hero_full):
        """(shard, Sidekick name) of a form attack the game grants inside one of
        these sets (Bright Nova Bolt: our Inherent.Inherent.Bright_Nova_Bolt)."""
        hits = [(shard, p["internalName"]) for shard in shards
                for p in shard.get("powers") or []
                if isinstance(p, dict) and p.get("autoIssue") is True and p.get("free") is True
                and isinstance(p.get("internalName"), str)
                and f"{GRANTED_SET}.{p['internalName']}".casefold() == hero_full.casefold()]
        return hits[0] if len(hits) == 1 else (None, None)

    def hero_set(self, record):
        return hero_set_path(record, self.mids, self.hero, self.epic_choices)

    def internal_name(self, shard, hero_full):
        """The Sidekick power name the importer resolves to `hero_full`."""
        names = [p.get("internalName") for p in shard.get("powers") or []
                 if isinstance(p, dict)]
        hero_set = self.hero_set(shard)
        hits = [n for n in names if _resolve_power(
            n, shard["setPath"], shard, self.mids, self.by_folded, "", [],
            hero_set=hero_set) == hero_full]
        return hits[0] if len(hits) == 1 else None

    def enhancement(self, slot):
        """The SKIF slot object for a native slot, or None when it has no identity."""
        uid = slot.get("piece_uid") or ""
        # Solver-placed pieces carry no flag; the uid says it (mids_import's rule).
        attuned = bool(slot.get("attuned")) or "Attuned" in uid or uid.startswith("Superior_")
        twins = [uid]
        for crafted, tuned in (("Crafted_", "Attuned_"),):
            if attuned and uid.startswith(crafted):
                twins.insert(0, tuned + uid[len(crafted):])
            if not attuned and uid.startswith(tuned):
                twins.insert(0, crafted + uid[len(tuned):])
        for twin in twins:
            source_uid = twin if twin in self.boosts else self.boosts_folded.get(twin.casefold())
            record = self.boosts.get(source_uid)
            written = (self._slot_from_record(record, slot, attuned)
                       if isinstance(record, dict) else None)
            if written:
                return written
        source_uid = self.inverse.get((uid, attuned))
        if source_uid:                    # e.g. our Crafted_Shrapnel_A = the game's Crafted_Artillery_A
            return self._slot_from_record(self.boosts[source_uid], slot, attuned)
        return None

    def _slot_from_record(self, record, slot, attuned):
        kind, level, boost = record.get("kind"), slot.get("io_level"), slot.get("boost")
        if kind == "io-set":
            if bool(record.get("attuned")) != attuned:
                return None
            out = {"type": "io-set", "setId": record["set"], "pieceNum": record["piece"],
                   "attuned": attuned}
        elif kind == "common-io" and record.get("level") is None:
            stat = self._unique_common_stat(record)
            if stat is None:
                return None
            out = {"type": "io-generic", "stat": stat}
        elif kind == "special":
            out = {"type": "special", "category": record["family"], "id": record["id"]}
            if type(level) is int and level > 50:
                out["relativeLevel"] = level - 50
            return out
        else:
            return None
        if type(level) is int:
            out["level"] = level
        if type(boost) is int and boost > 0:
            out["booster"] = boost
        return out

    def _unique_common_stat(self, record):
        for stat in record.get("stats") or []:
            owners = [r for r in self.boosts.values() if isinstance(r, dict)
                      and r.get("kind") == "common-io" and r.get("level") is None
                      and stat in (r.get("stats") or [])]
            if len(owners) == 1:
                return stat
        return None


def _invert_set_pieces(root, boosts, hero_piece_by_uid):
    """{(our piece uid, attuned): Sidekick uid}: the importer's own mapping, reversed.

    Built by resolving every Sidekick set piece forward with EnhancementResolver,
    so export can never map a piece the importer would not map back. A key two
    Sidekick uids share is dropped (ambiguous), never guessed.
    """
    resolver = EnhancementResolver(root, hero_piece_by_uid)
    found, clashes = {}, set()
    for source_uid, record in boosts.items():
        if not isinstance(record, dict) or record.get("kind") != "io-set":
            continue
        attuned = bool(record.get("attuned"))
        mapped, issue = resolver.resolve({"type": "io-set", "setId": record["set"],
                                          "pieceNum": record["piece"], "attuned": attuned,
                                          "level": 50})
        if issue:
            continue
        key = (mapped["hero_slot"]["piece_uid"], attuned)
        if key in found and found[key] != source_uid:
            clashes.add(key)
        found[key] = source_uid
    return {k: v for k, v in found.items() if k not in clashes}


def export_build(build, hero_powers_by_full, contract_root, hero_powersets=None, *, name=None,
                 hero_piece_by_uid=None, incarnate_catalog=None):
    """Return {ok, issues, dropped, skif?}; `skif` only when nothing is lost.

    hero_powersets (powersets.json) supplies the epics this archetype may take,
    which a renamed epic needs; without it only identically named epics export.
    hero_piece_by_uid (the import lookup) lets a piece whose uid spelling differs
    from the game's export under the game's uid; without it, such a piece refuses.

    `dropped` lists Sidekick attack-chain notes left out because a power they
    name is no longer in the build (they were reference notes, never state).
    """
    issues, dropped = [], []
    epic_choices = None
    if hero_powersets is not None:
        by_class = hero_powersets.get("by_archetype", {}).get(build.get("archetype"), {})
        epic_choices = [e.get("full_name") for e in by_class.get("epic") or []]
    contract = _Contract(contract_root, hero_powers_by_full, epic_choices, hero_piece_by_uid)
    slug = contract.archetype_slugs.get(build.get("archetype"))
    if not slug:
        issues.append(_issue("archetype_not_exportable", "archetype", build.get("archetype")))
    # The app keeps the character's level as level_reached (none on a level-50 plan).
    level = build.get("char_level") or build.get("level_reached") or 50
    out = {"dataset": "homecoming", "archetype": slug, "level": level}
    if name or build.get("name"):
        out["name"] = name or build.get("name")
    if isinstance(build.get("origin"), str):
        out["origin"] = build["origin"]

    # Only the standard seven inherited powers can be represented by this
    # exporter. An archetype/prestige or future inherent must never vanish
    # merely because the general power loop excludes Inherent.* records.
    # A form attack (Inherent.Inherent.Bright_Nova_Bolt) travels inside its powerset.
    picks = [p for p in build.get("powers") or [] if p["full_name"] not in HC_GRANTED_INHERENTS]
    roles = [("primary", build.get("primary")), ("secondary", build.get("secondary")),
             ("epicPool", build.get("epic"))]
    roles += [("pools", pool) for pool in build.get("pools") or []]
    pools, placed = [], set()
    for role, set_full in roles:
        if not set_full:
            continue
        selection = _selection(contract, role, set_full, slug, picks, issues, placed)
        if role == "pools":
            pools.append(selection)
        else:
            out[role] = selection
    for power in picks:
        if power["full_name"] in placed:
            continue
        reason = ("inherent_not_exportable" if power["full_name"].startswith("Inherent.")
                  else "power_outside_build_sets")
        issues.append(_issue(reason, power["full_name"], _set_of(power)))
    if pools:
        out["pools"] = pools

    inherents = _inherents(contract, build, issues)
    if inherents:
        out["inherents"] = inherents
    incarnates = _incarnates(build, issues, incarnate_catalog)
    if incarnates:
        out["incarnates"] = incarnates
    chains = _attack_chains(build, picks, dropped)
    if chains:
        out["attackChains"] = chains

    accolades = _accolades(contract.sources, build.get("accolades") or [], issues)
    if accolades:
        out["accolades"] = accolades
    slot_order, dropped_slot_order = _slot_order(build)
    if slot_order:
        out["slotOrder"] = slot_order

    result = {"ok": not issues, "issues": issues, "dropped": dropped,
              "dropped_slot_order": dropped_slot_order}
    if issues:
        result["ok"] = False
        return result
    try:
        result["skif"] = load_document({"version": 5, "build": out})
    except SkifFormatError as exc:
        result.update(ok=False, issues=[_issue("skif_format", "build", exc)])
    return result


def _set_of(power):
    return power.get("powerset_full_name") or power["full_name"].rsplit(".", 1)[0]


def _selection(contract, role, set_full, slug, picks, issues, placed):
    where = f"{role}:{set_full}"
    seat = contract.shard_for(set_full, role, slug)
    if seat is None:
        issues.append(_issue("powerset_not_exportable", where, set_full))
        placed.update(p["full_name"] for p in picks if _set_of(p) == set_full)
        return {"id": set_full, "powers": []}
    selection_id, shards = ((seat["id"], {set_full: seat}) if role not in ("primary", "secondary")
                            else contract.family(role, seat, slug))
    powers = []
    for power in picks:
        full = power["full_name"]
        if full in placed:      # already written by an earlier selection
            continue
        shard = shards.get(_set_of(power))
        internal = contract.internal_name(shard, full) if shard else None
        if shard is None and _set_of(power) == GRANTED_SET:
            shard, internal = contract.granted_name(list(shards.values()), full)
        if shard is None:
            continue
        placed.add(full)
        if internal is None:
            issues.append(_issue("power_not_exportable", full, shard["id"]))
            continue
        if type(power.get("pick_level")) is not int:
            issues.append(_issue("pick_level_unknown", full, power.get("pick_level")))
            continue
        written = {"internalName": internal, "level": power["pick_level"]}
        if shard["id"] != selection_id:
            written["powerset"] = shard["id"]
        written["slots"] = _slots(contract, power, issues)
        powers.append(written)
    return {"id": selection_id, "powers": powers}


def _slots(contract, power, issues):
    out = []
    for j, slot in enumerate(power.get("slots") or []):
        if not slot:
            out.append(None)
            continue
        written = contract.enhancement(slot)
        if written is None:
            issues.append(_issue("enhancement_not_exportable",
                                 f"{power['full_name']}.slots[{j}]",
                                 slot.get("piece_uid") or slot.get("piece_name")))
        out.append(written)
    return out


def _inherents(contract, build, issues):
    """Only an inherent the user authored on travels (Sidekick's own rule)."""
    out = []
    for power in build.get("powers") or []:
        full = power["full_name"]
        slots = power.get("slots") or []
        if full not in HC_GRANTED_INHERENTS or (len(slots) <= 1 and not any(slots)):
            continue
        internal = contract.inherent_names().get(full)
        if internal is None:
            issues.append(_issue("inherent_not_exportable", full, full))
            continue
        out.append({"internalName": internal, "level": 1, "slots": _slots(contract, power, issues)})
    return out


def _incarnates(build, issues, incarnate_catalog=None):
    """Export only known Hero Companion incarnates in the matching slot.

    The JSON codec only checks the shape of the Sidekick record; it cannot
    prove a particular incarnate power belongs to the game's dataset. The
    shipped HC incarnate catalog provides that independent proof, as it does
    on import, before the file is emitted.
    """
    picks = build.get("incarnates") or {}
    if not picks:
        return {}
    if not isinstance(picks, dict):
        issues.append(_issue("incarnate_not_exportable", "incarnates",
                             "Expected a map of incarnate selections"))
        return {}
    if incarnate_catalog is not None:
        catalog = incarnate_catalog
    else:
        # Offline callers may omit the catalog; the packaged app always
        # supplies its already-loaded INCARNATES instead of assuming source
        # tree file paths still exist inside a frozen executable.
        try:
            catalog = _read_json(Path(__file__).resolve().parents[1] / "data" / "incarnates.json",
                                 "Hero Companion incarnate catalog")
        except (OSError, ValueError) as exc:
            issues.append(_issue("incarnate_catalog_unavailable", "incarnates", exc))
            return {}
    slots = catalog.get("slots") if isinstance(catalog, dict) else None
    if not isinstance(slots, list):
        issues.append(_issue("incarnate_catalog_unavailable", "incarnates",
                             "No incarnate slot catalog"))
        return {}
    out = {}
    for slot, pick in picks.items():
        where = f"incarnates.{slot}"
        if isinstance(slot, str) and slot.casefold() in out:
            issues.append(_issue("incarnate_not_exportable", where,
                                 "Duplicate incarnate slot (case-insensitive)"))
            continue
        if (not isinstance(slot, str)
                or not isinstance(pick, dict)
                or not isinstance(pick.get("full_name"), str)
                or ("active" in pick and type(pick["active"]) is not bool)):
            issues.append(_issue("incarnate_not_exportable", where, pick))
            continue
        matched_slots = [s for s in slots if isinstance(s, dict)
                         and isinstance(s.get("slot"), str)
                         and s["slot"].casefold() == slot.casefold()]
        if len(matched_slots) != 1:
            issues.append(_issue("incarnate_not_exportable", where,
                                 "Unknown or ambiguous incarnate slot"))
            continue
        candidates = matched_slots[0].get("choices")
        if not isinstance(candidates, list):
            issues.append(_issue("incarnate_catalog_unavailable", where,
                                 "Missing incarnate choices"))
            continue
        matches = [c for c in candidates if isinstance(c, dict)
                   and c.get("full_name") == pick["full_name"]]
        if len(matches) != 1:
            issues.append(_issue("incarnate_not_exportable", where, pick["full_name"]))
            continue
        out[matched_slots[0]["slot"].lower()] = {
            "power": pick["full_name"], "active": pick.get("active") is not False}
    return out


def _accolades(sources, keys, issues):
    """Sidekick's ids for our accolade keys: the game's internal name, lower-cased
    (how Sidekick stores them). A key Sidekick has no record of refuses the export."""
    if not keys:
        return []
    names = {p["internalName"].casefold() for p in accolade_records(sources)["powers"]
             if isinstance(p, dict) and isinstance(p.get("internalName"), str)}
    out = []
    for key in keys:
        if not isinstance(key, str) or key.casefold() not in names:
            issues.append(_issue("accolade_not_exportable", "accolades", key))
        elif key.casefold() not in out:     # one entry each, as Sidekick stores them
            out.append(key.casefold())
    return out


def _slot_order(build):
    """(Sidekick's slot history, dropped?): written back verbatim only while the
    slots it describes are unchanged; otherwise left out, and the caller says so."""
    kept = build.get("sidekick_slot_order")
    if not isinstance(kept, dict) or not kept.get("entries"):
        return None, False
    if kept.get("shape") != slot_shape(build.get("powers") or []):
        return None, True
    return kept["entries"], False


def _attack_chains(build, picks, dropped):
    present = {p["full_name"] for p in picks}
    out = []
    for chain in build.get("sidekick_attack_chains") or []:
        if all(p in present for p in chain.get("powers") or []):
            out.append({"id": chain["id"], "name": chain.get("name", ""),
                        "powers": list(chain.get("source_powers") or [])})
        else:
            dropped.append(chain["id"])
    return out


def dumps(skif):
    """The exported file text (deterministic, validated by the codec)."""
    return json.dumps(skif, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
