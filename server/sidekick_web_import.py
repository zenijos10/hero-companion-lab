"""Pure, guarded adapter between Sidekick reconstruction and HC import UI.

No user-controlled filesystem paths, save writes, or editor mutations here.
The caller supplies an administrator-configured local Sidekick contract and
the same native legality validator already used by /build/validate.
"""
import copy

from sidekick_reconstruct import reconstruct_build


def _refusal(code, message, **details):
    return {"ok": False, "code": code, "response": message, **details}


def prepare_sidekick_import(payload, contract_root, power_index, powersets,
                            piece_index, validate):
    """Return a ready-to-display native build *only* after both gates pass.

    The source document is not returned in the browser response. No native
    build is returned if either identity/state reconstruction or legality fails.
    """
    if not contract_root:
        return _refusal(
            "sidekick_contract_unavailable",
            "Sidekick import requires local Homecoming compatibility data. "
            "Configure HC_SIDEKICK_CONTRACT_DIR to a Sidekick contract/homecoming "
            "folder and restart Hero Companion. Existing builds were not changed.")
    if not isinstance(payload, dict):
        return _refusal("sidekick_invalid_request", "Expected a Sidekick import request.")
    skif = payload.get("skif")
    if not isinstance(skif, (str, dict)) or not skif:
        return _refusal("sidekick_invalid_request", "Choose a nonempty Sidekick .skif v5 file.")
    if isinstance(skif, str) and len(skif) > 2_000_000:
        return _refusal("sidekick_invalid_request", "Sidekick file exceeds the 2 MB safety limit.")
    default_level = payload.get("default_io_level")
    if default_level is not None and (type(default_level) is not int
                                      or not 1 <= default_level <= 50):
        return _refusal("sidekick_invalid_request",
                        "Sidekick default IO level must be a whole number from 1 to 50.")
    if "pvp" in payload and type(payload["pvp"]) is not bool:
        return _refusal("sidekick_invalid_request", "PvP flag must be true or false.")
    try:
        reconstructed = reconstruct_build(
            skif, power_index, powersets, contract_root, piece_index,
            default_io_level=default_level)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        return _refusal("sidekick_invalid_file", f"Sidekick import refused: {exc}")
    if not reconstructed["ok"]:
        issues = reconstructed.get("issues") or []
        reason = issues[0].get("reason") if issues else "unknown"
        return _refusal(
            "sidekick_unresolved",
            f"Sidekick build is not safe to import: {reason}. "
            "Nothing was changed; see issues for the exact fields.",
            issues=copy.deepcopy(issues))
    native = copy.deepcopy(reconstructed["build"])
    if "pvp" in payload:
        native["pvp"] = payload["pvp"]
    legal = validate(copy.deepcopy(native))
    errors = legal.get("errors") or []
    warnings = legal.get("warnings") or []
    if errors:
        return _refusal(
            "sidekick_illegal_build",
            "Sidekick build could not pass Hero Companion's legality checks. "
            "The current build is unchanged.",
            errors=copy.deepcopy(errors), warnings=copy.deepcopy(warnings))
    return {"ok": True, "name": reconstructed["name"],
            "build": native, "warnings": copy.deepcopy(warnings)}
