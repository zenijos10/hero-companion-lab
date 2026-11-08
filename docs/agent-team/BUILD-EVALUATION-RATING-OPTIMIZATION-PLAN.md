# COH Builder Lab — Build Evaluation, Rating, Comparison & Pareto Optimization Plan

**Status:** Requirements / proposed delivery plan; implementation audit pending  
**Priority:** P0 for trustworthy measurement and player-visible ratings; P1 for comparison UI and multi-objective optimization  
**Created:** 2026-11-08  
**Repository:** hero-companion-lab (the fork; do not alter upstream)  
**Integration:** Hero Companion / COH Sidekick-compatible build workflow  
**Owner approval boundary:** Feature branches and PRs allowed; NEVER merge to master without explicit approval.

## 0. Why this document exists

Importing/exporting builds and generating valid optimized builds are not the finished product. The missing product requirement is **rating an existing build**: telling a player *what it does*, *how good it is at each task*, *how it compares to relevant alternatives*, and *what improvements trade away*.

This is an ADDITIVE scope specification, not a claim that Hero Companion has no scoring today. This repository already has a deterministic physics model, champion/context scoring, benchmarks, and an ILP optimizer. **Audit and reuse those implementations**; do not replace them or assert that any backlog item is absent until code and tests establish the gap.

Referenced repo guidance:
- docs/agent-team/STANDARDS.md and WORKFLOW.md: TDD, independent review, feature branches, user-approved merges.
- docs/architecture.md: model/data versions, deterministic offline client, champion scoring.
- docs/roles-and-context.md and build-doctrine.md: content/playstyle dependence and game-derived mechanics.
- docs/KNOWN-GAPS.md: generated, authoritative ledger of known modeling gaps (do not edit manually).
- AGENTS.md / CLAUDE.md: higher-priority repository instructions and game-client authority.

**Definition of done:** An ordinary imported Sidekick build can be evaluated; receives interpretable, category-specific ratings relative to meaningful baselines; can be compared to other builds and relevant archetypes; and can be optimized for user-selected goals with multiple Pareto-nondominated alternatives. The tool explains its assumptions and exports legal alternatives.

## 1. Product and engineering principles

1. **Multidimensional, not one magic number.** Damage, defense, resistance, sustain, recharge, buffing, debuffing, healing, and control remain separately visible. Existing internal canonical/champion scores may continue to serve solver/certification purposes, but must not be mistaken for a comprehensive player-facing rating.
2. **Rate the capability, not the stereotype.** A Mastermind with outstanding defense receives credit for that defense, irrespective of conventional archetype role. Lack of irrelevant healing is not an automatic defect in a damage specialist.
3. **Three comparison scopes.** Show standings versus (a) same primary + secondary powersets within archetype, (b) same archetype, and (c) all archetypes; provide the evaluated context and comparable scenario for each.
4. **Context is part of the input.** Solo, team, league, farms, AVs, target counts, encounter duration and +level materially affect measurements. Default to +4 enemies for the agreed combat-facing comparison scenario; explicitly label other content-specific presets.
5. **Use real performance quantities.** Ratings and dominance compare modeled DPS, uptime, mitigation, etc., not arbitrary enhancement rarity, slot counts, or coarse letter grades.
6. **Explain the measurement.** Provide metric, unit, assumptions, benchmark, uncertainty/unsupported mechanics, game database version, model version and scoring/rating version.
7. **Pareto tradeoffs are primary.** No universally best build exists across incompatible goals. Preserve meaningful nondominated alternatives throughout search, not only in a final postprocessing pass.
8. **Deterministic and offline.** Identical build, ruleset, scenario, and search inputs yield identical results without LLM calls or remote services.
9. **Source of truth.** Homecoming game-client mechanics outrank guesswork; champion/master builds are evidence, not invented rules. Known unmodeled mechanics remain disclosed.
10. **Build on what exists.** Reuse current scorer/optimizer/benchmarks and current Sidekick import/export where fit for purpose.

## 2. Delivery sequence and dependencies

