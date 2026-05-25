# Compound Team Start

Create a Claude Code agent team for work that benefits from inter-agent coordination.

Prerequisites:

- `.claude/settings.json` contains `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` set to `"1"`.
- `.agent-loop/team-topology.md` defines roles, scopes, and completion gates.
- The task has separable lanes and disjoint write ownership.

Steps:

1. Create or update a plan with `compound-start`.
2. Create a team run note in `docs/compound/`.
3. Ask Claude to create a dependency-aware planning team.
4. Parallelize PRD, users, architecture, planning, and early test strategy.
5. Serialize integration, `spec.html`, `test-cases.html`, and final acceptance.
6. Run the two-round cross-review protocol before implementation.
7. Assign each teammate a scoped task, owned files, output artifact, and verification responsibility.
8. Wait for teammates to finish before synthesis.
9. Write a compound note before declaring completion.

Starter prompt:

```text
Create an agent team for this task. Use `.agent-loop/team-topology.md`, `.agent-loop/core-planning-artifacts.md`, and `.agent-loop/parallel-agent-team-protocol.md`.
Spawn PRD, users/workflow, architecture, planning, test-strategy, spec, test-case, and reviewer lanes as dependency order allows.
Do not start implementation until `prd.html`, `planning.html`, `spec.html`, `test-cases.html`, `architecture.html`, and `users.html` pass two review rounds and final acceptance.
Keep write scopes disjoint, wait for teammates to finish, synthesize findings, run verification, and write a compound note.
```
