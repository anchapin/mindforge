# MindForge

> Your sovereign AI operating system. Multi-agent team, persistent memory,
> draft-first workflow, 24/7 proactive execution — all self-hosted.

[![CI](https://github.com/alex/mindforge/actions/workflows/ci.yml/badge.svg)](https://github.com/alex/mindforge/actions)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://docker.com)

## Features

- **Multi-agent team** — COO, CMO, Researcher, Engineer agents sharing persistent memory
- **Draft-first workflow** — every external action pauses for human approval
- **Persistent memory** — semantic (ChromaDB), episodic (PGLite), writing style profile
- **Skills system** — YAML-defined task chains with branching, retry, and approval gates
- **24/7 proactive execution** — Temporal workflows for email monitoring and follow-ups
- **Local inference** — Ollama for simple tasks, OpenRouter for complex ones
- **864+ integrations** — Composio Cloud (Phase 4), direct API for Phase 1–3

## Quick Start

```bash
git clone https://github.com/alex/mindforge.git
cd mindforge
cp .env.example .env        # add OPENROUTER_API_KEY and FERNET_KEY
make setup                  # install deps, pull containers
make dev                    # start services + hot reload
# Open http://localhost:3000
```

See [SPEC.md](SPEC.md) for the full design specification.

## Architecture

```
┌─────────────┐     WebSocket      ┌──────────────────┐
│  React UI   │◄──────────────────►│  FastAPI backend  │
│  (Port 3000)│                    │   (Port 8000)    │
└─────────────┘                    └────────┬─────────┘
                                            │ IPC
                              ┌─────────────┼─────────────┐
                              ▼             ▼             ▼
                         ChromaDB        PGLite        Temporal
                        (vectors)       (tasks)      (workflows)
```

## Project Structure

| Path | Purpose |
|---|---|
| `backend/` | FastAPI + LangGraph + memory stores |
| `frontend/` | React + Zustand dashboard |
| `backend/skills/skills/` | YAML skill definitions |
| `backend/tools/` | Integration tool implementations |
| `backend/tests/` | Unit, integration, E2E tests |
| `compose.yaml` | Service composition |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). All contributions are welcome — see the
good first issue tag for beginner-friendly tasks.

## License

AGPL-3.0 — see [LICENSE](LICENSE).
