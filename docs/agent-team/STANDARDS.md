# Engineering standards for Hero Companion Lab

These additive instructions do **not** supersede the upstream `AGENTS.md` or `CLAUDE.md`. Where instructions conflict, prefer the stricter restriction and report it for human resolution.

## Clean code
- Prefer descriptive names, cohesive functions, single responsibility and explicit data contracts.
- Separate pure calculations from I/O, Flask routes, UI handling, and persistence.
- Reuse existing implementation before introducing an abstraction or new engine.
- Avoid duplication, hidden global state, speculative frameworks, broad rewrites and unjustified dependencies.
- Keep changes narrowly scoped and consistent with current Python/vanilla-JS conventions.

## Test-driven development
Every behavior change follows RED → GREEN → REFACTOR. Record the specific failing test before changing production code, then passing results and any regression tests. Make tests deterministic, small, and independent of network and real user saves. If the test-first sequence is impossible (e.g. documentation-only change), explain why.

Use established repository test scripts and commands rather than treating a newly added test framework as an automatic replacement. Run only narrowly scoped optimizer tests unless a long run has been specifically authorized.

## Mechanical correctness
The Homecoming game client is authoritative. Reference builds and other planners can be cross-checks, not sources for invented rules. Keep precise mechanics separate from heuristic scores; label estimates clearly. Respect slot eligibility, uniqueness, caps, archetype/level restrictions, target scenario, resistance/protection, recharge, endurance and proc behavior. Record game-data/model revisions for comparisons.

## Compatibility and safety
Sidekick SKIF round trips must preserve unknown or unsupported fields without silently dropping them; fail explicitly when lossless export is not supported. Test malformed input and independently re-import representative exports. Never modify real player saves during testing. Do not redistribute third-party source without license review.

## Review
An independent reviewer challenges each substantive feature. Findings include severity, source location, reproduction, and impact. BLOCK/HIGH findings must be resolved or explicitly accepted by the user before requesting a merge. Do not claim Codex or Claude Code was invoked unless a distinct execution session actually ran.

## Approval boundary
The user authorized feature branches, commits, and pull requests for this fork. These instructions do not authorize merging into master, publishing releases, rewriting canonical data, or touching the upstream repository.
