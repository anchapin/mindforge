# Review Rubric

Lead with findings. Prioritize correctness, security, user-visible or reader-visible regressions, missing tests, factual drift, stale documentation, and maintainability risks.

## Required Checks

- Does the diff satisfy the plan?
- Are edge cases and failure modes covered?
- Are tests meaningful and close to the risk?
- Did the implementation follow existing project patterns?
- Did it introduce same-file ownership conflicts from parallel work?
- Did active agent claims overlap in `.agent-loop/coordination/ownership.json`?
- Did the opposite tool review the change when both tools participated?
- Is `README.md` current and easy to follow after the change?
- For writing work, are claims, sources, outline, terminology, and export instructions still accurate?
- Should any lesson become a pattern, decision, or failure note?

## Severity

- P0: Data loss, security compromise, production outage, or unusable core path.
- P1: Incorrect behavior in important paths or high-confidence regression.
- P2: Maintainability, test, or edge-case issue that should be fixed before merge.
- P3: Small cleanup or optional polish.
