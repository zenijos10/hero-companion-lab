"""STRENGTHS, WEAKNESSES AND A LANE (owner, 2026-11-14: "have a section for
weaknesses and strengths, talk about which types of attacks and debuffs or
defenses/resists the character is weak with and strong with. Help to pick a
lane").

Read from what the evaluation already measured and graded; nothing new is
modelled here, so every sentence points at a number the scorecard shows.

  lanes        each lane is a set of graded categories (LANES); its average_points
               is the mean grade (S 5 .. F 0, None 0: the build has none of it;
               Unknown and N/A skipped). The best lane is the suggestion; the
               weakest graded part of it says what to improve to lean further in.
  taking hits  the toughness grid (damage per second outlasted per position and
               type): the types and positions well above or below the build's
               own typical cell (STRONG_RATIO / WEAK_RATIO of the median).
  debuffs      defense debuff resistance and slow resistance, from their grades.
  damage       the damage types the build deals, and the enemy groups that
               resist it hardest (matchups: your damage not resisted).
  groups       the hardest and how many of the 106 groups the build outlasts.
Rating only: nothing here feeds the champion score.
"""
import statistics

POINTS = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "F": 0, "None": 0}
LETTERS = ("F", "D", "C", "B", "A", "S")
STRONG_GRADES, WEAK_GRADES = ("S", "A"), ("D", "F")
STRONG_RATIO, WEAK_RATIO = 1.25, 0.75   # a type/position stands out at +-25% of the median cell
RESISTED_AT = 0.8                       # a group resists you when 20%+ of your damage is lost

# (id, label, what the lane does in a team, graded categories)
LANES = (
    ("alpha", "Alpha striker", "opens fights by deleting a spawn or a boss in a few seconds",
     ("strike_aoe", "strike_single_target")),
    ("area", "Area damage", "keeps whole spawns melting fight after fight",
     ("aoe_damage", "strike_aoe")),
    ("single", "Single-target damage", "takes down bosses, elite bosses and AVs",
     ("single_target_damage", "strike_single_target")),
    ("tank", "Tank", "holds the spawn's attention and soaks the alpha",
     ("toughness", "resistance", "defense", "debuff_resist_defense")),
    ("control", "Controller", "locks spawns down so they cannot fight back",
     ("control_aoe", "control_single_target")),
    ("support", "Support", "buffs the team and debuffs the enemy",
     ("support_index",)),
    ("healer", "Healer", "keeps the team standing",
     ("healing",)),
)


def _letter(points):
    """The grade an average reaches, halves rounding up (1.5 -> C, 2.5 -> B);
    Python's round() rounds halves to even and would read 2.5 as C."""
    return LETTERS[max(0, min(5, int(points + 0.5)))]


def lanes(categories):
    """Every lane with its average grade points, best first ([] when nothing is
    graded). Never a key named `score`: that word is the champion score's alone."""
    out = []
    for lane_id, label, does, keys in LANES:
        graded = [(k, (categories.get(k) or {}).get("grade")) for k in keys]
        scored = [(k, g) for k, g in graded if g in POINTS]
        if not scored:
            continue
        score = sum(POINTS[g] for _k, g in scored) / len(scored)
        weakest = min(scored, key=lambda kg: POINTS[kg[1]])
        out.append({"id": lane_id, "label": label, "does": does, "average_points": round(score, 2),
                    "grade": _letter(score),
                    "parts": [{"category": k, "label": (categories.get(k) or {}).get("label") or k,
                               "grade": g} for k, g in scored],
                    "weakest_part": {"category": weakest[0], "grade": weakest[1],
                                     "label": (categories.get(weakest[0]) or {}).get("label")
                                     or weakest[0]}})
    out.sort(key=lambda lane: (-lane["average_points"], lane["id"]))
    return out


def _graded(categories, grades):
    rows = [(k, c) for k, c in categories.items() if c.get("grade") in grades]
    rows.sort(key=lambda kc: (-POINTS[kc[1]["grade"]] if kc[1]["grade"] in STRONG_GRADES
                              else POINTS[kc[1]["grade"]], kc[1].get("label") or kc[0]))
    return [{"category": k, "label": c.get("label") or k, "grade": c["grade"]} for k, c in rows]


def taking_hits(grid):
    """The damage types and positions the build takes well or badly, relative
    to its own typical cell (None when the grid is missing)."""
    if not grid:
        return None
    cells = [v for row in grid.values() for v in row.values() if isinstance(v, (int, float))]
    if not cells:
        return None
    median = statistics.median(cells)
    types = sorted({t for row in grid.values() for t in row})
    by_type = {t: statistics.mean(grid[p][t] for p in grid if t in grid[p]) for t in types}
    by_pos = {p: statistics.mean(row.values()) for p, row in grid.items()}

    def pick(table, test):
        return [{"name": k, "damage_per_second": round(v, 1)}
                for k, v in sorted(table.items(), key=lambda kv: (-kv[1], kv[0])) if test(v)]
    return {"typical_damage_per_second": round(median, 1),
            "strong_types": pick(by_type, lambda v: v >= median * STRONG_RATIO),
            "weak_types": list(reversed(pick(by_type, lambda v: v <= median * WEAK_RATIO))),
            "strong_positions": _stand_out(pick(by_pos, lambda v: v >= median * STRONG_RATIO), by_pos),
            "weak_positions": _stand_out(list(reversed(pick(by_pos, lambda v: v <= median * WEAK_RATIO))),
                                         by_pos)}


def _stand_out(rows, table):
    """A position only stands out when the others do not share it: every
    position strong (or weak) says the types decide, not where the hit comes from."""
    return rows if len(rows) < len(table) else []


