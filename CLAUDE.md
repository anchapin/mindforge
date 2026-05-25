# Claude Instructions

<!-- compound-orchestrator:start -->
## Compound Engineering Protocol For Claude Code

Use this repository as a compound engineering system for coding, writing, research, documentation, or mixed project work:

1. Start meaningful work with a task brief or plan in `docs/plans/`.
2. For substantial projects, complete the six planning contracts: `prd.html`, `planning.html`, `spec.html`, `test-cases.html`, `architecture.html`, and `users.html`.
3. Keep implementation scoped to the plan unless new evidence changes it.
4. Run `scripts/verify.py`, `scripts/verify.ps1`, `scripts/verify.sh`, or the closest project-specific verification before completion.
5. Review changes for bugs, missing tests, security risks, product regressions, factual drift, stale documentation, and unclear writing.
6. Record durable learning in `docs/patterns/`, `docs/decisions/`, `docs/failures/`, or `docs/compound/`.
7. Keep `README.md` current by removing stale information, preserving still-true information, adding new content, and reorganizing it into an easy-to-follow narrative.

Completion gate:

- A plan exists for the task.
- The six planning contracts are accepted before implementation starts on substantial projects.
- Any files edited by Claude Code or Codex are claimed in `.agent-loop/coordination/ownership.json` before edits.
- No active ownership claim overlaps another agent's claim unless the lead explicitly resolves the conflict.
- A cross-tool review exists when Claude Code reviews Codex-authored changes or Codex reviews Claude-authored changes.
- Verification was run or the blocker is documented.
- Two cross-review rounds are complete and author responses are recorded; stop after two rounds unless the user asks for more.
- `README.md` reflects the latest project state when the task changes setup, usage, architecture, workflow, output, or audience-facing behavior.
- A compound note records what future work should reuse or avoid.

Parallel agent policy:

- Use `.agent-loop/team-topology.md` as the shared Claude/Codex team contract.
- Use parallel agents for independent research, planning, test strategy, review, and competing bug hypotheses.
- Parallelize planning drafts, then serialize integration, `spec.html`, `test-cases.html`, and final acceptance.
- Give each agent a role, scope, owned files, expected artifact, and verification responsibility.
- Avoid parallel edits to the same file unless a lead integrator owns the final merge.
- Claude Code should use agent teams when work benefits from teammate-to-teammate coordination.
- Codex should mirror the same team shape with a lead-integrator hub plus explorer/worker/reviewer agents; workers must have disjoint write scopes.
- Before editing, claim intended files with `compound_orchestrator.py claim`.
- Before handing off, release claims with `compound_orchestrator.py release` or document why they remain active.
- Use the opposite tool's reviewer for cross-tool review: Claude reviews Codex-authored changes, Codex reviews Claude-authored changes, and other agents use the same author/reviewer split.

Project harness rules:

- Keep root `CLAUDE.md` short: big picture, navigation pointers, and critical gotchas only.
- Put local build/test/lint commands in subdirectory `CLAUDE.md` files.
- Start Claude Code in the subdirectory where work is happening; parent `CLAUDE.md` files still load.
- Move repeated procedural instructions into path-scoped skills instead of bloating `CLAUDE.md`.
- Prefer hooks over "always remember to..." instructions when behavior should be automatic.
<!-- compound-orchestrator:end -->