| Milestone | Priority | Output | Depends on |
| --- | --- | --- | --- |
| M1 — Repository audit and traceability | P0 | Verified complete/partial/missing/blocked inventory | None |
| M2 — Measurement coverage and correctness | P0 | Scenario-aware, testable performance metrics | M1 |
| M3 — Team support measurement | P0 | Structured buff/debuff/heal/control metrics | M2 shared measurement contracts |
| M4 — Benchmarks and tier ratings | P0 | Explainable S/A/B/C/D/F category ratings, three scopes | M2, M3 |
| M5 — Player comparison UX | P1 | Import → scorecard → compare workflow | M4 |
| M6 — Multi-objective Pareto search | P1 | Maintained nondominated candidate frontier and alternatives | M2–M4, build legality |
| M7 — Integration and validation | P1 | Sidekick-compatible, offline end-to-end workflow | M5, M6 |

M5 and M6 may run in parallel after shared measurement and rating interfaces stabilize. Do NOT re-run expensive whole-roster certification without authorization.

## M1 — Audit the existing implementation (P0)

- [ ] Inspect current branch, merged/open PRs, importer/exporter, scorer, models, optimizer, benchmarks, and UI.
- [ ] Map each requirement below to existing source files, tests, endpoints and visible behavior.
- [ ] Classify each item: **Verified complete**, **Partial**, **Missing**, **Blocked by game knowledge**, or **Design decision pending**.
- [ ] Distinguish already-implemented canonical/champion objective scores from the requested user-visible category ratings.
- [ ] Assess whether same-powerset, same-archetype and global comparison populations exist, are versioned, and are meaningfully representative.
- [ ] Check known modeling gaps against docs/KNOWN-GAPS.md and CLAUDE.md before suggesting mechanical changes.
- [ ] File tracked issues for verified gaps; link them to milestones; avoid duplicate work.
- [ ] Establish a thin, versioned evaluation contract: imported build + scenario + ruleset -> measurements -> ratings -> explanations.
- [ ] Document implementation plan, target modules, test commands and any performance risks.

**M1 acceptance:** Traceability table has evidence for every capability, not optimistic percentages. No unsupported assertion that current code has no scoring.

## M2 — Reliable measurement engine (P0)

### Offense
- [ ] Measure sustained single-target DPS (including attack chains, animation times, resource constraints and realistic availability).
- [ ] Measure short-window burst separately.
- [ ] Measure AoE effectiveness for specified target counts and coverage, not just single-target DPS multiplied by eight.
- [ ] Model +4 enemy hit chance, accuracy, defense and other applicable enemy-level modifiers for the default comparison; support scenario-specific alternatives.
- [ ] Model expected proc contribution using correct activation, PPM and hit mechanics; distinguish *local* from *global* recharge.
- [ ] Handle rains/patches, repeated ticks, auras, pets and relevant special cases without treating every tick as an unrestricted proc opportunity.
- [ ] Include resistance debuffs and other damage multipliers only when valid for the stated targets and uptime.

### Defense, sustain and mobility of combat resources
- [ ] Measure defense by position and damage type; resistance by damage type, with caps and context.
- [ ] Quantify expected mitigation and survival under stated incoming attack/damage profiles; distinguish raw capped stats from actual survival.
- [ ] Measure regeneration, absorb and healing throughput; recovery/endurance margin and attack-chain sustainability.
- [ ] Measure recharge and power availability, including downtime gaps and near-permanent uptime.
- [ ] Separate emergency powers (phase effects, temporary defenses, Force of Nature-like abilities) from sustained mitigation. Account for attack restrictions and opportunity costs.
- [ ] Preserve the distinctions between solo survival and team-provided defenses; do not silently assume external help.

### Calculation quality gates
- [ ] Expose raw values and units through a pure, deterministic API separate from Flask/UI.
- [ ] Reference the game client/data and version for each rule; do not infer new rules from benchmark builds.
- [ ] Identify unsupported powers/effects and estimate uncertainty rather than silently awarding zero or full credit.
- [ ] Add focused tests for mechanical edge cases, including proc-heavy, aura-heavy, temporary-defense and endurance-constrained builds.
- [ ] Demonstrate repeated evaluations are bitwise or tolerance-defined reproducible.

**M2 acceptance:** Each rated quantity has a reproducible numerical measurement, scenario, unit and tested interpretation.

## M3 — Team support as first-class metrics (P0)

