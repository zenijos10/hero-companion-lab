"""M6: Pareto dominance and a frontier maintained on every insert.

Pure: no game data, no Flask. Values are the unrounded numbers the
evaluation measures (never S-F grades). Every objective states its direction;
internally each is turned to "higher is better" by its sign, and nothing is
rescaled, so each objective keeps its own meaning.

    A dominates B  iff  A is at least as good as B on every objective
                        and strictly better on at least one.

Two values are EQUAL when they differ by no more than the objective's
tolerance (absolute floor or a share of the larger magnitude, whichever is
bigger), so float noise never decides a dominance. The frontier is exact by
default: it keeps every feasible nondominated candidate it is shown. A size
cap is opt-in; when it bites, the frontier says it is approximate and names
the rule that dropped members.
"""
from dataclasses import dataclass

MAXIMIZE, MINIMIZE = "max", "min"
ABS_TOLERANCE = 1e-9
REL_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Objective:
    key: str
    direction: str = MAXIMIZE
    abs_tolerance: float = ABS_TOLERANCE
    rel_tolerance: float = REL_TOLERANCE

    def __post_init__(self):
        if self.direction not in (MAXIMIZE, MINIMIZE):
            raise ValueError(f"objective {self.key}: direction must be 'max' or 'min'")

    def compare(self, a, b):
        """+1 when a is better than b, -1 when worse, 0 when equal within tolerance."""
        gap = (a - b) if self.direction == MAXIMIZE else (b - a)
        if abs(gap) <= max(self.abs_tolerance, self.rel_tolerance * max(abs(a), abs(b))):
            return 0
        return 1 if gap > 0 else -1


def dominates(a, b, objectives):
    """True when value vector a dominates b ({key: number} each)."""
    better = False
    for obj in objectives:
        verdict = obj.compare(a[obj.key], b[obj.key])
        if verdict < 0:
            return False
        better = better or verdict > 0
    return better


def missing(values, objectives):
    """The objectives a value vector cannot be compared on (absent or not a number)."""
    return [o.key for o in objectives
            if not isinstance(values.get(o.key), (int, float))
            or isinstance(values.get(o.key), bool) or values[o.key] != values[o.key]]


class Frontier:
    """The nondominated set of every candidate inserted, kept current on each
    insert (never a final filtering pass). Members are ordered by fingerprint,
    so the same candidates give the same frontier in any arrival order."""

    def __init__(self, objectives, max_size=None):
        if not objectives:
            raise ValueError("a frontier needs at least one objective")
        keys = [o.key for o in objectives]
        if len(set(keys)) != len(keys):
            raise ValueError("each objective may appear once")
        self.objectives = list(objectives)
        self.max_size = max_size
        self._members = {}             # fingerprint -> (values, payload)
        self.dropped_by_cap = 0

    def insert(self, fingerprint, values, payload=None):
        """('admitted', [removed fingerprints]) | ('dominated', by) |
        ('duplicate', fingerprint) | ('incomparable', [missing keys]) |
        ('capped', max_size) when an opt-in size cap removed it at once."""
        gaps = missing(values, self.objectives)
        if gaps:
            return "incomparable", gaps
        if fingerprint in self._members:
            return "duplicate", fingerprint
        for fp in sorted(self._members):
            if dominates(self._members[fp][0], values, self.objectives):
                return "dominated", fp
        removed = sorted(fp for fp, (v, _) in self._members.items()
                         if dominates(values, v, self.objectives))
        for fp in removed:
            del self._members[fp]
        self._members[fingerprint] = (dict(values), payload)
        self._apply_cap()
        if fingerprint not in self._members:
            return "capped", self.max_size
        return "admitted", removed

    def _apply_cap(self):
        while self.max_size and len(self._members) > self.max_size:
            del self._members[self._most_crowded()]
            self.dropped_by_cap += 1

    def _most_crowded(self):
        """Crowding distance (NSGA-II): the member whose neighbours sit closest
        on every objective, ties broken by fingerprint. Members at either end of
        an objective are never the most crowded."""
        fps = sorted(self._members)
        distance = {fp: 0.0 for fp in fps}
        for obj in self.objectives:
            ranked = sorted(fps, key=lambda fp: (self._members[fp][0][obj.key], fp))
            lo, hi = self._members[ranked[0]][0][obj.key], self._members[ranked[-1]][0][obj.key]
            distance[ranked[0]] = distance[ranked[-1]] = float("inf")
            span = (hi - lo) or 1.0
            for i in range(1, len(ranked) - 1):
                distance[ranked[i]] += (self._members[ranked[i + 1]][0][obj.key]
                                        - self._members[ranked[i - 1]][0][obj.key]) / span
        return min(fps, key=lambda fp: (distance[fp], fp))

    @property
    def approximate(self):
        return self.dropped_by_cap > 0

    def members(self):
        """[(fingerprint, values, payload)] in fingerprint order."""
        return [(fp, v, p) for fp, (v, p) in sorted(self._members.items())]

    def strengths(self, fingerprint):
        """For each other member: the objectives this one is strictly better on,
        i.e. why that member does not dominate it."""
        mine = self._members[fingerprint][0]
        out = {}
        for fp, (theirs, _) in sorted(self._members.items()):
            if fp != fingerprint:
                out[fp] = [o.key for o in self.objectives if o.compare(mine[o.key], theirs[o.key]) > 0]
        return out

    def describe(self):
        return {"exact": not self.approximate, "size": len(self._members),
                "max_size": self.max_size, "dropped_by_cap": self.dropped_by_cap,
                "approximation": ("crowding distance (NSGA-II) removed the most crowded "
                                  f"member each time the frontier passed {self.max_size}")
                if self.approximate else None,
                "objectives": [{"key": o.key, "direction": o.direction,
                                "tolerance": {"absolute": o.abs_tolerance,
                                              "relative": o.rel_tolerance}}
                               for o in self.objectives]}
