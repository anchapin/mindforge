# agents.md — For AI Coding Agents

You are working on MindForge, a self-hosted multi-agent AI operating system.
This file tells you how this codebase is organized and how to work in it.

## What This Project Is

MindForge is a local AI agent platform. A human user gives it tasks ("summarize my
GitHub commits", "draft a reply to this email"). Specialized agents (COO, CMO,
Researcher, Engineer) retrieve memories, call integrations, and draft outputs.
Every external action goes through a human approval gate before execution.

## Repository Layout

```
~/mindforge/
├── SPEC.md                    # Full design specification — READ THIS FIRST
├── backend/
│   ├── main.py                # FastAPI entry point
│   ├── agents/
│   │   ├── supervisor.py      # LangGraph supervisor — routes tasks to agents
│   │   ├── coo.py             # COO agent — orchestration
│   │   ├── cmo.py             # CMO agent — writing and content
│   │   ├── researcher.py       # Research agent — analysis and retrieval
│   │   └── engineer.py        # Engineer agent — code and GitHub
│   ├── memory/
│   │   ├── store.py           # SharedMemoryStore facade — USE THIS for all memory access
│   │   ├── semantic.py        # ChromaDB vector memory
│   │   ├── episodic.py        # PGLite task history
│   │   └── style.py           # Writing style profile
│   ├── skills/
│   │   ├── registry.py        # Skill loader — validates and executes skill YAML
│   │   └── skills/            # YAML skill files — EDIT HERE to add skills
│   ├── tools/                 # Integration tool implementations
│   │   └── registry.py        # ToolRegistry — ALL tools must be registered here
│   └── db/
│       └── schema.sql          # PGLite schema
├── frontend/
│   └── src/
│       ├── components/         # React components
│       └── stores/            # Zustand state stores
├── compose.yaml               # Docker services
├── Makefile                  # Developer commands: make dev / make test / make lint
└── .env.example               # Required env vars
```

## Key Rules for AI Agents

### 1. Always read SPEC.md before making architectural changes
This is not a typical web app. The agent runtime, memory stores, and skill system
have specific design constraints documented in SPEC.md. Changing the memory layer
without reading Section 2.2 will break retrieval.

### 2. Never bypass the approval gate
The draft-first workflow (Section 2.7.3 in SPEC.md) is not optional. Any code that
causes an external action (email send, GitHub PR, Stripe refund) without going through
the `draft → user_approval → execute` state transition is a security violation.

### 3. Skill YAML files use `yaml.safe_load()` — no Python objects
Never use `!!python/object` or any Python-specific YAML tag in skill files.
The loader is `yaml.safe_load()` (Section 3b.1 in SPEC.md). YAML tags that
deserialize to callable Python objects will be rejected at load time.

### 4. All memory writes go through SharedMemoryStore
Do not write directly to ChromaDB or PGLite. Use `SharedMemoryStore` (Section 2.2).
Direct writes bypass HMAC signing and will fail verification on read.

### 5. Test before and after any change
```bash
make test              # full suite
make lint              # ruff + mypy
# Any PR that breaks tests must also update the test
```

### 6. Follow the phase scope
Phases are documented in Section 5.1–5.4. A contribution that requires Phase 4
infrastructure (Composio, OAuth for Gmail) must be gated behind a feature flag
and not break Phase 1–3 functionality.

### 7. Integration credentials are never logged
The `scrub()` function in Section 3b.6 removes tokens, keys, and HMAC signatures
from all log output. Any new integration client must use the same scrub utility.

### 8. Ollama is the local inference tier — never required
Ollama is optional (Section 5.7.1). The system degrades gracefully to cloud-only
if Ollama is unavailable. Do not add Ollama as a hard dependency.

## How to Validate a Skill YAML

```bash
python -m backend.skills.registry validate backend/skills/skills/my-skill.yaml
```

A valid skill YAML:
- Uses only `!!str`, `!!int`, `!!float`, `!!bool`, `!!null` YAML tags
- Has no cycles in the execution graph
- Has at least one `end` node
- Has `approval_required: true` on any node that performs an external action

## How to Add an Integration

1. Implement `BaseTool` in `backend/tools/<name>.py`
2. Register it in `backend/tools/registry.py`
3. Add test fixtures in `backend/tests/fixtures/integrations/`
4. Document the auth method in `SECURITY.md`
5. Add rate limit config to `INTEGRATION_RATE_LIMITS` (Section 5.5)
6. **Memory injection defense:** If your integration fetches external content that will be
   embedded into ChromaDB (emails, web pages, calendar events), call
   `sanitize_for_memory()` from `backend/memory/sanitizer.py` before embedding.
   High-stakes integrations (`stripe`, `send_email`, `github_push`) trigger forced
   draft-approval when memory is the primary context — document this in your tool's
   docstring (see Section 3b.8 Layer 3).

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | LLM inference |
| `FERNET_KEY` | Yes | Encryption at rest |
| `CHROMA_HOST` | Auto | Vector store |
| `TEMPORAL_HOST` | Auto | Workflow engine |
| `OLLAMA_BASE_URL` | No | Local inference (optional) |
| `ENABLE_TEMPORAL` | No | Activate Temporal proactive engine (Phase 3, default `false`) |

## Contact

For questions about this codebase: open an issue or contact the maintainer directly.
