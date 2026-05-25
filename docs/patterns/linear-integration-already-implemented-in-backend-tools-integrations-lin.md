# Linear integration already implemented in backend/tools/integrations/linear.py

Date: `2026-05-22`
Kind: `pattern`

## Summary

Issue #153 reported LinearTool missing, but backend/tools/integrations/linear.py already existed with full CRUD (list_issues, create_issue, update_issue, get_issue), registered in registry.py, rate limited (INTEGRATION_LIMITS linear=5), and tested. Created missing unit tests (backend/tests/unit/test_linear_tool.py) and documented auth in SECURITY.md. Pre-existing test failures in test_main_lifespan.py are unrelated infrastructure issues (backend/main.py missing register_all_tools call).

## Reuse Rule

When this situation appears again, future agents should:
