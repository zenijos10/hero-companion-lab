---
name: hc-tdd
description: Implement Hero Companion changes test-first with clean code and mechanical correctness.
---
# Hero Companion TDD (Codex)
Read AGENTS.md, relevant sections of CLAUDE.md, and docs/agent-team/STANDARDS.md before editing. If graphify exists, use the repository's prescribed graphify queries; otherwise state that it was unavailable and inspect only relevant code.
1. Define observable acceptance criteria and a narrow baseline.
2. RED: write a regression test that fails for the expected reason. Record its command and failure.
3. GREEN: implement the minimum production code to pass.
4. REFACTOR: improve naming, cohesion and duplication without changing behavior. Re-run tests.
5. Verify the relevant existing scripts/tests and report evidence, assumptions and limits.
Never use unverified game mechanic constants, real user saves, unbounded optimizations, or wholesale game-data rewrites.
Do not commit, push, merge or publish unless the user explicitly authorizes that action. Never merge master without user approval.
