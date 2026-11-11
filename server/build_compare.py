"""M5: build scorecards and side-by-side comparison over /build/evaluate.

Pure: takes evaluated columns ({label, evaluation, error}) and returns one
table. Nothing is solved, saved or re-scored here; every number and grade is
the evaluation's own. A comparison names the size of each difference and
flags the ones that matter (a different grade, or a gap of at least
MEANINGFUL_SHARE of the larger value), and never declares an overall winner:
the plan's "no universal composite" rule (M4) holds here too.
"""
import build_ratings

MAX_BUILDS = 4
MEANINGFUL_SHARE = 0.10
LETTERS = ("S", "A", "B", "C", "D", "F")


def _column(entry):
    ev = entry.get("evaluation")
    if not ev:
        return {"label": entry["label"], "ok": False, "error": entry.get("error") or "not evaluated"}
    ratings = ev.get("ratings") or {}
    return {
        "label": entry["label"], "ok": True,
        "archetype": (ev.get("build") or {}).get("archetype"),
        "primary": (ev.get("build") or {}).get("primary"),
        "secondary": (ev.get("build") or {}).get("secondary"),
        "picked_powersets": (ev.get("build") or {}).get("picked_powersets"),
        "rated": ratings.get("status") == "rated",
        "not_rated_reason": ratings.get("reason"),
        "offense_complete": (ev.get("confidence") or {}).get("offense_complete"),
        "unsupported": [{"power": u.get("power"), "reason": u.get("reason")}
                        for u in (ev.get("unsupported") or {}).get("powers") or []],
        "versions": ev.get("versions"),
        "scenario": (ev.get("scenario") or {}).get("id"),
    }


def _cells(entries):
    out = []
    for entry in entries:
        ev = entry.get("evaluation") or {}
        cats = (ev.get("ratings") or {}).get("categories") or {}
        out.append(cats)
    return out


def _row(key, label, unit, per_column):
    cells = []
    for cats in per_column:
        cell = cats.get(key) or {}
        cells.append({"grade": cell.get("grade"), "value": cell.get("value"),
                      "why": cell.get("why"), "detail": cell.get("detail"),
                      "where": cell.get("where"),
                      "low_sample": cell.get("low_sample", False)})
    graded = [i for i, c in enumerate(cells)
              if c["grade"] in LETTERS and isinstance(c["value"], (int, float))]
    row = {"category": key, "label": label, "unit": unit, "cells": cells,
           "best": None, "meaningful": False, "difference": None}
    if len(graded) >= 2:
        values = [cells[i]["value"] for i in graded]
        top = max(values)
        row["best"] = [i for i in graded if cells[i]["value"] == top]
        if len(row["best"]) == len(graded):
            row["best"] = None                      # all equal: nobody leads
        spread = top - min(values)
        scale = max(abs(top), abs(min(values)), 1e-9)
        row["difference"] = round(spread, 3)
        row["meaningful"] = (len({cells[i]["grade"] for i in graded}) > 1
                             or spread / scale >= MEANINGFUL_SHARE)
    return row


SCOPES = {
    "same_powersets": "same archetype and powersets: the builds differ only in picks and slotting",
    "same_archetype": "same archetype, different powersets",
    "cross_archetype": "different archetypes: every grade uses the same all-archetype cut "
                       "points, so a gap can be the archetype rather than the build",
}


def _powersets(column):
    """The powersets a column's picks come from; the request's own primary/secondary
    spelling only when the evaluation did not report them."""
    picked = column.get("picked_powersets")
    return tuple(picked) if picked else (column.get("primary"), column.get("secondary"))


def scope(columns):
    """What a comparison compares, from the evaluated columns (None for a scorecard
    or when fewer than two builds were evaluated)."""
    ok = [c for c in columns if c.get("ok")]
    if len(ok) < 2:
        return None
    if len({c.get("archetype") for c in ok}) > 1:
        return "cross_archetype"
    if len({_powersets(c) for c in ok}) > 1:
        return "same_archetype"
    return "same_powersets"


def _scope_note(kind, columns):
    if kind is None:
        return None
    refused = sum(1 for c in columns if not c.get("ok"))
    if not refused:
        return SCOPES[kind]
    return (f"{SCOPES[kind]} (among the {len(columns) - refused} evaluated builds; "
            f"{refused} could not be evaluated and are not part of it)")


def compare(entries):
    """One table for 1..MAX_BUILDS evaluated builds."""
    columns = [_column(e) for e in entries]
    per_column = _cells(entries)
    rows = [_row(key, spec[0], spec[2], per_column)
            for key, spec in build_ratings.CATEGORIES.items()]
    kind = scope(columns)
    return {
        "ok": any(c["ok"] for c in columns),
        "mode": "scorecard" if len(columns) == 1 else "comparison",
        "scope": kind,
        "scope_note": _scope_note(kind, columns),
        "columns": columns,
        "rows": rows,
        "notes": [
            "Read-only: nothing was solved or saved.",
            "Grades are PROVISIONAL: fixed cut points set from optimized itrial champions "
            "as a guideline, not player-population percentiles.",
            "A difference is flagged when the grades differ or the gap is at least "
            f"{int(MEANINGFUL_SHARE * 100)}% of the larger value. No overall winner is "
            "declared: builds trade categories against each other.",
        ],
    }
