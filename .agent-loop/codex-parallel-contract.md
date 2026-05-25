# Codex Parallel-Agent Contract

Codex does not use Claude Code's runtime team config. It should mirror the same compound team topology with a lead-agent hub.

## Lead Responsibilities

- Decide whether parallel agents are useful.
- Keep the immediate blocking task local.
- Delegate bounded sidecar tasks with clear scopes.
- Prevent overlapping write ownership.
- Claim intended write paths in `.agent-loop/coordination/ownership.json` before edits.
- Refuse to edit files actively claimed by another agent runtime unless the lead releases or explicitly resolves the claim.
- Integrate returned work and run verification.
- Request Claude `compound-cross-tool-reviewer` review for Codex-authored changes when Claude Code is part of the workflow.
- Run Codex `codex-cross-tool-reviewer` review for Claude-authored changes before integration.
- Record durable learning before completion.

## Delegation Prompt Template

```text
You are not alone in this project. Other agents may be working in parallel.

Runtime or tool label:
Role:
Goal:
Owned files, modules, drafts, or artifacts:
Read-only context:
Output artifact:
Verification responsibility:
Do not edit outside your ownership scope.
Do not revert unrelated changes.
Before editing, claim owned files with `compound_orchestrator.py claim`.
If the claim fails, stop and report the conflict.
List changed files and remaining risks in your final answer.
```

## Recommended Parallel Lanes

- PRD: `prd.html`.
- Users/workflow: `users.html`.
- Architecture: `architecture.html` and `architecture.excalidraw`.
- Planning: `planning.html`.
- Spec: `spec.html` after integration.
- Test cases: `test-cases.html` after `spec.html`.
- Explorer: read-only project pattern research.
- Architect: plan decomposition and risks.
- Worker: bounded implementation, writing, or documentation in owned files.
- Test Runner: test design, execution, failure diagnosis.
- Reviewer: diff review against `.agent-loop/review-rubric.md`.

## Completion Gate

A Codex team run is complete only when the lead has:

- synthesized agent outputs
- confirmed no active cross-tool ownership conflict remains
- completed the opposite-tool review when more than one agent runtime participated
- completed both cross-review rounds and author responses
- resolved or accepted review findings
- run verification or documented the blocker
- written a compound note under `docs/compound/`
