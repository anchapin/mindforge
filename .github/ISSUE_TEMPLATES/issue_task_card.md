## Use Case
The TaskTracker currently shows tasks but needs individual task cards that display project badge, agent role, task description preview, status indicator, and countdown timer for draft approvals.

## Proposed Solution
Implement TaskCard component per SPEC.md Section 2.7.2 (Task submission states) and Section 2.7.4 (TaskTracker component).

**Features needed:**
- Project badge (color-coded by project_id hash)
- Task description (truncated to 1 line)
- Status indicator (color-coded: running=red, draft=amber, completed=green, failed=gray)
- Step progress for running tasks ("Step 2/4 ->")
- Countdown timer for draft approvals ("2h left")
- Click to expand -> DraftReview inline

**Project badge spec (SPEC.md Section 2.7.2):**
- Tappable: opens inline dropdown to reassign project
- Color derived from hash of project_id
- "(global)" shown when project_id = null

**Existing files:**
- frontend/src/components/TaskCard.tsx exists but is minimal
- frontend/src/components/TaskCard.test.tsx exists with tests

**What needs building:**
- Full TaskCard implementation matching the spec
- ProjectBadge component with color hashing
- StatusBadge component
- StepProgress indicator
- Countdown timer for approval windows

## Phase Alignment
- [ ] Phase 2 — Multi-Agent + Skills

## References
- SPEC.md Section 2.7.2
- SPEC.md Section 2.7.4 (TaskTracker component)
- Existing frontend/src/components/TaskCard.tsx