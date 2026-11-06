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

from sidekick_preview import _contract, _index_powers, _read_json, _resolve_power
from sidekick_reconstruct import HC_GRANTED_INHERENTS
from skif_document import SkifFormatError, load_document

_INHERENT_TABLES = ("BASIC_INHERENT_POWERS", "INHERENT_FITNESS_POWERS",
                    "PRESTIGE_SPRINT_POWERS")
_ROLE_CATEGORY = {"primary": "primary", "secondary": "secondary", "epicPool": "epic"}


def _issue(reason, where, detail):
    return {"reason": reason, "location": where, "detail": str(detail)}


class _Contract:
    """Reverse lookups over one Sidekick contract folder."""

    def __init__(self, root, hero_powers_by_full):
        self.root = Path(root)
        paths, self.mids = _contract(root)
        self.shards = [_read_json(path, f"Sidekick powerset {sid}") for sid, path in paths.items()]
        self.by_folded = _index_powers(hero_powers_by_full)
        self.boosts = _read_json(self.root / "boost-index.json", "Sidekick boost index")
        archetypes = _read_json(self.root / "archetypes.json", "Sidekick archetypes")
        self.archetype_slugs = {
            (entry.get("stats") or {}).get("className"): slug
            for slug, entry in (archetypes.get("archetypes") or {}).items()
            if isinstance(entry, dict)}
        self._levels = None

    def inherent_names(self):
        if self._levels is None:
            levels = _read_json(self.root / "levels.json", "Sidekick inherent table")
            self._levels = {entry["fullName"]: entry["internalName"]
                            for table in _INHERENT_TABLES for entry in levels.get(table) or []
                            if isinstance(entry, dict)}
        return self._levels

    def shard_for(self, set_full, role, archetype_slug):
        """The one Sidekick powerset whose setPath is `set_full` in this role."""
        found = [s for s in self.shards if isinstance(s, dict)
                 and s.get("setPath") == set_full
                 and s.get("archetype") in (None, archetype_slug)
                 and (role not in _ROLE_CATEGORY
                      or s.get("category") in (None, _ROLE_CATEGORY[role]))]
        return found[0] if len(found) == 1 else None

    def internal_name(self, shard, hero_full):
        """The Sidekick power name the importer resolves to `hero_full`."""
        names = [p.get("internalName") for p in shard.get("powers") or []
                 if isinstance(p, dict)]
        hits = [n for n in names if _resolve_power(
            n, shard["setPath"], shard, self.mids, self.by_folded, "", []) == hero_full]
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
        for source_uid in twins:
            record = self.boosts.get(source_uid)
            if isinstance(record, dict):
                return self._slot_from_record(record, slot, attuned)
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


def export_build(build, hero_powers_by_full, contract_root, *, name=None):
    """Return {ok, issues, dropped, skif?}; `skif` only when nothing is lost.

    `dropped` lists Sidekick attack-chain notes left out because a power they
    name is no longer in the build (they were reference notes, never state).
    """
    issues, dropped = [], []
    contract = _Contract(contract_root, hero_powers_by_full)
    slug = contract.archetype_slugs.get(build.get("archetype"))
    if not slug:
        issues.append(_issue("archetype_not_exportable", "archetype", build.get("archetype")))
    out = {"dataset": "homecoming", "archetype": slug, "level": build.get("char_level") or 50}
    if name or build.get("name"):
        out["name"] = name or build.get("name")
    if isinstance(build.get("origin"), str):
        out["origin"] = build["origin"]

    picks = [p for p in build.get("powers") or [] if not p["full_name"].startswith("Inherent.")]
    roles = [("primary", build.get("primary")), ("secondary", build.get("secondary")),
             ("epicPool", build.get("epic"))]
    roles += [("pools", pool) for pool in build.get("pools") or []]
    pools, placed = [], set()
    for role, set_full in roles:
        if not set_full:
            continue
        selection = _selection(contract, role, set_full, slug, picks, issues)
        placed.update(p["full_name"] for p in picks if _set_of(p) == set_full)
        if role == "pools":
            pools.append(selection)
        else:
            out[role] = selection
    for power in picks:
        if power["full_name"] not in placed:
            issues.append(_issue("power_outside_build_sets", power["full_name"], _set_of(power)))
    if pools:
        out["pools"] = pools

    inherents = _inherents(contract, build, issues)
    if inherents:
        out["inherents"] = inherents
    incarnates = _incarnates(build, issues)
    if incarnates:
        out["incarnates"] = incarnates
    chains = _attack_chains(build, picks, dropped)
    if chains:
        out["attackChains"] = chains

    result = {"ok": not issues, "issues": issues, "dropped": dropped}
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


def _selection(contract, role, set_full, slug, picks, issues):
    where = f"{role}:{set_full}"
    shard = contract.shard_for(set_full, role, slug)
    if shard is None:
        issues.append(_issue("powerset_not_exportable", where, set_full))
        return {"id": set_full, "powers": []}
    powers = []
    for power in picks:
        if _set_of(power) != set_full:
            continue
        internal = contract.internal_name(shard, power["full_name"])
        if internal is None:
            issues.append(_issue("power_not_exportable", power["full_name"], shard["id"]))
            continue
        if type(power.get("pick_level")) is not int:
            issues.append(_issue("pick_level_unknown", power["full_name"], power.get("pick_level")))
            continue
        powers.append({"internalName": internal, "level": power["pick_level"],
                       "slots": _slots(contract, power, issues)})
    return {"id": shard["id"], "powers": powers}


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


def _incarnates(build, issues):
    out = {}
    for slot, pick in (build.get("incarnates") or {}).items():
        if not isinstance(pick, dict) or not isinstance(pick.get("full_name"), str):
            issues.append(_issue("incarnate_not_exportable", f"incarnates.{slot}", pick))
            continue
        out[slot.lower()] = {"power": pick["full_name"], "active": pick.get("active") is not False}
    return out


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
