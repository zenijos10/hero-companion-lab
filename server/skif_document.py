"""Lossless, data-independent JSON boundary for CoH Sidekick SKIF v5.

This is *not* a Hero Companion game-data resolver. Unknown vocabulary and
future fields survive; unsupported structural changes are refused. No Sidekick
runtime, Rust source, or third-party data is embedded here.
"""

import copy
import json


class SkifFormatError(ValueError):
    """An unsupported or malformed SKIF document (never a partial build)."""


def _fail(where, expected):
    raise SkifFormatError(f"{where}: expected {expected}")


def _object(value, where):
    if not isinstance(value, dict):
        _fail(where, "object")
    return value


def _list(value, where):
    if not isinstance(value, list):
        _fail(where, "array")
    return value


def _string(value, where, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value):
        _fail(where, "string" if allow_empty else "nonempty string")


def _integer(value, where, low, high):
    if type(value) is not int or not low <= value <= high:
        _fail(where, f"integer between {low} and {high}")


def _optional_string(record, key, where):
    if key in record and record[key] is not None:
        _string(record[key], f"{where}.{key}", allow_empty=True)


def _optional_bool(record, key, where):
    if record.get(key) is not None and type(record[key]) is not bool:
        _fail(f"{where}.{key}", "boolean")


def _optional_integer(record, key, where, low, high):
    if key in record and record[key] is not None:
        _integer(record[key], f"{where}.{key}", low, high)


def _enhancement(slot, where):
    slot = _object(slot, where)
    kind = slot.get("type")
    required = {
        "io-set": ("setId", "pieceNum"),
        "io-generic": ("stat",),
        "special": ("category", "id"),
        "origin": ("stat", "tier"),
    }
    if not isinstance(kind, str) or kind not in required:
        _fail(f"{where}.type", "one of io-set, io-generic, special, origin")
    for key in required[kind]:
        if key == "pieceNum":
            _integer(slot.get(key), f"{where}.{key}", 0, 255)
        else:
            _string(slot.get(key), f"{where}.{key}")
    if kind in ("io-set", "io-generic"):
        _optional_integer(slot, "level", where, 1, 50)
        _optional_integer(slot, "booster", where, 0, 255)
        if kind == "io-set":
            _optional_bool(slot, "attuned", where)
    else:
        _optional_integer(slot, "relativeLevel", where, -128, 127)


def _power(power, where):
    power = _object(power, where)
    _string(power.get("internalName"), f"{where}.internalName")
    _integer(power.get("level"), f"{where}.level", 0, 50)
    for i, slot in enumerate(_list(power.get("slots"), f"{where}.slots")):
        if slot is not None:
            _enhancement(slot, f"{where}.slots[{i}]")
    _optional_string(power, "powerset", where)
    _optional_string(power, "activeSubPower", where)
    _optional_bool(power, "isActive", where)


def _selection(selection, where):
    selection = _object(selection, where)
    _string(selection.get("id"), f"{where}.id")
    for i, power in enumerate(_list(selection.get("powers", []), f"{where}.powers")):
        _power(power, f"{where}.powers[{i}]")


def _string_map(build, key):
    if key not in build:
        return
    for k, v in _object(build[key], f"build.{key}").items():
        _string(k, f"build.{key}.key")
        if type(v) is not bool:
            _fail(f"build.{key}.{k}", "boolean")


