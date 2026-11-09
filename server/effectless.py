"""Classify the player-pickable powers whose record carries NO effect rows.

Read-only. This decides nothing about game math: it sorts each effect-less
pick into a class from evidence already in the shipped data, so the rating
layer knows which ones hide damage (a rating-release blocker, owner review of
PR #25) and which are mechanics that legitimately carry nothing.

THE ONE COPY: tools/classify_effectless_powers.py writes the report from it,
and build_evaluation reads it per build.

Evidence, in the order the rules apply (first match wins):
  auto_granted        level_available < 1: the game issues it, never a pick
                      (Bio's stances, Dual Pistols ammo swaps; CLAUDE.md
                      `_pickable`).
  modeled_elsewhere   a Mastermind upgrade, priced by its re-cast time
                      (first_principles.mastermind_upgrade_records).
  unread_twins        the power's pet_powersets name records IN OUR DATA that
                      carry the effects (Archery Ranged Shot ->
                      Redirects.Blaster_Archery.Ranged_Shot_Quick/_Normal).
                      Readable today; nothing reads them.
  damaging_unread     the game's own short help says DMG/DoT, or the power
                      accepts Damage Increase, and no twin is found.
  mechanic            accepts no enhancement at all (Swap Ammo, Staff
                      Mastery, Fate Sealed class): a mode switch.
  effect_unread       everything else: the help text names an effect we
                      do not carry.
"""
import re

import first_principles

EFFECT_KEYS = ("self_effects", "damage_effects", "strength_effects", "debuff_effects",
               "control_effects", "buff_effects", "heal_effects", "summons")
DAMAGING = ("unread_twins_damage", "damaging_unread")
# DMG(...) / DoT(...) the power deals; NOT "+DMG(All)", a damage BUFF.
_HELP_DAMAGE = re.compile(r"(?<![+\w])(DMG|DoT)\s*\(")
MASTERMIND_SUMMON = "Mastermind_Summon."


def has_effects(rec):
    return any(rec.get(k) for k in EFFECT_KEYS)


def _short_help(help_entry):
    if isinstance(help_entry, (list, tuple)) and help_entry:
        return help_entry[0] or ""
    return help_entry if isinstance(help_entry, str) else ""


def _twins(fn, rec, records_by_set):
    """Records in the power's own pet_powersets whose name starts with the
    power's leaf name and carry effects (the client's redirect convention)."""
    leaf = fn.rsplit(".", 1)[-1].lower()
    found = []
    for ps in rec.get("pet_powersets") or []:
        for twin in records_by_set.get(ps) or []:
            name = twin["full_name"].rsplit(".", 1)[-1].lower()
            if name.startswith(leaf) and has_effects(twin):
                found.append(twin)
    return found


def is_mastermind_upgrade(fn, rec, siblings):
    """encounter_value prices upgrades only for a build with henchmen, so the
    rule applies to Mastermind summon sets alone (Storm Blast also has a summon,
    and its Direct Strike is an attack, not an upgrade)."""
    if not (rec.get("powerset_full_name") or "").startswith(MASTERMIND_SUMMON):
        return False
    return fn in {r.get("full_name") for r in
                  first_principles.mastermind_upgrade_records(siblings)}


def classify(rec, records_by_set, help_entry=None, full_name=None):
    """The class of one effect-less record, with its evidence; None when the
    record carries effects (nothing to classify)."""
    if has_effects(rec):
        return None
    fn = full_name or rec.get("full_name") or ""
    short = _short_help(help_entry)
    if (rec.get("level_available") or 0) < 1:
        return {"class": "auto_granted", "evidence": "level_available < 1 (never a pick)"}
    if is_mastermind_upgrade(fn, rec, records_by_set.get(rec.get("powerset_full_name")) or []):
        return {"class": "modeled_elsewhere",
                "evidence": "Mastermind upgrade: priced by its re-cast time"}
    twins = _twins(fn, rec, records_by_set)
    if twins:
        damaging = any(t.get("damage_effects") for t in twins)
        return {"class": "unread_twins_damage" if damaging else "unread_twins",
                "evidence": "effects live on " + ", ".join(t["full_name"] for t in twins),
                "twins": [t["full_name"] for t in twins]}
    accepts = rec.get("accepted_enhancement_types") or []
    if _HELP_DAMAGE.search(short) or "Damage Increase" in accepts:
        return {"class": "damaging_unread",
                "evidence": f"help: {short!r}" if short else "accepts Damage Increase"}
    if not accepts:
        return {"class": "mechanic", "evidence": "accepts no enhancement (a mode switch)"}
    return {"class": "effect_unread",
            "evidence": f"help: {short!r}" if short else "accepts " + ", ".join(accepts)}


def pickable_records(powers_by_set, powersets):
    """Every record in a set some archetype is offered (primary, secondary,
    epic, pools) plus the inherent sets: the records a build can contain."""
    offered = {ps["full_name"] for sets in (powersets.get("by_archetype") or {}).values()
               for group in sets.values() for ps in group}
    offered |= {ps["full_name"] for ps in powersets.get("pools") or []}
    offered |= {name for name in powers_by_set if name.startswith("Inherent.")}
    return [rec for name in sorted(offered) for rec in powers_by_set.get(name) or []]


def catalogue(powers_by_set, powersets, power_help):
    """Every effect-less pickable record with its class, sorted by name."""
    rows = []
    for rec in pickable_records(powers_by_set, powersets):
        verdict = classify(rec, powers_by_set, (power_help or {}).get(rec["full_name"]))
        if verdict:
            rows.append(dict(verdict, power=rec["full_name"],
                             display_name=rec.get("display_name")))
    return sorted(rows, key=lambda r: r["power"])