Evaluate **magnitude, coverage, uptime, reliability and opportunity cost** for every supported effect. Represent single-target and AoE performance independently, with target count, stack/overlap behavior and selected enemy context explicit.

### Buffs
- [ ] Defense, resistance, damage, accuracy/to-hit, recharge, regeneration, recovery/endurance and other relevant team buffs.
- [ ] Distinguish sustained from burst/temporary buffs; avoid substituting naive maximums for typical uptime.

### Debuffs
- [ ] Target HP/max-HP, regeneration, defense, resistance, damage/offense, to-hit/accuracy, recharge and other relevant debuffs.
- [ ] Report single-target AV/hard-target utility separately from AoE spawn utility.
- [ ] Account for resistance to debuffs, landing probability and uptime.

### Healing and control
- [ ] Single-target, AoE, sustained and emergency heals; include useful coverage and real activation opportunity cost.
- [ ] Hard control (holds, sleeps, immobilization as appropriate) and soft control (knockdown, disorient and other disruption).
- [ ] Measure magnitude, duration, refresh frequency, target count, target rank/protection and practical reliability.
- [ ] Do not equate healing throughput with damage prevention or imply healing is always superior to preventive buffs.

**M3 acceptance:** A build that excels at AV -regen but not AoE -damage can be recognized for the former, and a high-uptime defensive buffer receives appropriate credit even if its raw healing is low.

## M4 — Rating tiers and baselines (P0)

- [ ] Provide independent S/A/B/C/D/F tiers for meaningful performance categories; **do not score absent or irrelevant capabilities as a failure by default**.
- [ ] Formalize labels: **Not Applicable** (goal/context irrelevant), **None** (capability absent), **Unknown/Unsupported** (insufficient model), versus **F** (measured capability falls below threshold).
- [ ] Retain exact numeric measurement alongside each grade.
- [ ] Define **meaningful performance benchmark thresholds** per metric and scenario, with owner-approved calibration before shipping grades.
- [ ] Consider percentiles as **supplemental context**, not the sole grade determinant: top 5% of a weak peer group must not imply top-tier absolute performance.
- [ ] Support 3 independent views: same primary + secondary + AT, same AT, and all ATs, with equivalent combat assumptions.
- [ ] Explain when different populations yield different grades (e.g., exceptional Mastermind defense versus Mastermind peers but merely strong across the entire game).
- [ ] Verify benchmark sampling/coverage; avoid pretending champion-only populations represent every build.
- [ ] Version benchmark datasets, thresholds and algorithm; reject or relabel incompatible version comparisons.
- [ ] Define how reference distributions change after game balance/model releases, without silently rewriting history.
- [ ] Do not create a universal composite grade by default; a **goal-specific** summary may be considered separately with explicit weighting/constraints.

**M4 acceptance:** A scorecard can show the same raw defense value with two defensible contextual rankings, explains the difference, and does not manufacture high grades from poor comparison populations.

**Open decision:** Exact S–F thresholds and percentile presentation. Proposed direction: performance-grounded tiers plus optional percentile display; no thresholds are assumed decided here.

## M5 — Build scorecards and comparisons (P1)

- [ ] Import an existing valid Sidekick build; evaluate without forcing optimization.
- [ ] Render category ratings and raw statistics with clear unit, context, confidence and benchmark basis.
- [ ] Provide the three comparison scopes and allow switching between them.
- [ ] Compare two or more builds side by side; highlight meaningful wins/losses and the size of differences.
- [ ] Separate single-target/AoE, sustained/burst, and sustained/emergency categories where material.
- [ ] Show missing/unsupported metrics explicitly.
- [ ] Give specific explanations: why a rating was assigned and what tradeoff produced it.
- [ ] Preserve user choice: do not disparage valid specialist builds for being weak outside chosen goals.
- [ ] Make model, data, benchmark and scenario versions inspectable.
- [ ] Support exporting/sharing evaluation results without silently modifying a player save.

**M5 acceptance:** A player can import a build, see why it is strong/weak in particular roles, switch comparisons, and compare it with another build without triggering the optimizer.

## M6 — Goal-driven optimization with a maintained Pareto frontier (P1)

