# LSP And MCP Roadmap

Add these after the context layer, hooks, and skills are healthy.

## LSP Candidates

| Language | Server | Install Owner | Status | Notes |
| --- | --- | --- | --- | --- |
| Python | pyright | TBD | Candidate | Useful when symbol names collide |
| TypeScript | typescript-language-server | TBD | Candidate | Useful in monorepos |
| Java/C#/C++ | language-specific server | TBD | Candidate | High value in typed enterprise repos |

## MCP Candidates

| Tool/Data Source | Why Claude Needs It | Owner | Auth Model | Status |
| --- | --- | --- | --- | --- |
| Internal docs | Avoid stale local knowledge | TBD | TBD | Backlog |
| Ticketing system | Link work to source of truth | TBD | TBD | Backlog |
| Analytics/logs | Debug with live operational context | TBD | TBD | Backlog |
| Source library or reference manager | Keep writing projects grounded in current source material | TBD | TBD | Backlog |

## Rule

Do not add MCP servers just because they are available. Add them when repeated work is blocked by information an agent cannot reach through the repo, docs, or normal tools.