def _validate(document):
    _object(document, "file")
    if type(document.get("version")) is not int or document["version"] != 5:
        _fail("version", "SKIF v5")
    build = _object(document.get("build"), "build")
    _string(build.get("dataset"), "build.dataset")
    _integer(build.get("level"), "build.level", 1, 50)
    for key in ("name", "archetype", "origin"):
        _optional_string(build, key, "build")
    for key in ("primary", "secondary", "epicPool"):
        if build.get(key) is not None:
            _selection(build[key], f"build.{key}")
    for i, selection in enumerate(_list(build.get("pools", []), "build.pools")):
        _selection(selection, f"build.pools[{i}]")
    for i, power in enumerate(_list(build.get("inherents", []), "build.inherents")):
        _power(power, f"build.inherents[{i}]")
    for key in ("stances", "modes", "powerState"):
        _string_map(build, key)
    if "procOverrides" in build:
        for address, raw in _object(build["procOverrides"], "build.procOverrides").items():
            _string(address, "build.procOverrides.key")
            override = _object(raw, f"build.procOverrides.{address}")
            if type(override.get("enabled")) is not bool:
                _fail(f"build.procOverrides.{address}.enabled", "boolean")
            _string(override.get("mode"), f"build.procOverrides.{address}.mode")
    if "incarnates" in build:
        for slot, raw in _object(build["incarnates"], "build.incarnates").items():
            _string(slot, "build.incarnates.key")
            inc = _object(raw, f"build.incarnates.{slot}")
            _string(inc.get("power"), f"build.incarnates.{slot}.power")
            if type(inc.get("active")) is not bool:
                _fail(f"build.incarnates.{slot}.active", "boolean")
    if "attackChains" in build:
        for i, raw in enumerate(_list(build["attackChains"], "build.attackChains")):
            chain = _object(raw, f"build.attackChains[{i}]")
            _string(chain.get("id"), f"build.attackChains[{i}].id")
            _string(chain.get("name"), f"build.attackChains[{i}].name", allow_empty=True)
            for j, p in enumerate(_list(chain.get("powers"), f"build.attackChains[{i}].powers")):
                _string(p, f"build.attackChains[{i}].powers[{j}]")
    for key in ("accolades", "disabledProcCategories"):
        if key in build:
            for i, value in enumerate(_list(build[key], f"build.{key}")):
                _string(value, f"build.{key}[{i}]")
    if "slotOrder" in build:
        for i, raw in enumerate(_list(build["slotOrder"], "build.slotOrder")):
            entry = _object(raw, f"build.slotOrder[{i}]")
            _string(entry.get("powerName"), f"build.slotOrder[{i}].powerName")
            _integer(entry.get("slotIndex"), f"build.slotOrder[{i}].slotIndex", 0, 255)
            for key in ("category", "levelSource"):
                _optional_string(entry, key, f"build.slotOrder[{i}]")
            _optional_integer(entry, "level", f"build.slotOrder[{i}]", 1, 50)
    if build.get("whatIfBuffs") is not None:
        raise SkifFormatError("build.whatIfBuffs: unsupported what-if layer")
    if document.get("authoredAgainst") is not None:
        stamp = _object(document["authoredAgainst"], "authoredAgainst")
        _string(stamp.get("dataset"), "authoredAgainst.dataset")
        if stamp["dataset"] != build["dataset"]:
            raise SkifFormatError("authoredAgainst.dataset disagrees with build.dataset")
        for key in ("contractSchema", "datasetSchema"):
            _integer(stamp.get(key), f"authoredAgainst.{key}", 0, 2**32-1)
        _optional_string(stamp, "exportCommit", "authoredAgainst")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SkifFormatError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise SkifFormatError(f"invalid JSON number: {value}")


def load_document(source):
    """Read SKIF text or an object without mutating or discarding unknown fields."""
    if isinstance(source, str):
        try:
            document = json.loads(source, object_pairs_hook=_unique_object,
                                  parse_constant=_invalid_constant)
        except (ValueError, TypeError) as exc:
            raise SkifFormatError(f"invalid SKIF JSON: {exc}") from exc
    else:
        document = copy.deepcopy(source)
    _validate(document)
    return document


def dump_document(document):
    """Emit a deterministic, UTF-8-safe SKIF v5 JSON string with a final newline."""
    safe = load_document(document)
    try:
        return json.dumps(safe, ensure_ascii=False, sort_keys=True,
                          allow_nan=False, indent=2) + "\n"
    except (ValueError, TypeError) as exc:
        raise SkifFormatError(f"invalid SKIF value: {exc}") from exc
