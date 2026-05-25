# backend/tools — Integration Tools

## Purpose

BaseTool abstract class, ToolRegistry singleton, rate limiter, and all integration tool implementations (GitHub, Stripe, Linear, email, Google Calendar).

## Local Commands

- **Run tool tests**: `cd backend && pytest tests/unit/test_tools*.py -v`
- **List registered tools**: `python -c "from backend.tools.registry import ToolRegistry; print(ToolRegistry.list_names())"`
- **Test rate limits**: `python -c "from backend.tools.rate_limiter import IntegrationRateLimiter; ..."`
- **Validate Linear API**: `python -c "from backend.tools.integrations.linear import LinearTool; t = LinearTool(); print(t.name)"`

## Key Files

| File | Purpose |
|------|---------|
| `base.py` | `BaseTool` abstract class + `ToolResult` dataclass |
| `registry.py` | `ToolRegistry` singleton + `register_all_tools()` |
| `rate_limiter.py` | `IntegrationRateLimiter` + `@integration_call` decorator |
| `github.py` | GitHub API (commits, issues, PRs, create_issue) |
| `stripe.py` | Stripe API (revenue, refunds, billing) |
| `email_fetch.py` | IMAP email retrieval |
| `email_send.py` | SMTP email send |
| `integrations/linear.py` | Linear GraphQL (list/create/update/get issues) |
| `integrations/google_calendar.py` | Google Calendar API |

## Rate Limits

```python
INTEGRATION_RATE_LIMITS = {
    "github": 5,      # per second
    "stripe": 10,
    "linear": 5,
    "email": 15,
}
```

## Local Conventions

- **All tools inherit `BaseTool`** and implement `_execute(self, action, **kwargs) -> ToolResult`
- **Token scrubbing**: `scrub()` in `base.py` removes tokens, keys, HMAC signatures from logs
- **Tool names** must be unique and match `required_integrations` in skill YAML files
- **High-stakes integrations** (stripe, send_email, github_push) trigger forced draft-approval when memory is primary context

## Gotchas

- Tools are registered at startup via `register_all_tools()` in `main.py` lifespan
- If a tool's API credentials fail to construct (wrong key format, missing scope), the tool registration fails silently and the tool is excluded — it won't be available at runtime
- `validate_auth()` method on each tool should probe the real API, not just check token format