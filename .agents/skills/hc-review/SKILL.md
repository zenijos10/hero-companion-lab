---
name: hc-review
description: Independent adversarial review for Hero Companion code and game mechanics.
---
# Hero Companion adversarial review (Codex)
Follow AGENTS.md, relevant CLAUDE.md instructions, and docs/agent-team/STANDARDS.md. Review the neutral task brief, changed code, callers, tests, and game-data sources independently of the implementer's explanation.
Stay read-only on implementation; use a separate worktree/branch for adversarial tests if needed.
Try to falsify correctness: invalid SKIF round trips, corrupted or missing fields, enhancement legality, proc/PPM rules, time-varying recharge, deterministic outputs, performance, and failure paths.
Report findings with severity, file/line, reproducible steps, expected vs actual, and exact evidence. Distinguish untested hypotheses from verified failures.
Block acceptance for wrong mechanics, illegal builds, data loss, bypassed tests, major regressions or unsafe file writes. If unable to execute tests, state that explicitly.
Do not merge master or approve your own implementation.