### 6.1 User-selected objective space
- [ ] Select one or many objectives among offense, defense, resistance, sustain, recharge, buff, debuff, heal and control quantities.
- [ ] Use **numeric measured objective values**, not S–F grades, for dominance and search.
- [ ] Support objectives to **maximize** and **minimize** (e.g., cost), plus hard constraints and minimum floors.
- [ ] Support locked powers/slots or other build elements and legal enhancement/availability constraints.
- [ ] Normalize comparisons only as needed for numerical safety; keep objective meanings independently inspectable.
- [ ] Apply legality and hard-constraint checks before frontier admission.

### 6.2 Correct Pareto dominance
For the player-selected objective vector with all directions normalized to "higher is better":

> A dominates B iff A is at least as good as B on **every** selected objective, and **strictly better** on at least one.

- [ ] Implement a pure dominance comparator with explicit maximize/minimize directions, equality and floating-point tolerance rules.
- [ ] Keep **all feasible nondominated candidates discovered during search** in a frontier (subject only to explicit, labeled approximation/resource limits).
- [ ] When evaluating candidate C: reject if an incumbent dominates C; otherwise insert C and remove all incumbents C dominates.
- [ ] Handle exact duplicates deterministically; use stable fingerprints/tie-breaking.
- [ ] Never reject a candidate *solely* for a worse weighted-average score; weights may order exploration or display, not replace Pareto dominance.
- [ ] Maintain the frontier **throughout candidate generation/search**, not just as a final filtering pass.
- [ ] Avoid premature dominance pruning on partial/incomplete builds unless the algorithm has proved bounds that make it safe.
- [ ] Preserve diversity if the nondominated set grows; if epsilon-dominance, crowding/density or size caps approximate the frontier, label the output **approximate**, publish parameters and keep exactness tests for unconstrained cases.

### 6.3 Search implementation
- [ ] Reuse existing ILP, scoring and champion warm-start machinery rather than introducing an unrelated optimizer.
- [ ] Allow bounded deterministic run budgets/seeds; cache equivalent evaluations.
- [ ] Choose heuristics that explore different tradeoff directions without turning user goals into an undisclosed universal weight.
- [ ] Report candidates searched/evaluated, frontier size, stop reason, scenario and model version.
- [ ] Return discovered nondominated solutions even when stopped early.
- [ ] Call them the **discovered frontier**, never the proven global frontier unless an exhaustive or formally certified search establishes that claim.
- [ ] Preserve legal exportable builds and existing SKIF/Sidekick round-trip protections.
- [ ] Do not run expensive all-context sweeps/certification without permission.

### 6.4 Player-facing results
- [ ] Present several frontier alternatives rather than one alleged perfect build.
- [ ] Show each candidate's objective values, grades, and improvements/regressions from the starting build.
- [ ] Allow filtering to minimum standards and sorting/highlighting by a preferred goal **without deleting other nondominated alternatives**.
- [ ] Expose the objective dimensions that make each candidate non-dominated.
- [ ] Support selecting and exporting any retained candidate.

### 6.5 Required tests
- [ ] A candidate dominated on every relevant dimension is rejected.
- [ ] An incoming candidate dominates and removes one or more incumbents.
- [ ] Offense-vs-defense tradeoff candidates survive together.
- [ ] Equal candidates and floating-point near-ties are stable across runs.
- [ ] Both maximize and minimize dimensions behave correctly.
- [ ] Invalid builds or violated hard constraints never enter the frontier.
- [ ] A search with a hard time/evaluation budget still returns the discovered frontier.
- [ ] Heuristics, pruning and approximation do not silently discard valid tradeoffs.
- [ ] Repeated searches with identical inputs/settings are deterministic.
- [ ] Exported alternatives remain legal and Sidekick-compatible.

**M6 acceptance:** The optimizer **continuously maintains** a Pareto-nondominated set of evaluated legal builds. It preserves meaningful tradeoffs, does not promote a weighted-sum winner as universally best, and accurately labels any approximation or incomplete search.

### 6.6 Illustrative dominance example

These grades are only for explanation; the actual comparator must use unrounded numeric values.

| Candidate | Damage | Defense | Recharge | Treatment |
| --- | --- | --- | --- | --- |
| A | S | D | B | Retain |
| B | A | B | A | Retain |
| C | B | C | C | Discard: B dominates C |