def _names(rows, n=3):
    """'Fire', 'Fire and Cold', 'Fire, Cold and Toxic'."""
    names = [r["name"] for r in rows[:n]]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def summary(evaluation):
    """The strengths-and-weaknesses block for one evaluation."""
    ratings = evaluation.get("ratings") or {}
    categories = ratings.get("categories") or {}
    if ratings.get("status") != "rated":
        return {"rated": False, "reason": ratings.get("reason") or "the build is not rated",
                "basis": "lanes and graded strengths need the S-F grades"}
    m = evaluation.get("measurements") or {}
    surv = m.get("survival") or {}
    offense = m.get("offense") or {}
    ranked = lanes(categories)
    hits = taking_hits((surv.get("toughness") or {}).get("by_position_and_type"))
    strengths, weaknesses = [], []

    if hits:
        if hits["strong_types"]:
            strengths.append(f"Takes {_names(hits['strong_types'])} damage well "
                             f"(about {hits['strong_types'][0]['damage_per_second']:g} dmg/s outlasted, "
                             f"against a typical {hits['typical_damage_per_second']:g}).")
        if hits["weak_types"]:
            weaknesses.append(f"Weak to {_names(hits['weak_types'])} damage "
                              f"(about {hits['weak_types'][0]['damage_per_second']:g} dmg/s outlasted, "
                              f"against a typical {hits['typical_damage_per_second']:g}).")
        if hits["weak_positions"]:
            weaknesses.append(f"{_names(hits['weak_positions'])} attacks hurt most "
                              f"({hits['weak_positions'][0]['damage_per_second']:g} dmg/s outlasted).")
        if hits["strong_positions"]:
            strengths.append(f"Shrugs off {_names(hits['strong_positions'])} attacks "
                             f"({hits['strong_positions'][0]['damage_per_second']:g} dmg/s outlasted).")

    ddr = (categories.get("debuff_resist_defense") or {}).get("grade")
    defense = (categories.get("defense") or {}).get("grade")
    if ddr in STRONG_GRADES:
        strengths.append("Resists defense debuffs well, so its defense holds up in long fights.")
    elif defense in ("S", "A", "B") and ddr in ("D", "F", "None"):
        weaknesses.append("Relies on defense with little defense debuff resistance: a few landed "
                          "-Defense hits let more hits through (the cascade).")
    slow = (categories.get("debuff_resist_slow") or {}).get("grade")
    if slow in STRONG_GRADES:
        strengths.append("Resists slows and -Recharge well.")

    types = offense.get("damage_types") or []
    groups = (evaluation.get("matchups") or {}).get("groups") or []
    if types:
        main = [t["type"] for t in types[:2] if (t.get("damage_share") or 0) >= 0.15]
        resisting = sorted((g for g in groups if isinstance(g.get("your_damage_unresisted"), (int, float))
                            and g["your_damage_unresisted"] < RESISTED_AT),
                           key=lambda g: (g["your_damage_unresisted"], g.get("name") or ""))
        if main and len(main) == 1 and (types[0].get("damage_share") or 0) >= 0.8:
            text = f"Deals almost all {main[0]} damage"
        elif main:
            text = f"Deals mostly {' and '.join(main)} damage"
        else:
            text = None
        if text and resisting:
            names = ", ".join(f"{g['name']} ({round((1 - g['your_damage_unresisted']) * 100)}% resisted)"
                              for g in resisting[:3])
            weaknesses.append(f"{text}; groups that resist it: {names}.")
        elif text:
            strengths.append(f"{text}, and no enemy group resists 20% or more of it.")

    if groups:
        hardest = [g for g in groups if not g.get("outlasts")][:3]
        outlasted = sum(1 for g in groups if g.get("outlasts"))
        line = f"Outlasts {outlasted} of {len(groups)} enemy groups in a +4 spawn"
        if hardest:
            worst = ", ".join(f"{g['name']} ({', '.join(t['type'] for t in g.get('their_damage') or [])})"
                              for g in hardest)
            weaknesses.append(f"{line}; hardest: {worst}.")
        else:
            strengths.append(line + ".")

    best = ranked[0] if ranked else None
    advice = None
    if best:
        tip = (f" Its weakest part there is {best['weakest_part']['label']} "
               f"({best['weakest_part']['grade']}): improving that leans further into the lane."
               if POINTS.get(best["weakest_part"]["grade"], 5) < POINTS["A"] else "")
        others = [lane["label"] for lane in ranked[1:] if lane["average_points"] >= POINTS["B"]]
        also = f" Also suited to: {', '.join(others)}." if others else ""
        advice = (f"Best lane: {best['label']} ({best['grade']} average), a build that "
                  f"{best['does']}.{also}{tip}")
    profile = (evaluation.get("range_profile") or {}).get("profiles", {}).get("overall")
    where = None
    if profile:
        band = max(profile, key=lambda b: profile[b])
        where = {"melee": "up close, in melee", "midrange": "at midrange, around the spawn",
                 "range": "from range"}[band] + f" ({round(profile[band] * 100)}% of its output)"
    return {"rated": True, "lanes": ranked, "advice": advice, "operates": where,
            "strong_categories": _graded(categories, STRONG_GRADES),
            "weak_categories": _graded(categories, WEAK_GRADES),
            "taking_hits": hits, "strengths": strengths, "weaknesses": weaknesses,
            "basis": "lanes: the mean grade of each lane's categories (S 5 .. F 0; None 0; "
                     "Unknown and N/A skipped); taking hits: the toughness grid's types and "
                     "positions 25% above or below the build's typical cell; damage: the "
                     "matchups' unresisted share (server/strengths.py)"}
