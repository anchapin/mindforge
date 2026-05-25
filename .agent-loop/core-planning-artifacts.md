# Core Planning Artifacts

These six HTML files are the planning contract for substantial coding, writing, research, and mixed projects:

1. `prd.html` - product requirements, scope, success criteria, non-goals.
2. `planning.html` - delivery phases, dependencies, ownership, sequencing.
3. `spec.html` - detailed behavior, states, data contracts, validation, errors, edge conditions, and acceptance criteria.
4. `test-cases.html` - happy paths, edge cases, error cases, performance cases, user workflow cases, and acceptance mapping derived from `spec.html`.
5. `architecture.html` - components, boundaries, data flow, dependencies, deployment, failure modes, and an Excalidraw-compatible diagram reference.
6. `users.html` - user roles, journeys, permissions, outcomes, and operational handoffs.

Implementation should not begin until these artifacts are internally consistent and accepted through the two-round cross-review protocol.

## Dependency-Aware Planning Flow

1. Parallel draft `prd.html`, `users.html`, `architecture.html`, `planning.html`, and early test risks.
2. Lead integrator reconciles scope, workflows, architecture, plan, and test risks.
3. Write `spec.html` from the accepted PRD, users, architecture, and planning artifacts.
4. Write `test-cases.html` from `spec.html`.
5. Run two cross-review rounds and record final acceptance.
