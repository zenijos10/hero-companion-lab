# Codex + Claude Code: red team / blue team

Alternate the implementer/reviewer by feature:
- Odd cycles: **Codex blue**, **Claude Code red**.
- Even cycles: **Claude Code blue**, **Codex red**.

These definitions are reusable prompts and roles, **not an automatically running multi-agent orchestration system**. Start independent tool sessions to obtain genuine cross-model review.

1. Prepare a neutral brief containing observable acceptance criteria, changed surface, non-goals, relevant game-data versions, safety constraints and scoped checks.
2. Blue: inspect relevant code and rules, run baseline, add a failing test (RED), implement minimally (GREEN), refactor and rerun, record commands/outcomes.
3. Red: in a fresh independent model session, read the brief and diff rather than trusting blue's account. Challenge edge cases, format fidelity, exact mechanics, determinism, performance, security and insufficient tests. Stay read-only on implementation and document failures.
4. Blue: fix validated defects test-first and request red-team re-review.
5. PR: include test evidence and independent-review status. Do not merge until the user approves.

A human may assign a different rotation explicitly. Never report planned review as performed review.

## Example prompts
Codex blue: `Use $hc-tdd. Implement [neutral brief] using RED/GREEN/REFACTOR. Report test evidence and risks.`
Claude red: `Use @agent-hc-red to independently review [brief] and the actual diff, seeking reproducible counterexamples.`
Claude blue: `Use @agent-hc-blue to implement [brief] test-first. Report tests and limitations.`
Codex red: `Use $hc-review to independently audit [brief] and the diff. Report verified flaws and missing cases.`

## Initial proposed feature
SKIF import/export compatibility with Sidekick. Establish representative fixture(s), a lossless round-trip requirement, malformed-input behavior, and an external Sidekick re-import check before changing optimization behavior.
