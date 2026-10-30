"""Import lookups: resolve an imported enhancement (by uid or "Set: Piece" name) -> slot.

Pure data, no Flask: the server builds its lookups here, and offline tools
(tools/preview_skif.py) reuse the same copy instead of re-deriving it.
"""

# ⚠ SPECIAL ORIGINS ARE SLOTTABLE PIECES AND MUST RESOLVE BY NAME (2026-08-05).
# They live in common_ios.json, not ENH_SETS, so the set loop never saw them —
# and both importers' uid rung missed, fell through to the generic common-IO
# fallback, and labelled the slot with its own uid: a re-imported .mbd showed
# "Hamidon_Damage_Accuracy" where the app had written "Nucleolus Exposure", with
# the set line blank. Math was never affected (the engine prices by piece_uid,
# proven by identical totals across a round trip) — this is the naming rule:
# never label a piece from its internal name. Registered in PIECE_BY_UID because
# that is where both importers AND the ⓘ image lookup already read; the labels
# match the ones proc_pass/solver already emit, so a hand-placed HO and an
# imported one are the same object. No PIECE_REF_LEVEL (HO values are grade-flat).
_SPECIAL_ORIGIN_SETS = {"Hamidon": ("Hamidon_Origin", "Hamidon Origin"),
                        "Hydra": ("Hydra_Origin", "Hydra Origin"),
                        "Titan": ("Titan_Origin", "Titan Origin"),
                        "Dsync": ("DSync_Origin", "D-Sync Origin"),
                        "DSync": ("DSync_Origin", "D-Sync Origin")}


def build_piece_lookups(enh_sets, common_ios):
    """Return (piece_by_uid, name_to_piece) for set pieces and special origins."""
    piece_by_uid = {}        # piece uid -> slot dict
    name_to_piece = {}       # "set name: piece name" (lower) -> slot dict
    for s in enh_sets:
        for pc in s["pieces"]:
            if not pc.get("uid"):
                continue
            slot = {"set_uid": s["uid"], "set_name": s["name"],
                    "piece_uid": pc["uid"], "piece_name": pc["name"],
                    "category_id": s.get("category_id"),
                    "image": pc.get("image") or s.get("image") or ""}
            piece_by_uid[pc["uid"]] = slot
            name_to_piece[f"{s['name']}: {pc['name']}".lower()] = slot
    for c in common_ios.get("special_ios", []):
        if not c.get("uid"):
            continue
        suid, sname = _SPECIAL_ORIGIN_SETS.get(c["uid"].split("_")[0], (None, None))
        if not suid:
            continue
        piece_by_uid[c["uid"]] = {"set_uid": suid, "set_name": sname,
                                  "piece_uid": c["uid"], "piece_name": c.get("name") or c["uid"],
                                  "category_id": None, "image": c.get("image") or ""}
    return piece_by_uid, name_to_piece


def build_import_aliases(piece_by_uid):
    """Return the IMPORT-ONLY uid map: every real uid plus its Crafted_/Attuned_ twin.

    ⚠ ATTUNED COPIES MUST RESOLVE (field report 2026-09-19, ChainsawHands): the
    in-game export writes an attuned piece as "Attuned_Touch_of_Death_F" while our
    catalog carries only "Crafted_Touch_of_Death_F" (the parser keeps whichever
    prefix it saw) — both importers missed the uid and the slot rendered EMPTY.
    Alias the pair in BOTH directions; never across Superior_ (Superior Winter's
    Bite is a DIFFERENT set with different values). A slot's "attuned" flag still
    comes from the original uid at the call site.
    This is a SEPARATE map on purpose: aliases share the same slot object, so
    folding them into piece_by_uid would make .values() yield every piece twice —
    and the solver/test helpers that enumerate pieces would slot duplicates.
    """
    aliases = {}
    for uid, slot in piece_by_uid.items():
        for a, b in (("Crafted_", "Attuned_"), ("Attuned_", "Crafted_")):
            if uid.startswith(a):
                aliases[b + uid[len(a):]] = slot
    aliases.update(piece_by_uid)     # a real uid always outranks an alias
    return aliases
