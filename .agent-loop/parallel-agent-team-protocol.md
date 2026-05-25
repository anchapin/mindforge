# Parallel Agent Team Protocol

Parallelize independent planning and verification work, then serialize integration and acceptance.

## Phase A: Parallel Drafting

| Agent | Owns | Output |
| --- | --- | --- |
| PRD agent | `prd.html` | Product contract |
| Users/workflow agent | `users.html` | User and workflow contract |
| Architecture agent | `architecture.html`, `architecture.excalidraw` | System contract and diagram |
| Planning agent | `planning.html` | Delivery plan |
| Test strategy agent | Initial risks for `test-cases.html` | Test categories |

## Phase B: Integration

The lead integrator reconciles assumptions before spec work begins.

## Phase C: Spec

The spec agent writes `spec.html` from accepted PRD, users, architecture, and planning artifacts.

## Phase D: Tests

The test-case agent writes `test-cases.html` from `spec.html`.

## Phase E: Review

Run the two-round cross-review protocol before implementation begins.

Every editing agent claims files before edits. Failed claims stop the work until the lead narrows scope, releases stale claims, or serializes the task.