A and B do **not** dominate one another: A has better damage while B has better defense and recharge.

## M7 — Integration and release gates (P1)

- [ ] Sidekick import -> validation -> numeric evaluation -> category ratings -> comparison -> Pareto alternatives -> export works end-to-end.
- [ ] Preserve unknown Sidekick/SKIF fields where supported; fail visibly rather than silently discarding information.
- [ ] Keep the client offline and LLM-free for evaluations and optimization.
- [ ] Include versioned scenarios, rule assumptions, unknowns and constraints in reproducible result artifacts.
- [ ] Performance budgets and memory bounds are tested on realistic builds, with expensive certification runs excluded unless approved.
- [ ] UI and API clearly differentiate raw measurements, ratings, champion score, and chosen optimization objectives.
- [ ] Test representative archetypes, unusual specialist builds, proc bombs, pets, emergency protection and support-focused characters.
- [ ] Perform independent red/blue review on substantive implementations; fix HIGH/BLOCK findings or obtain explicit owner acceptance before merge.
- [ ] Keep PRs feature-sized (about 3–5 substantive commits when practical); never merge to master without user approval.

**M7 acceptance:** An actual imported character receives actionable capability ratings and valid optimized alternatives, with documented behavior and passed scoped tests. Import/export, raw stats, or a single optimized build alone are not completion.

## 3. Open product decisions (owner review required before shipping affected behavior)

- [ ] S/A/B/C/D/F thresholds per metric and scenario.
- [ ] Percentile availability and cohort construction (full builds versus champion-only baseline).
- [ ] Difference between None, Not Applicable, Unknown and F in the interface.
- [ ] Whether any optional goal-weighted *summary* should exist (not a universal overall score).
- [ ] Precise +4 default scenario (enemy archetype, target count/rank mix, encounter duration, incoming damage).
- [ ] Survival metric comparability across ATs and content styles.
- [ ] Which build elements are editable/lockable in optimization.
- [ ] How large a frontier can become before the UI introduces explicit approximation, ranking or paging.
- [ ] Runtime budget and quality bar for a usable search result.
- [ ] Benchmark governance and calibration after each balance patch.

Resolve only consequential product questions with the owner; proceed with audit and independently testable measurement contracts meanwhile.

## 4. Engineering workflow and progress reporting

- [ ] First perform M1 audit. Report evidence and a traceability matrix rather than asserting a guessed percent complete.
- [ ] File issues from verified gaps with scoped acceptance criteria and dependencies.
- [ ] For behavior changes: write failing tests (RED), implement (GREEN), refactor, run focused regressions.
- [ ] Use existing repository tools and standards; do not invent third-party mechanics.
- [ ] Alternate independent Codex/Claude implementation and review when separately executable; never claim a review was run if not.
- [ ] Summarize for each PR: achieved behaviors, outstanding risks, test evidence, independent review status and user-visible effects.
- [ ] Seek explicit user approval for every merge to master.

**Documentation-only PR exception:** No RED/GREEN code test cycle is applicable to writing this specification; inspect markdown structure and verify the PR diff instead.

## 5. Final project checklist

Do **not** mark the build-evaluation/rating objective complete until all are demonstrably true:

- [ ] Import an ordinary Sidekick build and evaluate it without optimization.
- [ ] Measure and expose key offense, survival, resource and support quantities with units and assumptions.
- [ ] Rate relevant individual capabilities using meaningful, documented benchmarks.
- [ ] Support same-powerset, same-AT and all-AT comparisons.
- [ ] Explain grades and missing/unsupported mechanics.
- [ ] Compare alternative builds and make tradeoffs visible.
- [ ] Optimize for user-selected objectives and hard constraints.
- [ ] Maintain a discovered Pareto frontier during the search; preserve nondominated alternatives.
- [ ] Never silently conflate a discovered/approximate frontier with a proven global one.
- [ ] Export valid alternatives into the Sidekick workflow.
- [ ] Keep computations deterministic, offline, versioned and game-mechanics-grounded.
- [ ] Pass scoped unit/integration/regression tests and independent substantive review.
- [ ] Obtain user approval before merging to master.

**Immediate next engineering work:** M1 traceability audit and issue breakdown, followed by the smallest verified gap in the calculation -> category-rating path.
