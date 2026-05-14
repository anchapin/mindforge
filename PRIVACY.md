# Privacy Policy

MindForge is a **self-hosted, local-only** AI agent platform. All data is stored
on your machine. This document describes what data is collected, how it is stored,
and your rights.

---

## What Data Is Stored

MindForge stores the following data locally:

| Data | Where | Purpose |
|---|---|---|
| Task descriptions & results | PGLite (`mindforge.db`) | Episodic memory — enables agents to recall prior tasks |
| Semantic memory embeddings | ChromaDB (`/app/data/chroma`) | Fast similarity search over past context |
| Writing style profiles | PGLite | Per-project tone and format preferences |
| Skill definitions | `backend/skills/skills/` (YAML) | Agent behaviour scripts |
| Integration credentials | `.env` (AES-256-GCM encrypted in PGLite) | API keys for OpenRouter, Ollama, etc. |
| Draft documents | PGLite | Pending approval documents before execution |

---

## How Long Data Is Retained

Data is retained indefinitely until explicitly deleted. MindForge does **not**
automatically purge old data.

---

## How to Request Data Export (GDPR/CCPA)

To export all data for a project:

```bash
#导出项目所有数据为 JSON
./scripts/export.sh <project_id>
```

This writes all PGLite records and ChromaDB vectors for the project to a JSON file.

---

## How to Delete Your Data

To permanently delete all data for a project:

```bash
# 删除项目所有数据（PGLite + ChromaDB）
./scripts/delete_project.sh <project_id>
```

⚠️ This is irreversible. All task history, memory, and drafts for the project will be lost.

---

## Third-Party Data Processing

When using **OpenRouter** for LLM inference, your prompts (task descriptions,
retrieved memory, integration responses) are sent to OpenRouter's servers.
OpenRouter acts as a data processor under GDPR — their
[Privacy Policy](https://openrouter.ai/privacy) governs data retention.

For maximum privacy, use **Ollama** (fully local — no data leaves your machine).

---

## Local-Only Nature

MindForge does not expose any network services by default. The API server
binds to `localhost` only. All data stays on your machine unless you explicitly
configure port forwarding or a reverse proxy.

---

## Credential Security

- `.env` contains API keys and the Fernet encryption key — treat it like a password
- Credentials stored in PGLite are encrypted at rest with AES-256-GCM
- HMAC signatures on semantic memory prevent injection tampering
- Never commit `.env` to version control

---

*Last updated: 2026-05-13*
