# M1 — Traceability audit: build evaluation, rating, comparison, Pareto

**Plan:** [BUILD-EVALUATION-RATING-OPTIMIZATION-PLAN.md](BUILD-EVALUATION-RATING-OPTIMIZATION-PLAN.md)
**Audited:** 2026-11-08, master `6591b5f`. Read-only: no code changed, no optimizer or certification run.
**Method:** each requirement traced to a source location and, where possible, run once through the real
route (`/build/autopick` → `/build/solve` → `/build/calculate`, Scrapper BS/Invuln, general content).

Status words: **Complete** (verified in code and a test or the real route) · **Partial** (the measurement
exists but is not exposed, not scenario-aware, or not tested the way the plan asks) · **Missing** ·
**Blocked** (needs game knowledge we don't have) · **Decision** (needs an owner ruling).

## The one-paragraph finding

The **measurement engine is far along; the requested player-facing rating, comparison and Pareto layers are not implemented.**
`engine.calculate_build` already returns typed defense/resistance, HP/regen/recovery against caps,
endurance sustainability, single-target chain DPS, AoE DPS and burst, PPM-priced procs, and enhanced
buffs/debuffs. `first_principles.encounter_value` turns a build into a scenario-aware contribution
(my_dps + amplified + prevented, × availability/time-to-live) at +1..+4 with Purple Patch and to-hit
tables. `role_output.py` measures control, debuff, buff and heal output. But a player sees only raw
stats: there are **no S–F grades, no benchmark thresholds, no peer comparison, no side-by-side of two
builds, and the optimizer returns one winner by a weighted contribution, not a frontier.** The
champion roster (2,865 contexts) is a potential **optimized-reference** dataset, not a representative
peer-build population: it is almost entirely one content type (2,854 itrial).

## Traceability matrix

### M2 — Measurement

| Requirement | Status | Evidence | Gap |
| --- | --- | --- | --- |
| Sustained single-target DPS (chain, animation, end) | Partial | `engine._chain_dps` (120 s chain, `engine.py:1071`); `offense.st_dps`, `chain_end_per_sec` | Not scenario-aware in the display (no +4 hit chance applied to the shown number; `encounter_value` applies it but is not exposed) |
| Short-window burst, separate | Partial | `offense.aoe_burst` (`engine.py:1453`) | No single-target burst metric |
| AoE for stated target counts | Partial | `offense.aoe_dps`, `aoe_count`; scenario `enemies` in `first_principles.SCENARIOS` | Target count fixed by scenario, not selectable |
| +4 hit chance / enemy level | Partial | `first_principles._PLAYER_BASE_VS`, `_PP_BELOW`, `outgoing_hit`; scenarios carry `shift` 1–4 | Only farm scenarios are +4; `general` is +1. The agreed +4 **rating** default must be implemented without silently changing existing solver presets |
| Procs: PPM, local vs global recharge | Partial | `engine.py:1123` PPM pricing into attack damage; proc_pass | Existing formula is explicitly marked PROVISIONAL pending verification against game mechanics; continue to disclose model limitations |
| Rains/patches/auras/pets tick handling | Partial | v51 aura proc pets (`engine.py:1733`); pet DPS (v38) | Aura/patch proc valuation is an **open ruling** (field 10.66%/tick vs formula 6.14%, CLAUDE.md) |
| −res / damage multipliers only when valid | Partial | `encounter_value` amplified term; `debuff_res` per scenario | Uptime-gated, but not shown per target |
| Defense by position+type; resistance by type, capped | Complete | `totals.defense` (11 keys), `totals.resistance` (8 keys), `caps` | — |
| Mitigation/survival under incoming profile | Partial | `encounter_value` → `ttl`, `availability`; `incoming_hit` | Computed for scoring, not exposed to the player |
| Regen/absorb/heal throughput; endurance margin | Partial | `regeneration.hp_per_sec`, `bonus_extras.absorb/absorb_hps`, `endurance.sustainable/net_per_sec` | Key quantities exist, but coverage and player-facing scenario throughput/limitations have not been validated for this evaluation contract |
| Recharge + power availability, downtime | Partial | `recharge`, `role_output.build_control_uptime`, Hasten uptime in `encounter_value` | No per-power downtime/perma report |
| Emergency vs sustained mitigation | Missing | — | Click armors are excluded from totals (by design) but not reported as a separate "emergency" class |
| Solo vs team-provided defense | Partial | `external_included` flag on totals; scenario `teammates` | No side-by-side solo/team view |
| Pure deterministic API separate from Flask | Partial | `engine.calculate_build`, `fp.encounter_value` are pure | No single "evaluate" contract bundling measurements + scenario + versions |
| Rule source + version per rule | Partial | `MODEL_VERSION` (57) stamped on champions/certs; game-first comments throughout | Not attached to a player-facing result |
| Unsupported effects disclosed, not zero/full | Partial | `docs/KNOWN-GAPS.md` (gap_ledger), inherent COUNTED/SHOWN ONLY/NOT MODELED words | Not per-build: a scorecard can't yet say "this build uses N unmodeled effects" |
| Edge-case tests (proc, aura, temp def, end) | Partial | tools/test_afk_offense, test_crits, test_domination, test_proc_trade_note, test_pet_hit_v38 | No test suite aimed at an *evaluation* contract |
| Reproducible evaluations | Partial | `evaluate_first` stability runs (0 moved on repeat); "canonical retraction" documents the in-process caveat | Fresh-process stability reported, but known unexplained in-process drift prevents a full deterministic guarantee |

### M3 — Team support

| Requirement | Status | Evidence | Gap |
| --- | --- | --- | --- |
| Team buffs (def/res/dmg/tohit/rech/regen/rec) | Partial | `role_output.enhanced_team_buffs`, `team_recovery_frac`; `offense.buffs` | Magnitude only; coverage/uptime/reliability not reported separately |
| Sustained vs burst buffs | Partial | v39 mode/host_recharge duty cycle (Build Up class) | Not split in output |
| Debuffs (−res, −def, −regen, −dmg, −tohit, −rech) | Partial | `role_output.enhanced_debuff_totals`; `offense.debuffs`; AV `debuff_res` 0.85 | No ST(AV) vs AoE(spawn) split; landing probability only inside `encounter_value` |
| Heals ST/AoE/sustained/emergency | Partial | `role_output.build_heal_output`, `power_heal_output` | No ST/AoE/emergency split |
| Hard and soft control | Partial | `role_output.build_control_output` (mez-seconds × mag × area × uptime, typed weights) | A proxy score, not magnitude/duration/target-count reported per type; `mez_in` ruling open |
| Per-power support diffs | Missing | CLAUDE.md: "Buffs/debuffs are NOT diffed per power" | — |

### M4 — Ratings and baselines

| Requirement | Status | Evidence | Gap |
| --- | --- | --- | --- |
| S/A/B/C/D/F per category | Missing | No grade code anywhere (grep) | — |
| Not Applicable / None / Unknown / F labels | Missing | — | **Decision** (plan §3) |
| Numeric value beside grade | Partial | Raw values and some cap/pct-to-cap fields already exist in engine results | No grade-side values, units or rating result contract yet; not every metric is a capped stat |
| Benchmark thresholds per metric/scenario | Missing | — | **Decision**: owner calibration |
| Percentiles as supplemental | Missing | `learn.py` percentiles exist but only for search marginals | — |
| Three scopes (same sets+AT / AT / all) | Missing (population exists) | `benchmarks/champions.json` keyed `Class|primary|secondary|content`, 2,865 entries, 15 ATs | 2,854 are itrial; champions are optimized builds, not a representative population — the plan's own warning |
| Versioned benchmarks | Partial | `model_version` stamp per champion (merge_champion_shards) | No benchmark/threshold version |
| No universal composite by default | Complete (by absence) | `canonical_score` is internal; not shown as a grade | Keep it that way |

### M5 — Scorecard and comparison UX

| Requirement | Status | Evidence | Gap |
| --- | --- | --- | --- |
| Import Sidekick build, evaluate without optimizing | Complete | `/build/import-sidekick` → recompute → `/build/calculate` (no solve) | — |
| Category ratings + units + context | Partial | Stats tab shows raw values and caps | No ratings, no scenario shown |
| Switch comparison scope | Missing | — | — |
| Side-by-side two or more builds | Missing | Only the tier overlay (3 *generated* builds, `index.html:877`) and the improvement report (one build before/after) | No compare of two saved/imported builds |
| Explain why a rating | Missing | — | — |
| Show unsupported metrics per build | Missing | — | — |
| Versions inspectable | Partial | About shows app/model version | Not on a result |
| Export evaluation without touching the save | Missing | — | — |

### M6 — Pareto optimization

| Requirement | Status | Evidence | Gap |
| --- | --- | --- | --- |
| User-selected objectives, max/min, floors | Partial | Custom targets = floors; content/role/perk choose the objective | One objective at a time; no minimize objectives |
| Locks, legality before admission | Partial | per-power `locked`, `_picks_legal`, `/build/validate`, preserve | Existing build legality/locks can be reused; frontier admission checks do not exist yet |
| Dominance comparator | Missing | No dominance code (grep "pareto|dominat") | — |
| Frontier maintained during search | Missing | `deep_optimize` keeps one champion; `/build/solve` physics-arbitrates three arms and keeps the best; `/build/assess` re-solves 2–4 alternative routes | `/build/assess` is the nearest thing: alternatives with deltas, but chosen by weighted target emphasis, not dominance |
| Several alternatives shown | Partial | `/build/assess` alternatives; tier overlay | Not nondominated, not exportable as a set |
| Discovered vs proven frontier labelling | Missing | Certificates already label convergence/truncation | Pattern to reuse |
| Exported alternatives legal + Sidekick-compatible | Complete (single build) | `/build/export-sidekick`, Sidekick decoder in CI | Applies to any one build |

### M7 — Integration

| Requirement | Status | Evidence | Gap |
| --- | --- | --- | --- |
| Import → validate → evaluate → rate → compare → Pareto → export | Partial | import, validate, evaluate, export done | rate, compare, Pareto missing |
| Offline, LLM-free | Complete | `AI_ENABLED` off in the client; engine/solver deterministic | — |
| Raw vs rating vs champion score vs objective distinguished | Missing | — | — |

## Backlog for verified gaps

GitHub Issues are disabled on this repository, so this list IS the tracked backlog (one PR per item,
smallest first; tick the box in the PR that closes it):

- [ ] 1. **Evaluation contract** — one pure `evaluate(build, scenario)` returning measurements + units + scenario + model/data versions + unsupported list, exposed as `/build/evaluate` (M2 foundation; no grades).
- [ ] 2. **Expose the scenario-aware numbers** — `encounter_value`'s ttl/availability/hit chances and `role_output` control/debuff/heal on that contract (M2/M3).
- [ ] 3. **Rating tiers** — S–F per category from thresholds, with N/A / None / Unknown labels (M4; blocked on owner thresholds).
- [ ] 4. **Peer comparison** — design representative versioned peer cohorts for three scopes; show champion standings as a **separate optimized-reference** comparison if useful. Do not present champion-only percentiles as population percentiles (M4).
- [ ] 5. **Scorecard + side-by-side compare UI** (M5).
- [ ] 6. **Pareto frontier** — pure dominance comparator + frontier, then a multi-objective search reusing `_assess_solve` (M6).

## Owner decisions needed before grades ship

From plan §3, the decisions that block shipping calibrated grades are: (a) which enemy/encounter
assumptions accompany the **already agreed +4 default for build ratings** (the existing `general`
solver preset stays +1 unless changed by a separate approved decision); (b) S–F thresholds per metric;
(c) how to construct representative comparison cohorts rather than treating an optimized, largely
itrial-only champion roster as a random player-build population. Everything in backlog items 1–2 and
the dominance comparator in item 6 can be built without these.

## Recommended first build

**Issue 1 (evaluation contract)**: it is the plan's own "smallest verified gap in the calculation →
category-rating path", needs no owner ruling, wraps code that already exists, and every later
milestone reads from it.
