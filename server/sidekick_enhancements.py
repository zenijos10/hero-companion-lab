"""Resolve Sidekick v5 enhancement identities using the *exported client contract*.

No UID is guessed from a set name, piece number, or displayed label. The
Sidekick boost-index supplies the actual identity; Hero Companion's import
lookup proves that the slot can be understood by this game's shipped data.

This module does not yet validate slot legality or translate the full build.
"""
import copy
import json
from pathlib import Path


class EnhancementContractError(ValueError):
    """A missing or corrupted Sidekick enhancement contract."""


def _load(path, label):
    try:
        with path.open(encoding="utf-8") as handle:
            result = json.load(handle)
    except (OSError, ValueError) as exc:
        raise EnhancementContractError(f"{label}: {exc}") from exc
    if not isinstance(result, dict):
        raise EnhancementContractError(f"{label}: expected object")
    return result


class EnhancementResolver:
    """A deterministic, read-only, exact-match enhancement vocabulary bridge."""

    def __init__(self, contract_root, hero_piece_by_uid):
        root = Path(contract_root)
        self._boosts = _load(root / "boost-index.json", "Sidekick boost index")
        catalog = _load(root / "enhancements.json", "Sidekick enhancement catalog")
        types = catalog.get("commonIoTypes")
        if not isinstance(types, list) or not all(isinstance(t, str) for t in types):
            raise EnhancementContractError("Sidekick commonIoTypes missing or invalid")
        if not isinstance(hero_piece_by_uid, dict):
            raise EnhancementContractError("Hero Companion enhancement lookup must be a map")
        for uid, record in self._boosts.items():
            if not isinstance(uid, str) or not isinstance(record, dict):
                raise EnhancementContractError(f"Malformed boost-index entry: {uid}")
        self._common_types = frozenset(types)
        self._hero = hero_piece_by_uid

    def _matches(self, piece, origin):
        kind = piece["type"]
        if kind == "io-set":
            def match(record):
                return (
                    record.get("kind") == "io-set"
                    and record.get("set") == piece["setId"]
                    and record.get("piece") == piece["pieceNum"]
                    and record.get("attuned") is bool(piece.get("attuned", False))
                )
        elif kind == "io-generic":
            # An unlevelled boost entry is the canonical type identity; a
            # concrete lvl-50 UID is a separate *record*, not another stat.
            if piece["stat"] not in self._common_types:
                return []
            def match(record):
                return (
                    record.get("kind") == "common-io"
                    and record.get("level") is None
                    and piece["stat"] in record.get("stats", [])
                )
        elif kind == "special":
            def match(record):
                return (
                    record.get("kind") == "special"
                    and record.get("family") == piece["category"]
                    and record.get("id") == piece["id"]
                )
        elif kind == "origin":
            def match(record):
                return (
                    record.get("kind") == "origin"
                    and record.get("tier") == piece["tier"]
                    and piece["stat"] in record.get("stats", [])
                    and (origin is None or origin in record.get("origins", []))
                )
        else:
            return []
        return [(uid, record) for uid, record in self._boosts.items() if match(record)]

    def resolve(self, piece, character_origin=None):
        """Return (identity, None) or (None, explicit reason).

        The identity includes a source UID, exact HC slot record, and the
        original mechanical attributes, without inventing missing levels.
        """
        matches = self._matches(piece, character_origin)
        if not matches:
            return None, "unknown_enhancement_identity"
        if len(matches) != 1:
            return None, "ambiguous_enhancement_identity"
        uid, _ = matches[0]
        hero = self._hero.get(uid)
        if not isinstance(hero, dict):
            return None, "missing_hero_enhancement"
        result = {"source_uid": uid, "hero_slot": copy.deepcopy(hero), "type": piece["type"]}
        if piece["type"] in ("io-set", "io-generic"):
            if piece.get("level") is not None:
                result["io_level"] = piece["level"]
            result["booster"] = _present_or(piece, "booster", 0)
            if piece["type"] == "io-set":
                result["attuned"] = _present_or(piece, "attuned", False)
        elif piece["type"] in ("special", "origin"):
            result["relative_level"] = _present_or(piece, "relativeLevel", 0)
        return result, None


def _present_or(piece, key, default):
    """SKIF optional fields may be absent or null; both mean the default."""
    value = piece.get(key)
    return default if value is None else value
