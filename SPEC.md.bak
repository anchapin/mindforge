# MindForge — Design Specification

> **Status:** Draft v0.1.0
> **Owner:** Alex
> **Last Major Review:** 2026-05-13
> **Version:** See Section 5.11 for full version strategy
>
> **Objective:** Build a self-hosted, single-user clone of surething.io's core functionality —
> a multi-agent AI team with shared persistent memory, proactive 24/7 execution, skills
> system, dashboard UI, and key integrations — using your own LLM APIs (OpenRouter / OpenAI)
> and local infrastructure. No subscriptions. No multi-tenancy. Runs on your own machine.
>
> **Why not just use SureThing?** This is a learning project and a sovereignty exercise.
> SureThing is a $15–$200/mo SaaS product. This spec documents how to build equivalent
> core functionality locally. The four role-based agents, shared memory architecture, draft-first
> workflow, and proactive monitoring loop are all replicable with open-source components.
> The main costs are LLM API calls (~$5–$50/mo) and your time.
>
> **Composio is a hard external dependency.** It is a cloud service. The self-hosted version
> in this spec uses Composio Cloud for the 864+ integrations. Phase 1 uses direct API calls
> (IMAP, GitHub, Linear, Stripe) to avoid Composio dependency for core functionality.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND                                 │
│   Dashboard (React) — task monitoring, approvals, chat,         │
│   deliverable review, skill launcher                           │
│   ⚠️ Frontend NEVER connects directly to the agent runtime.    │
└──────────────────────────┬──────────────────────────────────────┘
                           │  WebSocket / SSE  (localhost only)
                           │  REST API  (localhost only)
┌──────────────────────────▼──────────────────────────────────────┐
│                      API SERVER (FastAPI)                        │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐  │
│  │ Task       │ │ Memory     │ │ Skill      │ │ Integration│  │
│  │ Orchestr.  │ │ Manager    │ │ Executor   │ │ Manager    │  │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ WebSocket proxy (forwards agent events to dashboard)        │ │
│  │ Integration rate limiter (per-integration, in-process)      │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ⚠️ Only network-accessible component. Agent Runtime and         │
│     memory stores are backend-services, not exposed.            │
└──────────────────────────┬──────────────────────────────────────┘
                           │  Temporal workflow IPC
┌──────────────────────────▼──────────────────────────────────────┐
│                   AGENT RUNTIME LAYER                            │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Multi-Agent Orchestrator (LangGraph + Checkpointer)      │   │
│  │  ├── COO Agent  (planning, coordination, oversight)      │   │
│  │  ├── CMO Agent  (marketing, content, social)            │   │
│  │  ├── Researcher Agent (web, data, analysis)             │   │
│  │  └── Engineer Agent (code, GitHub, devops)                │   │
│  │                                                              │   │
│  │  LangGraph checkpointer: SQLite (single-file persistence)│   │
│  │  → enables task state persistence across restarts          │   │
│  │  → long-running tasks can be resumed mid-execution        │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Shared Memory System                                       │   │
│  │  ├── Semantic Memory  → ChromaDB (vector store)            │   │
│  │  ├── Episodic Memory  → PGLite (SQL — task history)       │   │
│  │  ├── Style Memory     → PGLite (user writing profile)     │   │
│  │  └── Procedural Mem.  → PGLite (skills + patterns)       │   │
│  │                                                              │   │
│  │  ⚠️ ChromaDB and PGLite are SEPARATE stores with a        │   │
│  │    defined interface: see Section 2.2 Interface Contract   │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                   EXTERNAL SERVICES                              │
│  Direct API calls (Gmail, GitHub, Linear, Stripe, etc.)       │
│  IMAP/SMTP Email (generic email skill)                          │
│  Temporal self-hosted (workflow engine for 24/7 tasks)          │
│  Composio Cloud (864+ integrations — optional, Phase 4)         │
└──────────────────────────────────────────────────────────────────┘
```

**Technology stack (single-user, self-hosted):**

| Layer | Recommended | Alternative | Note |
|---|---|---|---|
| Agent runtime | LangGraph (stateful, studio UI) | AutoGen, CrewAI | Checkpointer required for task persistence |
| Vector memory | ChromaDB (self-hosted) | Weaviate, Qdrant | PGLite has no vector type — separate store required |
| Relational memory | PGLite (single-file SQLite) | SQLite directly | `EpisodicMemory`, `WritingProfile`, `Skill` tables |
| Dashboard | React + Vite + Tailwind | Next.js | Never connects directly to agent runtime |
| API server | FastAPI (Python) | — | Listens on `127.0.0.1` only; no auth needed (localhost) |
| App integrations | Direct API calls | MCP servers | Direct: GitHub, Linear, Stripe, IMAP for Phase 1 |
| Background jobs | Temporal (self-hosted) | — | Persistent workflows, retry/DLQ built in |
| Realtime | WebSockets via FastAPI | SSE | Dashboard connects via `ws://127.0.0.1:8000/ws` |
| LLM provider | OpenRouter (unified API) | OpenAI direct | Circuit breaker: gpt-4o → claude-3.5 → gemini-2 |
| Auth | None (localhost boundary) | — | No user accounts, no JWT; OS-level access control |

> **No auth needed.** Since everything runs on a single machine under a single user account,
> the OS provides the security boundary. The API server binds to `127.0.0.1` only. If you
> want to access the dashboard from another device on your LAN, use an SSH tunnel
> (`ssh -L 8000:localhost:8000 user@host`) rather than exposing the server to the internet.

---

## 2. Core Subsystems

### 2.1 Multi-Agent Orchestrator

SureThing runs a team of role-specialized agents that share state. The key differentiator from
a single LLM is that each agent has a stable identity, a specialized system prompt, and
access to shared memory and shared tools. They coordinate via a shared task queue.

**Agent roles (from the marketing site):**

| Agent | Role | Responsibilities |
|---|---|---|
| COO | Planner/Overseer | Project management, coordination, progress reporting |
| CMO | Marketing/Content | Content creation, social, campaigns |
| Researcher | Data/Web | Web research, competitive intel, data synthesis |
| Engineer | Code/DevOps | GitHub, code review, automation scripts |

**Orchestration patterns to consider:**

1. **Supervisor pattern** (LangGraph): A supervisor agent (the "you" in SureThing's
   "you're the chairman, it executes" framing) routes tasks to specialized sub-agents.
2. **Shared-huddle pattern**: All agents are peers; a planning agent decomposes a task and
   hands off to the appropriate specialist, with memory as the shared communication bus.
3. **Skill-as-agent pattern**: Each Skill is a specialized agent/sub-graph. The orchestrator
   selects and composes skills based on the user's goal.

**Implementation (LangGraph supervisor):**

```python
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

llm = ChatOpenAI(model="gpt-4o", temperature=0)

AGENT_ROLES = {
    "coo": "You are the COO agent. Plan, coordinate, oversee. "
           "You delegate to specialists and synthesize their output.",
    "cmo": "You are the CMO agent. Handle marketing, content, social. "
           "Produce drafts for user review.",
    "researcher": "You are the Researcher agent. Handle web research, "
                  "data analysis, competitive intel.",
    "engineer": "You are the Engineer agent. Handle code, GitHub, devops tasks."
}

def supervisor(state):
    """Router that decides which agent handles the next step."""
    task = state["current_task"]
    if "write" in task or "content" in task or "social" in task:
        return "cmo"
    elif "code" in task or "github" in task or "deploy" in task:
        return "engineer"
    elif "research" in task or "analyze" in task or "find" in task:
        return "researcher"
    else:
        return "coo"

# Build graph...
```

### 2.2 Persistent Memory System

This is SureThing's most defensible differentiator. The memory system has four layers:

| Layer | Store | Schema | Bounded? |
|---|---|---|---|
| Semantic Memory | ChromaDB | `id, project_id, text, embedding, metadata, created_at` | Yes — TTL or LRU eviction |
| Episodic Memory | PGLite | `EpisodicMemory` table (see Section 4) | Yes — configurable retention window |
| Writing Style Memory | PGLite | `WritingProfile` table | Yes — replaced on explicit update |
| Procedural Memory | PGLite | `Skill` table + execution patterns | Yes — skill versioning |

**Memory interface contract.**

ChromaDB and PGLite are separate stores. All agents access memory through `SharedMemoryStore`:

```python
class SharedMemoryStore:
    """Sole interface for all memory read/write operations."""

    def read(
        self,
        query: str,
        project_id: str | None = None,  # scopes memory to a project/client
        memory_types: list[str] = ["semantic", "episodic", "style"],
    ) -> str:
        results = []

        if "semantic" in memory_types:
            results.append(self.vector_store.similarity_search(
                query, k=5, filter={"project_id": project_id} if project_id else {}
            ))

        if "episodic" in memory_types:
            task_type = self.classify_task_type(query)  # rule-based classifier
            results.append(self.db.query_episodic(
                project_id=project_id,
                task_type=task_type,
                limit=5,
            ))

        if "style" in memory_types:
            results.append(self.db.get_writing_profile().format())

        return self.format_combined_context(results)
```

**`classify_task_type(query: str) -> str` — defined as rule-based keyword matching:**

```python
import re

TASK_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("github",   ["github", "commit", "pr ", "pull request", "repository", "git"]),
    ("email",    ["email", "reply", "inbox", "mail", "send", "draft"]),
    ("research",  ["research", "find", "lookup", "analyze", "competitor", "market"]),
    ("content",  ["write", "blog", "post", "tweet", "linkedin", "content", "copy"]),
    ("finance",  ["refund", "invoice", "billing", "stripe", "revenue", "cost"]),
    ("engineering", ["code", "deploy", "build", "debug", "test", "ship"]),
    ("operations", ["schedule", "calendar", "meeting", "task", "project"]),
]

def classify_task_type(query: str) -> str:
    query_lower = query.lower()
    for task_type, keywords in TASK_TYPE_RULES:
        if any(kw in query_lower for kw in keywords):
            return task_type
    return "general"
```

> **Rationale:** Keyword matching is deterministic, has zero latency, and zero cost. It is correct for ~80% of cases. An LLM classifier is more accurate but adds latency and cost on every memory retrieval. Use keyword matching as the default; upgrade to an LLM classifier only if recall is demonstrably poor.

**Write concurrency.** All `write()` calls go through a queue (Python `asyncio.Queue` or Celery task) rather than writing directly. This serializes writes, prevents ChromaDB corruption, and allows deduplication before insertion:

```python
async def write(self, memory_type: str, content: dict, project_id: str | None = None):
    # Enqueue — write happens async
    await self._write_queue.put({
        "memory_type": memory_type,
        "content": content,
        "project_id": project_id,
    })

# Background worker processes the queue:
async def _process_writes(self):
    while True:
        item = await self._write_queue.get()
        # Deduplicate: check if similar content already stored within 24h
        if not await self._is_duplicate(item, lookback_hours=24):
            await self._write_to_store(item)
        self._write_queue.task_done()
```

**Memory retention / eviction:**
- Semantic memory: TTL of 90 days by default; reset on explicit user confirmation; LRU cap of 10,000 vectors per `project_id`
- Episodic memory: 180-day rolling window; failed task records kept until resolved
- Writing style: replaced only on explicit user update (never auto-expires)
- Skills: current version only; old versions archived for rollback

**Project/client scoping.** Every memory record has a `project_id` (nullable for global context). This prevents cross-contamination when a user manages multiple clients or businesses:

- `project_id = None` → global context (user preferences, writing style, general goals)
- `project_id = "proj_abc"` → project-specific context (client names, project details, milestones)

The supervisor/COO agent sets `project_id` from the task description on first invocation
using a tiered heuristic:

1. **Explicit project mention:** If the task description contains a known project name
   or client name already in memory, use that project's `project_id`.
2. **Integration context:** If the task involves a GitHub repo, Linear team, or Stripe
   customer, extract the project from the integration context (the integration credential
   is already project-scoped in the `Integration` table).
3. **Fallback:** Default to `project_id = None` (global context). The dashboard renders
   a project badge on the task card; the user can correct it inline if wrong.

The task record's `project_id` is locked at invocation time and does not change during
execution — this prevents mid-task project drift.

**`format_combined_context(results: list[MemoryResult]) -> str`:**

```python
def format_combined_context(results: list[MemoryResult]) -> str:
    """Combine heterogeneous memory results into a single context string."""
    sections = []
    for result in results:
        if result.memory_type == "semantic":
            sections.append("## Relevant Background\n" + result.formatted())
        elif result.memory_type == "episodic":
            sections.append("## Recent Similar Tasks\n" + result.formatted())
        elif result.memory_type == "style":
            sections.append("## Your Writing Style\n" + result.formatted())
    return "\n\n".join(sections)
```

**Writing Style Memory — how it actually works:**

"Building" a writing style profile is not magic — it is structured extraction:

1. **Input:** Approved emails, Slack messages, documents — content the user has explicitly validated as "this is how I write"
2. **Extraction (LLM, one-time per approved item):** When a user approves a draft, call:
   ```
   Extract the following from this text: {approved_draft}
   - tone: formal | semi-formal | casual | friendly
   - sentence_length: short (<10 words avg) | medium | long (20+ words avg)
   - first_person_usage: I/we/they/none
   - signature_phrases: [list of 3-5 recurring phrases]
   - greeting_style: how this person opens emails
   - signoff_style: how this person closes emails
   ```
3. **Storage:** Extracted fields stored in `WritingProfile` table in PGLite
4. **Injection:** At task start, `format()` renders the profile as a style guide in the system prompt:
   ```
   You are drafting as Alex. His style:
   - Tone: semi-formal, direct, action-oriented
   - Avg sentence length: medium-short
   - First person: "I" for personal topics, "we" for company announcements
   - Signature phrases: ["let's move forward", "happy to help", "TL;DR"]
   - Greeting: Hi [Name], (never "Hey" or "Dear")
   - Sign-off: Cheers (never "Best" or "Thanks")
   ```
5. **Feedback loop:** If the user edits a draft significantly, extract from the edited version and update the profile. If they approve without edits, the current profile is reinforced.

> **Key insight:** The writing style profile is not a generative model — it is a structured dictionary rendered into the prompt. The LLM follows it. Profile updates are explicit (edited by user) or extracted (from approved drafts), never inferred silently.

### 2.3 Skills System

Skills are SureThing's unit of reuse. Each skill is a self-contained prompt template +
tool specification + a defined execution graph (not a linear list). From the Skills page:

| Skill | Category | What it does |
|---|---|---|
| Side Business Launcher | Entrepreneurship | Profile → Recommend → Build → Deploy → Grow pipeline |
| Fandom Automation | Community | Sync wiki edits to Fandom via bot accounts |
| Distill Your Own Skill | Productivity | Turn a completed task into a reusable skill |
| Custom Email Sync | Productivity | IMAP/POP3/SMTP email read/sort/send |
| GitHub Daily Summary | Developer Tools | Fetch 24h commits/PRs, produce PM-style summary |
| Task Load Monitor | Productivity | List active tasks sorted by execution load |
| Subscription Refund | Finance/Negotiation | Multi-round autonomous SaaS refund negotiation |

**Formal Skill YAML schema (v1):**

```yaml
version: "1"
name: subscription-refund
description: >
  Fully autonomous multi-round negotiation to recover a refund
  for an unused SaaS subscription billing cycle.
category: finance
trigger:
  type: keyword | intent_classifier | explicit_only
  keywords: [refund, cancel, subscription, billing]  # for keyword type
  intent: ["request_refund", "cancel_subscription"]    # for intent type

execution_graph:
  type: directed_acyclic_graph  # supports branching, not just linear
  nodes:
    - id: verify
      agent: researcher
      goal: "Verify subscription status and usage"
      tools: [stripe_api, email_fetch]
      outcome_on_failure: skip_to_approve  # continue but flag
      retry:
        max_attempts: 2
        backoff_seconds: 30
    - id: draft
      agent: cmo
      goal: "Draft refund request in user's voice"
      requires_approval: true    # <-- execution PAUSES here
      approval_timeout_minutes: 1440  # 24h; auto-escalate after timeout
      memory_layers: [semantic, episodic, style]
      output_schema:   # what the draft must contain
        type: object
        fields: [subject, body, attachment_urls]
    - id: negotiate
      agent: engineer
      goal: "Submit refund via API and monitor for response"
      tools: [stripe_refund_api, email_send]
      requires_approval: true          # <-- second approval gate
      approval_timeout_minutes: 2880
      # No node-level condition needed — edge from draft handles gate.
      # Node only executes if execution reached it (draft was approved).
      retry:
        max_attempts: 3
        backoff_seconds: 60
    - id: escalate
      agent: coo
      goal: "Escalate to human: no response after 48h"
      trigger: timeout_negotiate.exceeded
      notification:
        channel: dashboard
        message: "Refund negotiation stalled — manual intervention needed"
  edges:
    - from: verify
      to: draft
      condition: verify.success       # simple string label; not evaluated Python
    - from: verify
      to: escalate
      condition: verify.failed
    - from: draft
      to: negotiate
      condition: draft.approved
    - from: draft
      to: escalate
      condition: draft.rejected
    - from: draft
      to: escalate
      condition: draft.timeout
    - from: negotiate
      to: escalate
      condition: negotiate.timeout

# NOTE: edge conditions are plain string labels, not expressions.
# The LangGraph executor resolves them using a simple dictionary lookup
# (e.g., node_state.get("verify.success") → bool). Do NOT use Python eval().
# Complex multi-variable conditions should be modeled as explicit intermediate
# nodes rather than complex expressions.

memory_layers: [semantic, episodic]

version: "1"  # skills are versioned; running executions pin their skill version
```

**Skill execution lifecycle:**

1. **Trigger** — keyword match, intent classifier (LLM call with a classification prompt), or user invokes explicitly. Explicit invocation always wins.
2. **Version pin** — the skill's YAML at the time of invocation is frozen for that execution. Updates to the skill definition do not affect running executions.
3. **Brief** — relevant memories injected per `memory_layers` in each node
4. **Draft** — agent produces output per `output_schema`, execution pauses at `requires_approval: true`
5. **Approval** — user reviews, edits, approves, or rejects within `approval_timeout_minutes`
   - **Approved:** execution continues to next node
   - **Rejected:** execution routes to `escalate` node (COO agent notified)
   - **Timeout:** execution routes to `escalate` node; dashboard notified
6. **Execute** — agent calls tools, integrations per `retry` policy
7. **Reflect** — outcome stored in episodic memory, `Skill.success_count` or `Skill.failure_count` incremented

**Skill trigger implementation (keyword + intent hybrid):**

```python
async def trigger_skill(task: str) -> Skill | None:
    # 1. Check explicit invocation first ("run the github-daily-summary skill")
    explicit = skill_registry.find_by_name(task)
    if explicit:
        return explicit

    # 2. Keyword match (fast path, no LLM call)
    for skill in skill_registry.all():
        if skill.trigger.type == "keyword":
            if any(kw in task.lower() for kw in skill.trigger.keywords):
                return skill

    # 3. Intent classifier (LLM call, only if keyword missed)
    intent = await classify_intent(task)  # lightweight LLM call
    skill = skill_registry.find_by_intent(intent)
    return skill
```

**SkillResult schema:**

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class SkillResult:
    skill_id: str
    skill_version: int
    status: "draft" | "approved" | "rejected" | "completed" | "failed" | "escalated"
    nodes_completed: list[str]
    current_node: str | None
    draft_content: dict[str, Any] | None   # frozen at draft nodes
    final_output: dict[str, Any] | None     # frozen at completion
    approval_history: list[ApprovalRecord]
    escalation_message: str | None
    error: str | None
    started_at: str   # ISO timestamp
    completed_at: str | None

@dataclass
class ApprovalRecord:
    node_id: str
    action: "approved" | "rejected" | "timeout"
    edited_content: dict[str, Any] | None  # if user edited before approving
    timestamp: str
```

### 2.4 App Integrations

Phase 1 uses direct API calls (IMAP/SMTP, GitHub, Linear, Stripe) to avoid external
dependencies. Phase 4 adds Composio Cloud for the full 864+ integration library.

| Option | Pros | Cons |
|---|---|---|
| Composio | 864 apps, auth handled, active | Costs money, external dependency |
| MCP (Model Context Protocol) | Open standard, local, free | Fewer native integrations than Composio |
| Zapier API | 6000+ Zaps, well-documented | OAuth only, expensive at scale |
| Direct API calls | Full control, no per-call cost | Massive engineering effort |
| n8n | Self-hosted, 400+ integrations | Workflow-based, not agent-native |

**Recommendation:** Use Composio for the prototype (free tier: 1000 calls/month). For a
self-hosted version, build an MCP server bridge that wraps Composio calls, or implement
the most important integrations (Gmail, Slack, GitHub, Stripe, Linear) as direct MCP
servers.

**Key integrations (from the integrations page, 864 total):**

| App | Category | What SureThing does with it |
|---|---|---|
| Gmail | Collaboration | Read inbox, learn writing style, draft replies, triage |
| Slack | Collaboration | Monitor channels, summarize threads, draft responses |
| Linear | Productivity | Create/update/track issues, sprint management |
| GitHub | Developer | Commit activity, PR summaries, issue management |
| Stripe | Finance | Revenue monitoring, refund negotiation, billing |
| HubSpot | CRM | Contact management, deal updates, call logging |
| Salesforce | CRM | Enterprise sales automation |
| Facebook | Marketing | Page management, post scheduling |
| Instagram | Marketing | Business/creator account content |
| LinkedIn | Marketing | Professional networking, content scheduling |
| Reddit | Marketing | Subreddit monitoring, viral content tracking |

### 2.5 Dashboard

The dashboard is the "reporting line" — the UI that makes you "the chairman, not the bottleneck."
From the product: "You stay in control without being the bottleneck."

**Dashboard features:**
1. **Chat interface** — talk to your AI team, give directives
2. **Task tracker** — view running/completed/pending tasks, their status, agents involved
3. **Deliverable review** — approve/reject drafts before execution
4. **Memory viewer** — inspect what the system knows about you and your projects
5. **Skill launcher** — browse and activate skills
6. **Integration manager** — connect/disconnect apps, manage OAuth flows
7. **Credit usage** — track API consumption (mapped from SureThing's credit system)

**Real-time updates:** Tasks report progress via WebSocket/SSE. The agent can "ping" the
dashboard when it needs a decision (draft approval, clarification).

**Draft-first workflow UI pattern:**
- Agent produces a draft (email, post, report) and pauses
- Dashboard shows a notification: "CMO Agent drafted a reply to [email thread]. Review?"
- User edits/approves → agent continues to execution
- User rejects → agent revises based on feedback

**Chairman / Human-in-the-Loop protocol:**

The supervisor does not blindly delegate — it surfaces ambiguity before acting:

```
User: "I need to respond to this customer complaint"

Supervisor analysis:
  - Intent: email_response (clear)
  - Customer tone: escalated (from email subject)
  - Priority: high
  - Draft-first required: yes
  - Ambiguity: what is our return/exchange policy for this product?
    → SURFACE TO USER: "Should I offer a refund, replacement, or store credit?"

User: "Replacement"

Supervisor: executes with that constraint locked in memory
```

**Clarification request protocol (WebSocket message):**

```typescript
// Agent → Dashboard: request for human decision
interface AgentClarification {
  type: "clarification_request";
  task_id: string;
  node_id: string;
  question: string;          // "Should I offer a refund or replacement?"
  options: string[];          // ["Refund", "Replacement", "Store credit"]
  context_summary: string;    // condensed relevant memories
  deadline_iso: string;       // if no response by this time, escalate
}

// Dashboard → Agent: human decision
interface HumanDecision {
  type: "clarification_response";
  task_id: string;
  node_id: string;
  decision: string;           // one of the options, or free-text
  edited_draft?: object;     // optional edited version
}
```

**WebSocket message protocol (full set):**

```typescript
type WSMessage =
  | { type: "task_created";        task_id: string; skill_name: string | null }
  | { type: "task_status_update";  task_id: string; status: TaskStatus; agent_role: string }
  | { type: "draft_ready";          task_id: string; node_id: string; draft: DraftContent;
      awaiting_approval: true;     approval_deadline_iso: string }
  | { type: "approval_resolved";   task_id: string; node_id: string;
      action: "approved" | "rejected" | "timeout" }
  | { type: "clarification_request"; task_id: string; node_id: string;
      question: string; options: string[]; context_summary: string }
  | { type: "agent_message";       task_id: string; agent_role: string;
      message: string }             // agent talking to the chairman
  | { type: "task_completed";      task_id: string; final_output: object }
  | { type: "task_failed";         task_id: string; error: string; escalated: boolean }
  | { type: "skill_triggered";     skill_id: string; task_id: string }
```

**Frontend state management:** React + Zustand (not Redux — simpler, less boilerplate).
Task state is the canonical store; WebSocket messages update the task store directly.
TanStack Query manages server data fetching (skills catalog, integration list, user profile).

### 2.6 Proactive Execution (24/7)

SureThing's "always on" capability requires background task scheduling:

**Proactive capabilities (from the research page):**
- Monitors inbox overnight and flags priority items
- Detects calendar conflicts before you notice
- Follows up on unreplied emails
- Catches billing anomalies, renewal deadlines

**Implementation (Temporal):**

```python
# Temporal workflow for email monitoring
from temporalio import workflow
from datetime import timedelta

@workflow.run
async def email_monitor_workflow():
    while True:
        emails = await workflow.execute_activity(
            check_inbox,
            start_to_close_timeout=timedelta(seconds=30),
        )
        for email in emails:
            if is_urgent(email) and not already_handled(email):
                await workflow.execute_activity(
                    draft_response,
                    email,
                    start_to_close_timeout=timedelta(minutes=2),
                )
                await workflow.execute_activity(
                    notify_dashboard,
                    f"Urgent email from {email.sender}: draft awaiting approval",
                    start_to_close_timeout=timedelta(seconds=10),
                )
        await asyncio.sleep(1800)  # check every 30 minutes

@workflow.run
async def followup_check_workflow():
    while True:
        unreplied = await query_unreplied_threads(days_threshold=3)
        for thread in unreplied:
            draft = await workflow.execute_activity(
                draft_followup,
                thread,
                start_to_close_timeout=timedelta(minutes=2),
            )
            await workflow.execute_activity(
                notify_dashboard,
                f"Unreplied thread ({thread.subject}): follow-up draft ready",
                start_to_close_timeout=timedelta(seconds=10),
            )
        await asyncio.sleep(86400)  # check once per day
```

---

## 2.7 User Experience Design

This section specifies the UI/UX for every user-facing surface. Each user story defines
the components involved, the states those components can be in, and the interactions
the user can take. The frontend stack is React + Zustand + TanStack Query (Section 1).
All WebSocket message types are in Section 2.5.

---

### 2.7.1 Onboarding — First Run ("I just installed it. What do I do?")

**Goal:** Guide a new user from launch to their first completed task in under 5 minutes.

**OnboardingWizard component (3 steps):**

```
Step 1: "Connect your first tool"
  ┌──────────────────────────────────────────────────────────────┐
  │  SureThing Local Clone                            [×]        │
  │                                                               │
  │  Welcome. Let's set up your AI team.                         │
  │                                                               │
  │  Which would you like to connect first?                       │
  │                                                               │
  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
  │  │  📧 Email   │  │  💻 GitHub  │  │  💳 Stripe  │        │
  │  │  IMAP/SMTP  │  │  API token  │  │  Read-only  │        │
  │  └─────────────┘  └─────────────┘  └─────────────┘        │
  │                                                               │
  │  [+ Add another integration]                                  │
  │                                                               │
  │                              [Skip for now →]  [Continue →] │
  └──────────────────────────────────────────────────────────────┘
```

**Step 2: "Tell us how you write"**
- Option A: Paste 3 example emails (textarea × 3) — LLM extracts style profile
- Option B: Fill in structured form (tone dropdown, sentence length, signature phrases)
- Both paths create a `WritingProfile` record on submission

**Step 3: "Meet your team"**
- Shows agent cards for COO, CMO, Researcher, Engineer with one-line descriptions
- "Your job is the chairman. They do the work. You review and approve."
- [Launch Dashboard →]

**EmptyState component (shown when no tasks exist):**

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   Your AI team is ready.                                     │
│                                                              │
│   Try: "Summarize my GitHub commits from the last 24 hours"  │
│                                                              │
│   ┌────────────────────────────────────────────────────┐    │
│   │  What would you like to do?                        │    │
│   │  [Ask your AI team...                            ] │    │
│   │                                      [Send →]     │    │
│   └────────────────────────────────────────────────────┘    │
│                                                              │
│   Or browse [Skills] to get started faster.                 │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**EmptyState when integrations exist but memory is empty:**
Shows a "seed memory" prompt: "Tell us about your current projects" with a textarea.
Submitting creates the first `SemanticMemory` entry.

---

### 2.7.2 Task Submission — Chat Interface ("I want the AI to do something")

**ChatInterface component:**

```
┌──────────────────────────────────────────────────────────────┐
│ SureThing Local                      [🔔 2] [⚙️] [☰]        │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ You — 2 min ago                                     │    │
│  │ Summarize my GitHub commits from the last 24 hours  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 🤖 Engineer Agent — Just now                        │    │
│  │                                                      │    │
│  │ [Spinner] Routing to Engineer agent...             │    │
│  │                                                      │    │
│  │ ┌──────────────────────────────────────────────┐   │    │
│  │ │ 🔄 Working on it...                           │   │    │
│  │ │ Running: GitHub Daily Summary (v1)           │   │    │
│  │ │                                                │   │    │
│  │ │ Step 1/3: Fetching commits... ✓              │   │    │
│  │ │ Step 2/3: Analyzing patterns... →            │   │    │
│  │ │ Step 3/3: Drafting summary...                  │   │    │
│  │ └──────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  What would you like to do?                        │    │
│  │  [Ask your AI team...                            ] │    │
│  │                                      [Send →]     │    │
│  └────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

**Task submission states:**

| UI State | Trigger | What user sees |
|---|---|---|
| `pending` | Message sent, server received | Spinner + "Routing..." |
| `running` | Supervisor begins execution | Live progress: "Step 1/3: Fetching commits... →" |
| `draft` | Approval gate hit | Amber card: "Review required" with [View Draft →] button |
| `executing` | Draft approved | "Executing..." indicator |
| `completed` | Success | Green checkmark, final output card |
| `failed` | Error | Red card with error message, [Retry] button |

**ClarificationRequest modal (triggered by `clarification_request` WS message):**

```
┌──────────────────────────────────────────────────────────────┐
│  🤖 COO Agent needs your input                    [×]        │
│                                                              │
│  To respond to this customer complaint, I need to know:     │
│                                                              │
│  Should I offer a refund, replacement, or store credit?     │
│                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐   │
│  │   Refund       │  │  Replacement  │  │Store credit │   │
│  └────────────────┘  └────────────────┘  └──────────────┘   │
│                                                              │
│  Or tell me in your own words:                               │
│  [                                          ]                │
│                                                              │
│                                         [Submit] [Cancel]   │
└──────────────────────────────────────────────────────────────┘
```

The modal is blocking — the task does not proceed until the user responds, times out,
or cancels. The task card in the task tracker shows "Awaiting your input."

**ProjectBadge (shown on task card):**

```
┌─────────────────────────────────────────────────────┐
│ [Acme Corp 🔹] Task #23 · Engineer Agent           │
│ ...
└─────────────────────────────────────────────────────┘
```

Tappable: tapping the badge opens an inline dropdown to reassign the project.
The badge color is derived from a hash of `project_id` for visual differentiation.

---

### 2.7.3 Draft Approval — DraftReview Component

**DraftReview card (inline expansion in task list):**

```
┌─ Task #24: Refund request — Acme Corp ──────────────────┐
│                                                        │
│  ⏳ Awaiting your approval           [24h 12m left]    │
│                                                        │
│  ┌─ Draft from CMO Agent ─────────────────────────┐   │
│  │ Subject: Re: Your recent subscription          │   │
│  │                                                  │   │
│  │ Hi Sarah,                                       │   │
│  │                                                  │   │
│  │ Thank you for reaching out. I'd be happy to     │   │
│  │ help with your request. As discussed, we're    │   │
│  │ able to offer a full refund for your last      │   │
│  │ billing cycle.                                  │   │
│  │                                                  │   │
│  │ [Edit draft before approving]                   │   │
│  └──────────────────────────────────────────────────┘   │
│                                                        │
│  [Reject — tell us what to change]  [Approve & Send]  │
│                                                        │
└────────────────────────────────────────────────────────┘
```

**Editing before approval:** Clicking "Edit draft before approving" opens an inline
editor replacing the read-only draft content. The edited content is sent back via
`HumanDecision.edited_draft` in the `clarification_response` WS message. A small
badge shows "You modified this draft" when edits are detected.

**Timeout state (draft passed approval window):**

```
┌─ Task #24: Refund request — Acme Corp ──────────────────┐
│                                                        │
│  ⛔ Approval window expired          [Escalated to COO]│
│                                                        │
│  ┌─ Original draft (not sent) ────────────────────┐   │
│  │ ...                                            │   │
│  └────────────────────────────────────────────────┘   │
│                                                        │
│  [View what happened]              [Draft new response] │
│                                                        │
└────────────────────────────────────────────────────────┘
```

The task is now in `failed` state with `escalation_message` set. The escalation
notification appears as a red bell notification with "COO notified."

**Reject flow:** Clicking "Reject — tell us what to change" opens a text field
(required, min 10 characters):

```
┌────────────────────────────────────────────────────────┐
│ What should change?                                    │
│                                                        │
│ [The tone is too formal. Make it more friendly and    ]
│ [direct. Also shorten the opening paragraph.]          │
│                                                        │
│                    [Send feedback & rerun] [Cancel]   │
└────────────────────────────────────────────────────────┘
```

Feedback is stored in `TaskStep.feedback` and `EpisodicMemory.feedback` so the
agent can incorporate it on retry.

---

### 2.7.4 Task Tracker — System Activity & Background Monitoring

**TaskTracker component (full page view):**

```
┌──────────────────────────────────────────────────────────────┐
│  Tasks          System Activity       Skills      Settings   │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  [All ▼]  [Running] [Pending] [Completed] [Failed] [Draft] │
│                                                              │
│  ┌─ 🔴 ACTIVE — 3 tasks ────────────────────────────────┐    │
│  │                                                       │    │
│  │  #27  🔵 Acme Corp      CMO Agent      Draft review  │    │
│  │       "Launch email for new feature"   ⏳ 2h left    │    │
│  │                                                       │    │
│  │  #26  🔵 Acme Corp      Researcher     Running       │    │
│  │       "Competitor pricing analysis"    Step 2/4 →    │    │
│  │                                                       │    │
│  │  #25  ⚪ (global)        Engineer       Completed ✓  │    │
│  │       "GitHub daily summary"                          │    │
│  └───────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─ SYSTEM ACTIVITY (last 24h) ────────────────────────┐    │
│  │                                                       │    │
│  │  📨 3 follow-up drafts created (all approved)        │    │
│  │  ⚠️  Billing anomaly detected: Stripe renewal $149   │    │
│  │     [View →] [Dismiss]                               │    │
│  │  📅 Calendar conflict: Team sync 2pm overlaps with  │    │
│  │     client call [Resolve →]                         │    │
│  │  🔴 Temporal worker restarted at 03:12 (recovered)  │    │
│  │                                                       │    │
│  │  [View full activity log →]                          │    │
│  └───────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

**Pause/resume proactive monitoring:**

```
⚙️ Settings > Proactive Monitoring
────────────────────────────────────────────────
[  ✓ ] Monitor inbox overnight (every 30 min)
[  ✓ ] Follow-up on unreplied emails (3-day threshold)
[  ✓ ] Alert on billing anomalies
[  ✓ ] Calendar conflict detection

Email check interval: [30 min ▼]
Alert threshold:     [$50 USD ▼]

[Save preferences]
```

**Monitoring failure alert (bell notification):**

```
🔴 Background monitoring stopped — action needed
   The email monitoring worker stopped at 03:12 AM.
   [View status] [Restart monitoring]
```

Shown when the Temporal worker fails and does not auto-recover within 5 minutes.
The `proactive_monitoring_enabled` boolean in `UserPreference` is the master kill
switch; the per-workflow toggles are secondary.

---

### 2.7.5 Memory Viewer — "What does it know about me?"

**MemoryViewer component:**

```
┌─ Memory ───────────────────────────────────────────────────┐
│                                                              │
│  [All] [Semantic] [Episodes] [Writing Style] [Skills]     │
│                                                              │
│  Search: [                                          ] [🔍] │
│                                                              │
│  ┌─ Writing Style ─────────────────────────────────────┐   │
│  │  Tone: Semi-formal, direct                           │   │
│  │  Avg sentence: Medium (12–18 words)                  │   │
│  │  First person: "I" for decisions, "we" for company   │   │
│  │  Signature phrases: "happy to help", "let's move     │   │
│  │  forward", "TL;DR"                                   │   │
│  │  Greeting: "Hi [Name]," (never "Hey" or "Dear")      │   │
│  │  Sign-off: "Cheers"                                   │   │
│  │                                        [Edit style ↗] │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─ Recent Episodes (last 30 days) ────────────────────┐   │
│  │  [Acme Corp] CMO · Email response · Completed        │   │
│  │  [Acme Corp] Researcher · Pricing analysis · Done    │   │
│  │  (global) Engineer · GitHub summary · Completed      │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─ Semantic Memory (top 5 matches) ───────────────────┐   │
│  │  "Acme Corp prefers replacement over refund"         │   │
│  │    Retrieved by: CMO Agent · 3 tasks ago · v1.2      │   │
│  │                                          [🗑️] [📌] │   │
│  │  ...                                                   │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  Danger zone:                                               │
│  [Export all memories]  [Delete all memories]               │
└──────────────────────────────────────────────────────────────┘
```

**Selective memory deletion:** Each semantic memory entry has a trash icon.
Clicking it shows a confirmation: "Delete this memory? The agent will re-learn
it if relevant to future tasks." Episodic memories can be deleted by project or
by date range.

**"What was used" disclosure (task detail view):**

```
┌─ Task #26 Detail ────────────────────────────────────────┐
│                                                         │
│  Question: "What's Acme's refund policy?"               │
│  Agent: Researcher · Status: completed ✓                │
│                                                         │
│  ┌─ Context used ──────────────────────────────────┐   │
│  │  📄 Episodic: "Customer prefers replacement"    │   │
│  │     (from task #24, CMO Agent, 2 days ago)       │   │
│  │  📄 Semantic: "Acme Corp contract terms"        │   │
│  │     (v1.3, vector match 0.91)                    │   │
│  │  📄 Style: greeting "Hi [Name]," ✓               │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  Answer: "Based on our conversation, Acme Corp's       │
│  policy is to offer replacement as the primary..."    │
└─────────────────────────────────────────────────────────┘
```

The "Context used" section is collapsed by default. Expanding it shows the exact
memories the agent retrieved before answering. This makes the memory system
transparent and auditable — key to the "human in the loop" design intent.

---

### 2.7.6 Skill Authoring & Debugging — SkillEditor + TaskDebug

**SkillEditor component (YAML + DAG preview split view):**

```
┌─ Skill Editor: subscription-refund ──────────────────────────┐
│                                                               │
│  Name: [subscription-refund                           ]       │
│  Category: [Finance/Negotiation ▼]                            │
│  Agent: [researcher ▼]                                        │
│  Trigger: [keyword ▼]  Keywords: [refund, cancel, billing]   │
│                                                               │
│  ┌─ YAML ─────────────────────┐ ┌─ DAG Preview ───────────┐  │
│  │                           │ │                          │  │
│  │  nodes:                   │ │   [verify]──────┐        │  │
│  │  - id: verify             │ │      │         │        │  │
│  │    agent: researcher      │ │      ▼         ▼        │  │
│  │    goal: "Verify..."      │ │   [draft]   [escalate]   │  │
│  │    tools: [stripe_api]    │ │      │                    │  │
│  │    requires_approval: true│ │      ▼                    │  │
│  │  - id: draft              │ │   [negotiate]            │  │
│  │    ...                    │ │      │                    │  │
│  │                           │ │      ▼                    │  │
│  │                           │ │   [escalate]              │  │
│  └───────────────────────────┘ └──────────────────────────┘  │
│                                                               │
│  ⚠️ Cycle detected: escalate → escalate                      │
│  ⚠️ Node "draft" has no outgoing edges                       │
│                                                               │
│  [Test with sample task]    [Save v3]    [Cancel]             │
└───────────────────────────────────────────────────────────────┘
```

The right panel renders the DAG in real time as YAML is edited. Validation errors
appear inline below the YAML editor and as red highlights on nodes in the DAG preview.
"Test with sample task" opens a modal with a textarea for the task input and shows
the execution path that would be taken — without touching live integrations.

**TaskDebug panel (expanded from task list):**

```
┌─ Task #26: Debug View ────────────────────────────────────────┐
│                                                                │
│  Status: failed · Retry count: 2/3                            │
│  Skill: Competitor Pricing Analysis v1                         │
│                                                                │
│  ┌─ Step history ────────────────────────────────────────┐   │
│  │  ✅ Step 1: research (1.2s) — Found 8 competitors      │   │
│  │  ✅ Step 2: analyze (3.4s) — Generated price table     │   │
│  │  ❌ Step 3: draft (failed after 2 retries)              │   │
│  │     Error: RateLimitError: 429 on github.com/api        │   │
│  │     Retry 1: 2s backoff → same error                    │   │
│  │     Retry 2: 4s backoff → same error                    │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                                │
│  What the agent saw at Step 3:                                │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Retrieved 3 semantic memories:                       │   │
│  │ - "Acme Corp pricing Q1 2025"                       │   │
│  │ - "Competitor X charges $99/mo"                      │   │
│  │ - "User prefers table format"                        │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                                │
│  [Retry from Step 3]  [Rerunfrom start]  [Cancel task]     │
└────────────────────────────────────────────────────────────────┘
```

The step history shows each step's duration, outcome, and any error. The "what
the agent saw" section shows the retrieved memory context at failure time. This is
the primary debugging interface for skill authors.

**Skill performance indicator (on skill cards in SkillLauncher):**

```
┌─────────────────────────────────────────────────────┐
│  📊 Subscription Refund Negotiator                   │
│     Finance · Researcher · v3                        │
│     ✅ 94% success (last 50 runs)                   │
│     ⚠️ 2 recent failures (network timeouts)         │
│                                    [Run ↗] [Edit]   │
└─────────────────────────────────────────────────────┘
```

---

### 2.7.7 Error Recovery UX

**Task failed — recoverable:**

```
┌─ Task #26 ────────────────────────────────────────────────┐
│                                                          │
│  ❌ Failed: GitHub API rate limit hit (429)               │
│     The Engineer agent tried 3 times but GitHub kept      │
│     returning 429 Too Many Requests.                      │
│                                                          │
│  [Retry]  [View debug details]  [Cancel]                 │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

The human-readable error is translated from the raw exception in the frontend
using an error catalog. Unknown errors show the raw message with a "Report this"
link.

**Task failed — escalation required:**

```
┌─ Task #24 ────────────────────────────────────────────────┐
│                                                          │
│  ⛔ Escalated to COO — manual intervention needed         │
│                                                          │
│  The draft for "Acme Corp refund" was rejected 48h ago   │
│  and the approval window expired.                        │
│                                                          │
│  COO Agent's note: "Customer has follow-up asking about  │
│  status. Recommend drafting a new response manually."   │
│                                                          │
│  [Draft new response]  [Mark resolved]  [View thread]   │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Task cancellation:**

```
┌─ Task #27 ────────────────────────────────────────────────┐
│                                                          │
│  Are you sure you want to cancel this task?              │
│                                                          │
│  "Launch email for new feature" — CMO Agent · running    │
│                                                          │
│  [Keep running]            [Yes, cancel this task]       │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

On confirm: `PUT /tasks/{id}/cancel` → state transitions to `failed` with
`escalation_message: "Cancelled by user"`.

---

### 2.7.8 WebSocket Reconnect UX

The WebSocket client (`websocket.ts`) implements exponential backoff reconnect:

```
Disconnected from server.
Attempting to reconnect... (attempt 1/5)
Attempting to reconnect... (attempt 2/5)
Connected ✓ — syncing state...
```

While disconnected:
- The task list shows the last known state with a yellow banner:
  "⚠️ Live updates paused — your task state is up to date as of 3 min ago"
- No actions are blocked; the user can still interact with the dashboard
- On reconnect, the server sends a `sync` message with all active task states;
  the frontend reconciles with the Zustand store (last-write-wins on `updated_at`)

If all 5 reconnect attempts fail:
- Red banner: "⚠️ Could not reconnect. The server may have restarted."
- [Refresh page] button appears
- All tasks show their last known state with a "Last updated: X min ago" timestamp

---

### 2.7.9 Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Enter` | Submit current input (chat or task) |
| `Cmd/Ctrl + Enter` | Submit and ping the agent immediately |
| `A` | Open draft approval panel (when a draft is pending) |
| `Esc` | Close any open modal/panel |
| `Cmd/Ctrl + K` | Open skill launcher |
| `Cmd/Ctrl + /` | Show keyboard shortcut cheatsheet |
| `Tab` | Cycle through task cards in tracker |
| `R` | Retry selected failed task |
| `Cmd/Ctrl + M` | Toggle memory viewer |

---

---

## 3. Key Technical Decisions

### 3.1 Memory is the Core

The most important engineering investment is the memory system. SureThing's four memory
dimensions (project context, writing voice, execution history, skill patterns) compound over time —
the longer you use it, the more capable it becomes. This is what makes it feel like
"hiring an employee who already knows you."

The four layers (Section 2.2) are implemented as two separate stores:

| Layer | Store | Bounded? | Notes |
|---|---|---|---|
| Semantic Memory | ChromaDB | TTL 90d + LRU cap | Vector search |
| Episodic Memory | PGLite | 180d rolling window | SQL queries |
| Writing Style | PGLite | Explicit update only | Structured fields |
| Procedural (Skills) | PGLite | Versioned | YAML content |

The memory system should be the first thing you build and test rigorously.

### 3.2 The "Shared Brain" Pattern

Every agent in the team reads from and writes to the same memory store. No agent is
siloed. When the Engineer agent completes a GitHub task, the CMO agent can see the
outcome and build on it. This is the "zero silos" claim in the marketing.

Implementation:

```python
class SharedMemoryStore:
    """Every agent reads/writes through this interface. Single-user: no user_id needed."""

    def read(self, query: str, project_id: str | None = None,
             memory_types: list[str] = ["semantic", "episodic", "style"]) -> str:
        results = []
        if "semantic" in memory_types:
            results.append(self.vector_store.similarity_search(
                query, k=5,
                filter={"project_id": project_id} if project_id else {}
            ))
        if "episodic" in memory_types:
            results.append(self.db.query_task_history(project_id=project_id))
        if "style" in memory_types:
            results.append(self.db.get_writing_profile().format())
        return format_combined_context(results)

    def write(self, memory_type: str, content: dict, project_id: str | None = None):
        if memory_type == "semantic":
            self.vector_store.add_text(
                text=content["text"],
                metadata={"project_id": project_id, **content.get("metadata", {})}
            )
        elif memory_type == "episodic":
            self.db.insert_task_history(project_id=project_id, **content)
        elif memory_type == "style":
            self.db.get_writing_profile().update_style(content)
```

### 3.3 Skills as Prompt Templates with Tool Bindings

Skills are the procedural memory layer. A skill is a function that:
1. Accepts a task description and user context
2. Selects relevant memories
3. Renders a specialized system prompt
4. Binds to specific tools/APIs
5. Returns a draft or executes

```python
class Skill:
    def __init__(self, name, description, agent_role, steps, tools, memory_layers):
        self.name = name
        self.description = description
        self.agent_role = agent_role  # "cmo", "engineer", etc.
        self.steps = steps            # ordered execution steps
        self.tools = tools            # MCP tool bindings
        self.memory_layers = memory_layers

    def execute(self, task: str, project_id: str | None = None, context: dict = None) -> SkillResult:
        memories = shared_memory.read(task, project_id=project_id, memory_layers=self.memory_layers)
        system_prompt = self.render_prompt(task, memories, context)
        agent = agent_for_role(self.agent_role)
        result = agent.run(system_prompt, tools=self.tools)
        return result
```

---

## 3b. Security & Isolation

These concerns apply across all phases. They are not optional hardening — they are
required to safely operate an always-on agent system with integration credentials on a
personal machine.

### 3b.1 PyYAML Safe Loading (CRITICAL)

Skill definitions are stored as raw YAML in `Skill.yaml_content`. They are parsed at
registry load time and at skill invocation. **Never use `yaml.load()` without a SafeLoader.**

```python
import yaml

# DANGEROUS — FullLoader can instantiate arbitrary Python objects:
skill_def = yaml.load(skill_yaml_content)          # ← RCE vector

# SAFE — SafeLoader only constructs plain data structures:
skill_def = yaml.safe_load(skill_yaml_content)     # ← correct
```

A maliciously crafted skill YAML can run arbitrary shell commands via PyYAML object
deserialization:

```yaml
# Example of arbitrary code execution via FullLoader
name: bomb
yaml_content: |
  !!python/object/apply:os.system ["rm -rf /"]
```

This is a documented PyYAML hazard. `safe_load()` is the only acceptable loader for
skill YAML. Add this to the skill registry implementation before any other parsing logic.

---

### 3b.2 Agent-to-Integration Permission Scoping (CRITICAL)

All four agents share access to all integrations by default. This is a maximally
dangerous configuration: if any agent is prompt-injected or misrouted, it can access
any connected integration.

**Least-privilege model:** Each integration has an explicit `permissions` and
`allowed_agents` scope. The skill executor verifies both before invoking any tool.

Extend the `Integration` schema (Section 4.2) with two fields:

```
Integration
  ...
  permissions    TEXT[] NOT NULL DEFAULT '{}'
    -- e.g., ["read"] or ["read", "write"]; empty array = no access
  allowed_agents TEXT[] NOT NULL DEFAULT '{}'
    -- e.g., ["engineer"] or ["coo", "researcher"]; empty = block all
```

Extend each skill node's `tools` list with a manifest the executor validates:

```yaml
nodes:
  - id: verify
    agent: researcher
    goal: "Verify subscription status"
    tools: [stripe_api]          # validated against Integration.permissions
    allowed_agents: [researcher] # validated against Integration.allowed_agents
```

At execution time, before any tool call:

```python
async def execute_tool(tool_name: str, agent_role: str, integration_id: str):
    integration = db.get_integration(integration_id)
    if agent_role not in integration.allowed_agents:
        raise PermissionError(f"{agent_role} is not allowed to use {integration.app_name}")
    if tool_name not in integration.permissions:
        raise PermissionError(f"{tool_name} not permitted for {integration.app_name}")
    # ... proceed with tool call
```

Without this, an agent asked to "research competitor pricing" could theoretically
be redirected to call the Stripe refund tool if the task routing is compromised.

---

### 3b.3 Data at Rest Encryption (HIGH)

Section 4.3 covers **token encryption** (Fernet for OAuth tokens). This section covers
everything else.

**What is currently unencrypted:**

| Store | Contents | Risk |
|---|---|---|
| PGLite (`episodic_memory`) | Task history, project context, outcomes | High — full working patterns exposed |
| PGLite (`writing_profile`) | Tone, signature phrases, greeting style | Medium — personal communication patterns |
| ChromaDB (`semantic_memory`) | All embedded memory content | High — entire knowledge base exposed |
| `.env` | Fernet key, API keys | Critical — unlocks all tokens |

**Encryption status by phase:**

- **Phase 1–2:** Acknowledge the gap. OS-level file permissions (`chmod 600`) are the
  boundary. Do not run on shared hosting or multi-user machines.
- **Phase 3+ (full disk):** Use LUKS or `fscrypt` to encrypt the data directory.
  This is transparent to the application and covers all stores simultaneously.
- **Phase 3+ (selective):** ChromaDB has no built-in encryption. A transparent
  encryption layer in `SharedMemoryStore` can encrypt text before embedding and
  decrypt after retrieval, using the same Fernet key. PGLite supports SQLite
  encryption via SQLCipher (`PRAGMA key`), but this requires compiling a custom
  PGLite build or using `aiosqlite` with SQLCipher directly.

**Minimum for Phase 1:** `chmod 600` on the data directory and `.env`. Document this
as a setup prerequisite. Do not run as a shared OS user.

---

### 3b.4 Container and Network Isolation (HIGH)

The current architecture runs everything in a single process tree. If the agent runtime
is compromised (malicious skill, prompt injection chain leading to tool exfiltration),
there is no container boundary — the attacker has the same OS privileges as the user.

**Minimum container layout:**

```
┌─────────────────────────────────────────────────────┐
│  mindforge-network (Docker bridge, 172.20.0.0/16)   │
│                                                      │
│  ┌──────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │  app         │  │  temporal   │  │  chroma    │ │
│  │  (FastAPI)   │  │  (worker)   │  │  (server)  │ │
│  │  127.0.0.1:  │  │             │  │  172.20.x  │ │
│  │  8000        │  │             │  │            │ │
│  └──────────────┘  └─────────────┘  └───────────┘ │
│                                                      │
│  ┌──────────────┐                                   │
│  │  postgres    │  (for Temporal persistence)      │
│  │  172.20.x     │                                   │
│  └──────────────┘                                   │
└─────────────────────────────────────────────────────┘
```

**Key isolation rules:**
- App container runs as non-root user (`USER appuser`)
- ChromaDB and Postgres containers have read-only filesystem except for their data volumes
- App container can only reach explicit allowlisted external hosts (GitHub, Stripe, Gmail
  APIs) — no wildcard internet access
- Temporal worker has no direct network access; it signals the app via the database only
- WebSocket dashboard traffic stays on the Docker bridge; no port exposed to host by default

For local development (Phase 1), processes can run directly on the host. Document the
production container target explicitly so the Phase 3 migration path is clear.

---

### 3b.5 Skill Graph Validation at Load Time (MEDIUM)

The skill execution graph's edge conditions are plain string labels (not Python
expressions — correctly designed). However, a corrupted or malformed skill definition
can still bypass approval gates or create invalid execution paths.

**Validate every skill at registry load time:**

```python
import yaml

def validate_skill_graph(skill_def: dict) -> list[str]:
    """Returns list of validation errors; empty list means valid."""
    errors = []
    node_ids = {n["id"] for n in skill_def.get("nodes", [])}
    outgoing = {n["id"]: [] for n in skill_def.get("nodes", [])}

    # 1. Every edge references an existing node
    for edge in skill_def.get("edges", []):
        if edge["from"] not in node_ids:
            errors.append(f"Edge references missing node: {edge['from']}")
        if edge["to"] not in node_ids:
            errors.append(f"Edge references missing node: {edge['to']}")
        outgoing[edge["from"]].append(edge["condition"])

    # 2. Every node with requires_approval has at least one outgoing edge
    for node in skill_def.get("nodes", []):
        if node.get("requires_approval"):
            if not outgoing.get(node["id"]):
                errors.append(f"Node '{node['id']}' requires approval but has no outgoing edges")

    # 3. No node is its own ancestor (no cycles reachable from start)
    def has_path(from_id, visited):
        if from_id in visited:
            return True
        for edge in skill_def.get("edges", []):
            if edge["from"] == from_id:
                if has_path(edge["to"], visited | {from_id}):
                    errors.append(f"Cycle detected: {from_id} → ...")
                    return True
        return False
    has_path(skill_def["nodes"][0]["id"], set())  # errors collected in closure

    return errors
```

Run this in `SkillRegistry.load_skill()` before inserting into the registry. Reject
the skill and log an error if validation returns non-empty errors.

---

### 3b.6 Sensitive Field Scrubbing Before Logging (LOW)

All token fields are excluded from logging (Section 4.3). But `task.context` JSONB,
`SkillResult.draft_content`, and WebSocket messages to the dashboard can contain
other sensitive data: email subjects, client names, integration responses.

```python
SENSITIVE_KEYS = {
    "auth_token_enc", "refresh_token_enc", "access_token",
    "password", "secret", "api_key", "private_key", "token",
    "authorization", "cookie", "session",
}

def scrub(obj: dict) -> dict:
    """Recursively redact sensitive fields in a dict or list."""
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]" if k.lower() in SENSITIVE_KEYS
            else scrub(v) if isinstance(v, (dict, list))
            else v
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [scrub(i) for i in obj]
    return obj

# Usage:
logger.info("Task context", extra={"context": scrub(task.context)})
ws.send(json.dumps(scrub(draft_message)))
```

Apply `scrub()` to all log `extra` dicts and all WebSocket message payloads before
serialization. This is especially important for the observability / LangSmith trace
export path, which may transmit span attributes to a third-party service.

---

### 3b.8 Prompt Injection in Semantic Memory (CRITICAL)

#### Threat model

MindForge embeds content from external sources — parsed emails, scraped web pages,
calendar summaries, integration responses — into ChromaDB. At inference time, retrieved
memory chunks are injected directly into the LLM prompt via `memory_context` in
`build_supervisor_prompt()`.

An attacker who can place text into any of these input channels can inject instructions
that the agent acts on as if they came from the system prompt:

```
Email → email parser skill → embed → ChromaDB → retrieve() → prompt → LLM → action
Web scrape → scrape skill → embed → ChromaDB → retrieve() → prompt → LLM → action
```

This is the **semantic memory injection** attack surface. Unlike traditional prompt
injection (which targets a single prompt), memory injection persists — a single
malicious email embeds instructions that can be retrieved and followed across many
subsequent task executions.

#### Injection vectors

| Vector | How injection occurs | Attacker capability required |
|---|---|---|
| Email parsing | Malicious email contains hidden instruction in body/signature | Send an email to a connected inbox |
| Web scraping | Scraped page contains prompt-injection SEO content | Control a scraped domain or compromise it |
| Calendar summary | Event description or attendee list contains injected text | Have an event added to a connected calendar |
| Integration response | Third-party API response includes dynamic content with injected text | Compromise or manipulate a connected API |
| Project memory | A collaborator's message in a shared project channel injects text | Be part of an email thread or project |

#### Defense-in-depth strategy

Three layers of defense, each required. No single layer is sufficient.

**Layer 1 — Input classification at write time (`sanitize_for_memory`)**

Before embedding any text from an external integration, classify it. Text classified as
injection attempts is flagged, not rejected (to avoid data loss), but logged and
stored with a `flags: ["injection_suspect"]` metadata marker.

```python
# backend/memory/sanitizer.py
import re
from enum import Enum

class ContentSource(str, Enum):
    HUMAN = "human"           # direct user input — trust
    INTEGRATION = "integration"  # email, scrape, calendar — untrusted
    SKILL_OUTPUT = "skill_output"  # agent-generated — low trust

# Patterns that indicate potential instruction injection
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|orders?|rules?)", re.I),
    re.compile(r"(system|assistant)\s*:\s*", re.I),
    re.compile(r"disregard\s+(your|the)\s+(instructions?|rules?|constraints?)", re.I),
    re.compile(r"<\|system\|>", re.I),          # common LLM delimiter
    re.compile(r"<\|user\|>", re.I),
    re.compile(r"^\s*##?\s*System\s*Instructions?", re.I),
    re.compile(r"you\s+are\s+now\s+(a\s+)?(instructed\s+to\s+)?act\s+as", re.I),
    re.compile(r"(instead|rather)\s+than\s+(what|doing)", re.I),
    re.compile(r"forget\s+(everything|all)\s+(above|previous)", re.I),
    # Base64/octal obfuscation — common in evasion
    re.compile(r"^[A-Za-z0-9+/]{64,}={0,2}$"),  # long base64 strings
]

INJECTION_WEIGHT_PATTERNS = [
    (re.compile(r"(reminder|note|instruction):", re.I), 0.6),
    (re.compile(r"please\s+(also\s+)?(ignore|disregard)", re.I), 0.8),
    (re.compile(r"additional(ly)?\s+inst", re.I), 0.7),
]

def classify_injection_risk(text: str, source: ContentSource) -> tuple[bool, float, list[str]]:
    """
    Returns (is_suspect, risk_score, matched_patterns).
    risk_score 0.0 (safe) → 1.0 (clear injection).
    """
    if source == ContentSource.HUMAN:
        return False, 0.0, []   # trust direct user input

    matched = []
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            matched.append(pattern.pattern)

    risk = sum(
        weight
        for pattern, weight in INJECTION_WEIGHT_PATTERNS
        if pattern.search(text)
    )
    risk += 0.9 if matched else 0.0

    # Cap at 1.0
    risk = min(risk, 1.0)

    # Threshold: flag if risk > 0.6 OR any hard pattern matched
    is_suspect = risk > 0.6 or len(matched) > 0
    return is_suspect, risk, matched

def sanitize_for_memory(
    text: str,
    source: ContentSource,
    project_id: str,
) -> tuple[str, dict]:
    """
    Sanitize text before embedding.
    Returns (sanitized_text, metadata_dict).
    """
    is_suspect, risk, matched = classify_injection_risk(text, source)

    sanitized = text
    if is_suspect:
        # Remove detected instruction patterns but preserve the rest
        for pattern in INJECTION_PATTERNS:
            sanitized = pattern.sub("[instruction removed]", sanitized)
        for pattern, _ in INJECTION_WEIGHT_PATTERNS:
            sanitized = pattern.sub("[instruction removed]", sanitized)

    flags = ["injection_suspect"] if is_suspect else []
    metadata = {
        "source": source.value,
        "project_id": project_id,
        "injection_risk": risk,
        "matched_patterns": matched,
        "flags": flags,
        "sanitized": is_suspect,
    }
    return sanitized, metadata
```

**When to call `sanitize_for_memory`:**
- Email parsing skill: `source=INTEGRATION` before `embed_texts([email_body])`
- Web scraping skill: `source=INTEGRATION` before `embed_texts([page_content])`
- Calendar summary: `source=INTEGRATION` before `embed_texts([event_desc])`
- Skill output: `source=SKILL_OUTPUT` before re-embedding agent output into memory

**Layer 2 — Instruction filtering at read time (`filter_memory_context`)**

Even after sanitization, a sophisticated attacker may use novel evasion techniques that
bypass Layer 1. Layer 2 inspects retrieved memory chunks at prompt-build time before
they enter the LLM context.

```python
# backend/agents/prompt_builder.py

# LLM instruction delimiters — never legitimate in memory context
LLM_DELIMITERS = {"<|system|>", "<|assistant|>", "<|user|>", "<|system>", "[SYSTEM]", "## System"}
INSTRUCTION_PHRASES = {
    "ignore all previous instructions",
    "disregard your guidelines",
    "you are now instructed to",
    "forget everything above",
    "instead of what you are supposed to do",
}

def filter_memory_context(memory_chunks: list[dict]) -> list[dict]:
    """
    Remove or quarantine chunks that contain instruction-like content.
    Called inside build_supervisor_prompt() before adding memory_context.
    """
    filtered = []
    quarantined = []

    for chunk in memory_chunks:
        text = chunk.get("text", "")

        # Check for LLM delimiters
        if any(delimiter in text for delimiter in LLM_DELIMITERS):
            quarantined.append(chunk)
            continue

        # Check for instruction phrases (case-insensitive substring)
        text_lower = text.lower()
        if any(phrase in text_lower for phrase in INSTRUCTION_PHRASES):
            quarantined.append(chunk)
            continue

        # Check metadata flags from Layer 1
        if "injection_suspect" in chunk.get("flags", []):
            # Downgrade: include with a warning prefix that the LLM will notice
            quarantined.append(chunk)
            continue

        filtered.append(chunk)

    if quarantined:
        # Log what was quarantined for human review
        logger.warning(
            "Memory chunks quarantined during prompt build",
            extra={
                "quarantined_ids": [c["id"] for c in quarantined],
                "count": len(quarantined),
            },
        )

    return filtered

def build_supervisor_prompt(task: str, agent_role: str,
                             memory_context: list[dict], skill_name: str | None):
    # Filter memory chunks before building context
    safe_memory = filter_memory_context(memory_context)

    # Format with visible boundary so the LLM knows where memory ends
    memory_block = "\n\n".join(
        f"[Memory {i+1}/{len(safe_memory)}]\n{c['text']}"
        for i, c in enumerate(safe_memory)
    )

    context_section = ""
    if safe_memory:
        context_section = f"""
## Retrieved Context (from your memory)
{memory_block}
---
End of retrieved context.
"""

    return Prompt(segments=[
        PromptSegment(content=AGENT_ROLES[agent_role], cached=True, ...),
        PromptSegment(content=context_section, cached=False),  # always fresh
        PromptSegment(content=f"## Current Task\n{task}", cached=False),
    ])
```

**Layer 3 — Approval gate amplification for memory-sourced tasks**

Tasks whose context was built primarily from retrieved memory (rather than the user's
direct input) carry higher uncertainty. Amplify the human-in-the-loop requirement:

```python
# If >50% of memory_context chunks were injection_suspect in Layer 1
# OR if the task involves a high-stakes integration (stripe, email send, GitHub push)
# → force draft-first with explicit user acknowledgment before execution

def should_force_draft_approval(task: Task, memory_chunks: list[dict]) -> bool:
    high_stakes_integrations = {"stripe", "send_email", "github_push", "slack_post"}

    suspect_ratio = sum(
        1 for c in memory_chunks if "injection_suspect" in c.get("flags", [])
    ) / max(len(memory_chunks), 1)

    uses_high_stakes = bool(
        memory_chunks and
        any(tool in high_stakes_integrations
            for c in memory_chunks
            for tool in c.get("tools_used", []))
    )

    return suspect_ratio > 0.5 or uses_high_stakes
```

#### Summary of changes required

| Where | Change | Layer |
|---|---|---|
| `backend/memory/sanitizer.py` | New file — `classify_injection_risk`, `sanitize_for_memory` | 1 — write time |
| Email parsing skill | Call `sanitize_for_memory` before embed | 1 |
| Web scraping skill | Call `sanitize_for_memory` before embed | 1 |
| `backend/agents/prompt_builder.py` | New `filter_memory_context`, update `build_supervisor_prompt` | 2 — read time |
| Skill execution gate | New `should_force_draft_approval` | 3 — action time |

#### What this does NOT cover

- Injection in direct user messages (the user is trusted; this is out of scope)
- Injection in skill YAML (covered by `yaml.safe_load()` + pydantic_yaml in Section 3b.1)
- Injection in integration tool responses at execution time (mitigated by `allowed_agents`/`permissions` scoping in Section 3b.2)
- A sufficiently sophisticated attacker who uses novel phrasing that evades all pattern matches (this is an unsolved problem in the field; the three layers reduce but cannot eliminate this risk)

---

### 3b.7 Fernet Key Rotation Procedure (LOW)

The Fernet key in `.env` is the DEK for all integration tokens. If the key is leaked
or you suspect compromise, rotate it as follows:

```bash
# 1. Generate new key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Put the new key in .env as ENCRYPTION_KEY_V2

# 3. Re-encrypt all tokens (one-time script)
python << 'EOF'
from cryptography.fernet import Fernet
import json

new_key = os.environ["ENCRYPTION_KEY_V2"]
old_key = os.environ["ENCRYPTION_KEY"]  # current key still valid

fernet_old = Fernet(old_key)
fernet_new = Fernet(new_key)

# Read all Integration records
records = db.query("SELECT id, auth_token_enc FROM integrations")
for rec in records:
    decrypted = fernet_old.decrypt(rec["auth_token_enc"])
    re_encrypted = fernet_new.encrypt(decrypted)
    db.execute(
        "UPDATE integrations SET auth_token_enc=%s, token_key_id='v2' WHERE id=%s",
        (re_encrypted, rec["id"])
    )
EOF

# 4. Remove old key from .env
# 5. Set ENCRYPTION_KEY=ENCRYPTION_KEY_V2 value
```

The old key is needed only during the rotation window. After all tokens are migrated,
remove it from `.env`.

---

### 3b.8 Memory Write Path — Semantic Injection Defense (MEDIUM)

Agents write to semantic and episodic memory via `SharedMemoryStore.write()`.
An agent whose output is influenced by an adversarial prompt can inject false
information into future context retrievals. For example:

```
Task A: "Summarize our contract with Acme Corp"
  → Agent writes episodic: {"summary": "Client prefers bitcoin payments"}
  → Later task retrieves this as grounding context
  → Downstream agent acts on false information
```

**Mitigations:**

1. **Sign episodic writes** with an HMAC of the source task ID + agent role + content.
   On retrieval, verify the HMAC before using the entry as grounding context.
   Entries with failed HMAC verification are flagged, not silently used.

2. **Content filtering on semantic writes:** Before inserting into ChromaDB,
   run the text through a prompt injection detector (simple regex pass for known
   injection patterns like "ignore previous instructions", "system prompt", etc.).
   Flag and exclude suspicious content rather than storing it.

3. **Epidemic memory retention window** already limits exposure (180-day rolling).
   Combined with HMAC signing, this makes targeted long-term memory poisoning
   impractical.

```python
import hmac, hashlib, re

INJECTION_PATTERNS = [
    r"ignore (all )?previous (instructions?|context)",
    r"(system|prompt|you are now)[:]",
    r"disregard (your|all) (instructions?|rules)",
]

async def write_semantic(self, text: str, project_id: str | None = None,
                         task_id: str | None = None, agent_role: str | None = None):
    # Reject injection patterns
    text_lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            logger.warning(f"Rejected suspicious semantic write: {pattern}")
            return  # do not store

    # Store with HMAC for integrity verification at read time
    hmac_key = f"{task_id}:{agent_role}".encode() if task_id else b"no-source"
    signature = hmac.new(self._hmac_key, text.encode(), "sha256").hexdigest()

    self.vector_store.add_text(
        text=text,
        metadata={"project_id": project_id, "hmac": signature,
                  "task_id": task_id, "agent_role": agent_role}
    )

def read_semantic(...) -> list[MemoryResult]:
    results = self.vector_store.similarity_search(...)
    verified = []
    for r in results:
        sig = r.metadata.get("hmac", "")
        computed = hmac.new(self._hmac_key, r.text.encode(), "sha256").hexdigest()
        if not hmac.compare_digest(sig, computed):
            logger.warning(f"HMAC mismatch on semantic memory {r.id}, excluding from context")
            continue  # exclude tampered entry
        verified.append(r)
    return verified
```

---

## 4. Data Model

### 4.1 Task State Machine

```
                    ┌─────────────┐
                    │   pending   │  (task created, not started)
                    └──────┬──────┘
                           │ supervisor begins execution
                           ▼
                    ┌─────────────┐
                    │   running   │  (agent actively working)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
       ┌──────────┐  ┌──────────┐  ┌──────────┐
       │  draft   │  │ executing │  │  failed  │  (unrecoverable)
       │          │  │           │  └──────────┘
       └────┬─────┘  └─────┬────┘
            │              │
      approve/reject  complete
            │              │
            ▼              ▼
     ┌────────────┐  ┌──────────┐
     │ executing  │  │completed │
     └─────┬──────┘  └──────────┘
           │
    execute fails
           │
           ▼
     ┌──────────┐
     │  failed  │  (recoverable — COO notified, can retry)
     └──────────┘
```

Valid transitions:
- `pending → running` (always)
- `running → draft` (skill node requires approval)
- `running → executing` (skill node, no approval required)
- `running → failed` (unrecoverable error)
- `draft → executing` (approved)
- `draft → failed` (rejected, routed to COO)
- `draft → failed` (timeout, escalated)
- `executing → completed` (success)
- `executing → failed` (recoverable error, COO notified)
- `failed → running` (COO retries)

**Task.status values:** `pending | running | draft | approved | executing | completed | failed`

---

### 4.2 Entity Schemas

```python
# Single-user configuration — no User table.
# All records are global to this installation.
# The OS user account is the security boundary.

WritingProfile       # see below
Task                 # see below
TaskStep             # see below
Integration          # see below
Skill                # see below
SemanticMemory       # ChromaDB collection — see below
EpisodicMemory       # see below
```

WritingProfile (singleton — one per installation)
  id              UUID (primary key)
  tone            TEXT  -- "formal" | "semi-formal" | "casual" | "friendly"
  sentence_length TEXT  -- "short" | "medium" | "long"
  first_person    TEXT  -- "I" | "we" | "they" | "mixed"
  signature_phrases TEXT[]  -- ["let's move forward", "happy to help"]
  greeting_style  TEXT
  signoff_style   TEXT
  updated_at      TIMESTAMP NOT NULL DEFAULT NOW()

Task
  id              UUID (primary key)
  skill_id        UUID (FK → Skill, NULLABLE)
  skill_version   INTEGER NOT NULL DEFAULT 1  -- pinned at invocation time

  status          TEXT NOT NULL  -- see state machine above
  task_type       TEXT NOT NULL  -- from classify_task_type()
  project_id      TEXT NULLABLE  -- scopes memory; set by COO on first invocation

  description     TEXT NOT NULL  -- original user input
  context         JSONB NOT NULL DEFAULT '{}'  -- structured runtime state
    /*
     * context schema:
     * {
     *   "nodes_completed": ["verify"],
     *   "current_node": "draft",
     *   "draft_content": { "subject": "...", "body": "..." },
     *   "constraint": "replacement",  -- from clarification response
     *   "error": null,
     *   "escalation_message": null,
     *   "approval_deadline_iso": "..."
     * }
     */

  created_at      TIMESTAMP NOT NULL DEFAULT NOW()
  updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
  completed_at    TIMESTAMP NULLABLE

  steps           TaskStep[] (one-to-many)

TaskStep
  id              UUID (primary key)
  task_id         UUID (FK → Task)
  node_id         TEXT NOT NULL  -- matches skill execution_graph node id
  agent_role      TEXT NOT NULL  -- "researcher" | "cmo" | "engineer" | "coo"
  step_order      INTEGER NOT NULL

  status          TEXT NOT NULL  -- "pending" | "running" | "completed" | "failed"
  action_taken    JSONB NULLABLE
  result          JSONB NULLABLE
  approval_required BOOLEAN NOT NULL DEFAULT FALSE
  approval_status TEXT NULLABLE  -- "pending" | "approved" | "rejected" | "timeout"
  approval_edited_content JSONB NULLABLE
  approved_at     TIMESTAMP NULLABLE

  error           TEXT NULLABLE
  retry_count     INTEGER NOT NULL DEFAULT 0

Integration
  id              UUID (primary key)
  app_name        TEXT NOT NULL  -- "gmail", "github", "stripe", etc.
  auth_token_enc  TEXT NOT NULL  -- AES-256-GCM encrypted, base64-encoded
  refresh_token_enc TEXT NULLABLE -- AES-256-GCM encrypted, base64-encoded
  token_key_id    TEXT NOT NULL  -- "local" for self-hosted
  status          TEXT NOT NULL  -- "active" | "revoked" | "error" | "expired"
  last_sync_at    TIMESTAMP NULLABLE
  created_at      TIMESTAMP NOT NULL DEFAULT NOW()
  updated_at      TIMESTAMP NOT NULL DEFAULT NOW()

  -- Per-integration credentials:
  extra           JSONB NULLABLE  -- e.g., { "team_id": "...", "instance_url": "..." }

  -- Least-privilege scoping (see Section 3b.2):
  permissions     TEXT[] NOT NULL DEFAULT '{}'
    -- e.g., ["read"] or ["read", "write"]; empty array = no access
  allowed_agents  TEXT[] NOT NULL DEFAULT '{}'
    -- e.g., ["engineer"] or ["coo", "researcher"]; empty = block all

Skill
  id              UUID (primary key)
  name            TEXT UNIQUE NOT NULL
  description     TEXT NOT NULL
  category        TEXT NOT NULL
  agent_role      TEXT NOT NULL

  yaml_content    TEXT NOT NULL  -- raw YAML, versioned
  version         INTEGER NOT NULL DEFAULT 1
  tools           JSONB NOT NULL  -- ["stripe_api", "email_fetch", ...]
  memory_layers   TEXT[] NOT NULL
  trigger_type    TEXT NOT NULL  -- "keyword" | "intent_classifier" | "explicit_only"
  trigger_keywords TEXT[] NULLABLE
  trigger_intents  TEXT[] NULLABLE

  success_count   INTEGER NOT NULL DEFAULT 0
  failure_count   INTEGER NOT NULL DEFAULT 0
  last_run_at     TIMESTAMP NULLABLE

  created_at      TIMESTAMP NOT NULL DEFAULT NOW()
  updated_at      TIMESTAMP NOT NULL DEFAULT NOW()

SemanticMemory  ← ChromaDB, NOT PGLite
  collection: "semantic_memory"
  schema:
    id: TEXT (UUID, primary key)
    project_id: TEXT NULLABLE (indexed)
    text: TEXT
    embedding: FLOAT[1536]  -- text-embedding-3-small; 1536 dims
    metadata: JSONB  -- arbitrary extra context
    created_at: TIMESTAMP

  ⚠️ SemanticMemory lives in ChromaDB. It does NOT have a PGLite table.
  PGLite stores ONLY: EpisodicMemory, WritingProfile, Skill, Integration, Task, TaskStep.

EpisodicMemory
  id              UUID (primary key)
  project_id      TEXT NULLABLE
  task_id         UUID (FK → Task)
  task_type       TEXT NOT NULL
  agent_role      TEXT NOT NULL
  summary         TEXT NOT NULL
  outcome_status  TEXT NOT NULL  -- "completed" | "failed" | "escalated"
  feedback        TEXT NULLABLE  -- user feedback if any
  created_at      TIMESTAMP NOT NULL DEFAULT NOW()

  -- retention: 180-day rolling window; delete where created_at < NOW() - 180 days

UserPreference (singleton — one per installation)
  id              UUID (primary key)

  proactive_monitoring_enabled  BOOLEAN NOT NULL DEFAULT TRUE
  email_check_interval_minutes   INTEGER NOT NULL DEFAULT 30
  calendar_check_interval_minutes INTEGER NOT NULL DEFAULT 60
  billing_alert_threshold_usd    INTEGER NOT NULL DEFAULT 50

  notification_channel  TEXT NOT NULL DEFAULT 'dashboard'
    -- "dashboard" | "email" | "slack" | "discord"
  notification_handle   TEXT NULLABLE  -- slack handle, discord ID, email addr

  created_at      TIMESTAMP NOT NULL DEFAULT NOW()
  updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
```

### 4.3 Auth Token Key Management

Auth tokens for integrations are encrypted at rest using AES-256-GCM.

**Phase 1–2 (self-hosted prototype):** Use `cryptography.fernet.Fernet` with a key stored in
`.env`. Generate a key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the output as `ENCRYPTION_KEY` in `.env`. No external KMS required. The `token_key_id`
column is still included for forward-compatibility but is set to `"local"` in these phases.

**Phase 4:** The Fernet key in `.env` remains sufficient. If you want key rotation
without re-encrypting everything, generate a new key, re-encrypt secrets, and update
`token_key_id` to `"v2"`. AWS KMS / HashiCorp Vault is only needed for multi-user deployments.

**Shared requirements (all phases):**
- **DEK (Data Encryption Key):** Per-integration, randomly generated 32-byte key
- **Token refresh:** Background job detects expired tokens via API error, triggers re-OAuth
- **Never logged:** All token fields are excluded from application logging

---

## 5. Implementation Phases

> **Who is building this?** Single developer for Phase 1–3. Solo scope is reflected in
> task counts. Phase 4 (scale) requires at minimum 2 people.

### 5.1 Phase 1 — Core Loop (3–4 weeks solo)

**Goal:** Single-agent demo, in-memory everything, no background tasks

- [ ] FastAPI server on `127.0.0.1:8000`, no auth, REST endpoints + WebSocket
- [ ] PGLite database: WritingProfile, Task, TaskStep, UserPreference only (no User table)
- [ ] ChromaDB: SemanticMemory collection, `project_id` scoped
- [ ] SharedMemoryStore with `classify_task_type()` keyword rules
- [ ] Writing style profile: manual entry form (no LLM extraction yet)
- [ ] React dashboard: chat UI + task list + draft approval cards
- [ ] OpenRouter integration with circuit breaker (gpt-4o → claude-3.5 → gemini-2)
- [ ] LangGraph single-agent (no multi-agent yet): supervisor routes by keyword
- [ ] Memory injection at task start; write-out on task complete
- [ ] **Email: IMAP/SMTP only (no OAuth)** — avoids OAuth complexity for Phase 1
- [ ] GitHub API key (personal token, not OAuth) for Phase 1
- [ ] Linear API key for Phase 1
- [ ] Stripe: read-only mode (dashboard shows revenue, no writes)

**Test scenario:** "Summarize my GitHub commits from the last 24 hours."

**Exit criteria:** Task enters system → agent retrieves relevant memories → produces
output → output stored in episodic memory. Dashboard reflects correct task status.
Agent can be restarted mid-task and resume (checkpointer verified).

---

### 5.2 Phase 2 — Multi-Agent + Skills (3–4 weeks solo)

**Goal:** Multi-agent team with role specialization, skills framework, WebSocket

- [ ] LangGraph supervisor orchestrator with 4 agent roles: COO, CMO, Researcher, Engineer
- [ ] Shared memory store accessible by all agents (write queue implemented)
- [ ] Skill execution graph engine: branching, retry, approval gates
- [ ] Skills: GitHub Daily Summary (YAML), Subscription Refund Negotiator (DAG)
- [ ] Draft-first workflow: task enters "draft" state, pauses, awaits approval
- [ ] WebSocket/SSE: agent pings dashboard on draft ready, dashboard pushes approval back
- [ ] Clarification protocol: supervisor surfaces ambiguity to user before executing
- [ ] `trigger_skill()`: keyword → explicit → intent classifier fallback chain
- [ ] Skill registry: load YAML, version pin at invocation, archive old versions
- [ ] Writing style learning: LLM extraction from approved drafts, update WritingProfile

**Test scenario:** "I need to launch a new feature. Research competitor pricing,
write a launch email in my voice, create the GitHub issue."

**Exit criteria:** Multi-agent task routes to correct specialist. Draft-first pauses
and resumes on approval. Skill with branching (verify → draft → negotiate) completes
end-to-end. Skill version pinning verified: update skill mid-execution, running
execution completes with old version.

---

### 5.3 Phase 3 — Proactive Execution (2–3 weeks)

**Goal:** 24/7 monitoring, background tasks, Temporal (not Celery)

- [ ] Temporal workflow for proactive monitoring tasks (replaces Celery)
- [ ] Email inbox monitoring: periodic fetch via IMAP, urgency classification
- [ ] Unreplied email follow-up detection: thread-level tracking in PGLite
- [ ] Calendar conflict detection (Google Calendar API, OAuth required)
- [ ] Billing anomaly detection (Stripe webhook handler + HMAC verification)
- [ ] Dashboard notification system: in-app + optional email/slack
- [ ] Full Subscription Refund skill: multi-round, timeout escalation, COO notified
- [ ] Rate limiter: per-integration (prevents 403s from concurrent API calls)
- [ ] OAuth flows: Gmail, Google Calendar, GitHub (personal token → OAuth transition)
- [ ] Observability: LangSmith or OpenTelemetry tracing for agent decision traces
- [ ] Skill editor UI: YAML code editor with syntax highlighting, preview parsed DAG,
  validation on save (Phase 3 — needed before Phase 4 skill marketplace can test installs)

**Test scenario:** Agent detects unreplied email from 3 days ago, drafts follow-up,
user approves, follow-up sent, episodic memory updated.

**Exit criteria:** Background task runs without manual trigger. Webhook delivers Stripe
event → agent processes → action taken. Temporal handles task failure with retry and DLQ.

---

### 5.4 Phase 4 — Composio + 24/7 Production

**Goal:** Full integration library, robust long-running workflows, no manual intervention

> Phase 4 is the single-user equivalent of "shipping v1" — all integrations wired,
> Temporal self-hosted cluster running, system stable enough to leave running 24/7.

Quarter 1 scope:
- [ ] Composio Cloud: connect all major integrations (Gmail, Slack, GitHub, Linear, Stripe, HubSpot, Salesforce)
- [ ] Temporal self-hosted cluster: 3-worker cluster with PostgreSQL persistence
- [ ] 24/7 email monitoring: IMAP watcher with urgency classification
- [ ] Unreplied email follow-up: thread-level tracking, auto-draft on 3-day silence
- [ ] Stripe webhook handler: billing anomaly detection, HMAC verified
- [ ] Calendar conflict detection: Google Calendar OAuth (if needed)
- [ ] Dashboard polish: notification history, task audit log, memory viewer
- [ ] Skill editor UI: YAML editor with DAG preview, installed skills management

**Exit criteria:** Agent runs for 7 days without manual restart. Webhook events processed within 5s. Draft-first workflow completes end-to-end on 5 different skill types.

---

## 5.5 Cross-Cutting Concerns

These apply across all phases — not phase-specific.

### 5.5.1 LLM Failure Handling

Every LLM call must have a defined failure policy. Do not let the agent hang on timeout.

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

LLM_RETRY_CONFIG = {
    "max_attempts": 3,
    "backoff_factor": 2,  # 2s, 4s, 8s
    "jitter": True,
}

FALLBACK_CHAIN = ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "google/gemini-2.0-flash"]

async def llm_call(prompt: str, model: str = FALLBACK_CHAIN[0]) -> str:
    for attempt, model in enumerate(FALLBACK_CHAIN):
        try:
            response = await openrouter.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                timeout=30,
            )
            return response.choices[0].message.content
        except (TimeoutError, RateLimitError) as e:
            if attempt == len(FALLBACK_CHAIN) - 1:
                raise LLMExhaustedError(f"All models failed: {e}") from e
            continue
        except Exception as e:
            # Unknown error — do not retry blindly
            raise LLMError(f"Unexpected error with {model}: {e}") from e
```

Circuit breaker per model: if the system hits 5 consecutive failures with one model,
circuit-break that model for 5 minutes before retrying.

### 5.5.2 Rate Limiting (per-integration)

Concurrent API calls to GitHub, Stripe, Linear, etc. cause 403s. Enforce a semaphore per
integration:

```python
from asyncio import Semaphore

INTEGRATION_RATE_LIMITS = {
    "github": Semaphore(5),    # max 5 concurrent GitHub API calls
    "stripe": Semaphore(2),
    "gmail": Semaphore(10),
    "linear": Semaphore(5),
    "_default": Semaphore(20),
}

async def integration_call(integration: str, fn, *args, **kwargs):
    sem = INTEGRATION_RATE_LIMITS.get(integration, INTEGRATION_RATE_LIMITS["_default"])
    async with sem:
        return await fn(*args, **kwargs)
```

> ⚠️ **Multi-worker note:** `asyncio.Semaphore` lives in process memory. If the API server
> runs with multiple workers (e.g., `gunicorn -w 4`), each worker has an independent semaphore
> count — rate limiting is per-worker, not per-user. For single-instance dev this is fine.
> For multi-worker production, replace with a Redis-backed rate limiter (e.g., `limits` library
> or a Lua script on Redis) so all workers share a single counter state.

### 5.5.3 OpenRouter Hard Rate Limit

Integration rate limits (Semaphore) prevent concurrent API overload. A **hard budget cap**
prevents a runaway loop from burning through the monthly OpenRouter budget in minutes.
The `CostTracker` (Section 5.7.10) estimates spend but does not enforce limits.

**Add to `backend/billing/budget.py`:**

```python
from datetime import datetime, timedelta
from collections import deque
import threading

class OpenRouterBudgetGuard:
    """
    Hard rate limit for OpenRouter API calls and token usage.
    Prevents runaway loops from exhausting the monthly budget.
    """

    def _default_limits() -> dict:
        return {
            # Hard caps — cannot be exceeded by any code path
            "max_calls_per_minute": 30,
            "max_calls_per_day": 500,
            "max_tokens_per_day": 2_000_000,  # ~$0.40 at gemini-2-flash
            # Alert thresholds — warn before hitting hard caps
            "calls_per_day_warning": 300,   # 60% of daily cap
            "tokens_per_day_warning": 1_500_000,  # 75% of daily token cap
        }

    def __init__(self, limits: dict | None = None):
        self.limits = limits or self._default_limits()
        self._calls_minute: deque = deque()   # timestamps of recent calls
        self._calls_day: deque = deque()       # timestamps of today's calls
        self._tokens_day: int = 0
        self._lock = threading.Lock()
        self._reset_day_if_needed()

    def _reset_day_if_needed(self):
        now = datetime.utcnow()
        if self._calls_day and self._calls_day[0].date() < now.date():
            self._calls_day.clear()
            self._tokens_day = 0

    def _clean_minute_window(self):
        cutoff = datetime.utcnow() - timedelta(minutes=1)
        while self._calls_minute and self._calls_minute[0] < cutoff:
            self._calls_minute.popleft()

    def check(self, tokens_estimate: int = 0) -> tuple[bool, str]:
        """
        Returns (allowed, reason). Raises BudgetExceeded if hard cap hit.
        Call before every LLM call and after every response to count tokens.
        """
        now = datetime.utcnow()
        with self._lock:
            self._clean_minute_window()
            self._reset_day_if_needed()

            # 1. Per-minute call rate
            if len(self._calls_minute) >= self.limits["max_calls_per_minute"]:
                return False, (
                    f"Per-minute rate limit hit ({len(self._calls_minute)}/"
                    f"{self.limits['max_calls_per_minute']} calls in last minute). "
                    "Wait before retrying."
                )

            # 2. Per-day call count
            if len(self._calls_day) >= self.limits["max_calls_per_day"]:
                return False, (
                    f"Daily call limit reached ({self.limits['max_calls_per_day']}). "
                    f"Resets at midnight UTC."
                )

            # 3. Per-day token budget
            if tokens_estimate > 0:
                if self._tokens_day + tokens_estimate > self.limits["max_tokens_per_day"]:
                    return False, (
                        f"Daily token budget exceeded "
                        f"(~{self._tokens_day + tokens_estimate:,} / "
                        f"{self.limits['max_tokens_per_day']:,}). "
                        "Wait until midnight UTC or reduce context size."
                    )

            return True, "allowed"

    def record(self, tokens_used: int = 0):
        """Call after a successful LLM response to count usage."""
        now = datetime.utcnow()
        with self._lock:
            self._calls_minute.append(now)
            self._calls_day.append(now)
            self._tokens_day += tokens_used

    @property
    def usage_today(self) -> dict:
        with self._lock:
            self._reset_day_if_needed()
            return {
                "calls_today": len(self._calls_day),
                "tokens_today": self._tokens_day,
                "calls_remaining": self.limits["max_calls_per_day"] - len(self._calls_day),
                "tokens_remaining": max(0, self.limits["max_tokens_per_day"] - self._tokens_day),
            }
```

**Usage in LLM call path:**

```python
# backend/agents/llm_router.py
BUDGET_GUARD = OpenRouterBudgetGuard()

async def call_llm(model: str, messages: list[dict], tokens_estimate: int) -> dict:
    allowed, reason = BUDGET_GUARD.check(tokens_estimate=tokens_estimate)
    if not allowed:
        raise BudgetExceeded(f"OpenRouter rate limit: {reason}")

    response = await openrouter.chat.completions.create(
        model=model, messages=messages, ...
    )
    tokens_used = response.usage.total_tokens
    BUDGET_GUARD.record(tokens_used=tokens_used)
    return response
```

**Alert on warning thresholds:**

```python
# In the health endpoint, check usage and warn if approaching limits
usage = BUDGET_GUARD.usage_today
if usage["calls_remaining"] < 50 or usage["tokens_remaining"] < 300_000:
    logger.warning("Approaching OpenRouter budget cap", extra=usage)
    # WebSocket → dashboard: show budget warning banner
```

**Environment variable overrides:**

```bash
# .env — override hard caps (in case of emergency or testing)
OPENROUTER_MAX_CALLS_PER_DAY=1000    # raise/lower daily call cap
OPENROUTER_MAX_TOKENS_PER_DAY=5000000  # raise for GPU-heavy usage
```

---

### Stripe Webhook Security

```python
import hmac
import hashlib

async def validate_stripe_webhook(payload: bytes, signature: str, secret: str) -> bool:
    """Validate Stripe webhook signature (HMAC-SHA256)."""
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

# In the webhook handler:
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not validate_stripe_webhook(payload, sig, settings.stripe_webhook_secret):
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Parse and process event — but do NOT process synchronously
    # Queue for Temporal workflow:
    await temporal.signal("stripe_event", event_id=event["id"], payload=event)
    return {"received": True}
```

> **Webhook retry queue:** If the Temporal worker is down when a Stripe event fires, the
> event is lost. Mitigation: Stripe dashboard settings → "Retry failed webhook deliveries"
> with exponential backoff (up to 7 days). This is configured in the Stripe dashboard,
> not in code.

### Observability

Every agent decision generates a trace:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer("mindforge")

@tracer.start_as_current_span("supervisor.route")
async def supervisor_route(task: str, state: AgentState):
    span = trace.get_current_span()
    span.set_attribute("task_type", classify_task_type(task))
    # ... routing logic
    span.set_attribute("selected_agent", result)
All spans include: `task_id`, `agent_role`, `skill_id`, `skill_version`.

Spans are exported to LangSmith (for LangGraph integration) or Jaeger (self-hosted).
All spans include: `task_id`, `agent_role`, `skill_id`, `skill_version`.

---

## 5.6 Testing Strategy

This section applies across all phases. Testing is not a Phase 4 concern — it must be
built in from the first line of code. A system that autonomously executes actions on
your behalf, with always-on background workflows and integration credentials, requires
more rigorous testing than a typical web app.

### 5.6.1 Test Directory Structure

```
mindforge-local/
├── backend/
│   ├── main.py
│   ├── agents/
│   ├── memory/
│   ├── skills/
│   ├── integrations/
│   ├── scheduler/
│   ├── db/
│   └── tests/                          # ← new
│       ├── unit/                       # pure functions, no I/O
│       │   ├── test_classify_task_type.py
│       │   ├── test_shared_memory_store.py
│       │   ├── test_skill_registry.py
│       │   ├── test_skill_graph_validation.py
│       │   ├── test_fernet_round_trip.py
│       │   ├── test_hmac_tamper_detection.py
│       │   ├── test_safe_yaml_loading.py
│       │   ├── test_scrub_sensitive_fields.py
│       │   └── test_circuit_breaker.py
│       ├── integration/                # real I/O, real stores
│       │   ├── test_task_lifecycle.py
│       │   ├── test_draft_approval_flow.py
│       │   ├── test_websocket_messages.py
│       │   ├── test_skill_execution_dag.py
│       │   ├── test_proactive_monitoring.py
│       │   ├── test_chroma_semantic_memory.py
│       │   ├── test_pglite_episodic_memory.py
│       │   └── test_integration_clients/
│       │       ├── test_github_client.py
│       │       ├── test_stripe_webhook_hmac.py
│       │       └── test_email_fetch.py
│       ├── e2e/                       # full-stack, browser
│       │   ├── test_task_submission_flow.py
│       │   ├── test_draft_approval_ui.py
│       │   ├── test_memory_viewer.py
│       │   └── test_websocket_reconnect.py
│       ├── fixtures/                  # shared test data
│       │   ├── skills/                # YAML skill definitions for tests
│       │   │   ├── valid-github-daily-summary.yaml
│       │   │   ├── valid-subscription-refund.yaml
│       │   │   └── invalid-cycle-skill.yaml
│       │   ├── memory/                # replay fixtures
│       │   ├── tasks/                 # synthetic task histories
│       │   └── integrations/           # masked test credentials
│       ├── conftest.py                # pytest config, fixtures, plugins
│       └── pyproject.toml             # pytest settings, coverage config
├── frontend/
│   └── src/
│       └── tests/                     # ← new
│           ├── unit/                  # React component tests
│           │   ├── TaskTracker.test.tsx
│           │   ├── DraftReview.test.tsx
│           │   ├── ClarificationModal.test.tsx
│           │   └── SkillEditor.test.tsx
│           ├── integration/           # API mocking with MSW
│           │   └── test_task_api.ts
│           └── e2e/                   # Playwright
│               └── test_dashboard.ts
└── compose.yaml                          # test isolation containers
```

**Test isolation rule:** Unit tests never touch the network, a real database, or a real
LLM. Integration tests may use real stores (ChromaDB, PGLite) via Docker Compose in
the `test` profile. E2E tests use the full stack with services in `docker compose up`.

---

### 5.6.2 Python Test Stack

| Tool | Purpose |
|---|---|
| `pytest` | Test runner, fixture discovery |
| `pytest-asyncio` | Async test support for FastAPI + Temporal |
| `pytest-cov` | Coverage reporting; gate at 70% line cover for unit, 50% integration |
| `dirty-equals` | Readable assertion assertions: `assert resp.json() == {"status": "ok", dirty_equals.Ignore()} |
| `hypothesis` | Property-based testing (e.g., generate 100 random project_ids, verify scoping) |
| `pytest-mock` | Spy and mock objects for unit isolation |
| `respx` | Route HTTPX-based clients (used by ChromaDB client, HTTPX in tests) |
| `freezegun` | Freeze time for TTL/eviction tests without real clock waiting |
| `tmp_path` | pytest built-in for isolated temp storage per test |

**`conftest.py` shared fixtures:**

```python
# backend/tests/conftest.py
import pytest, asyncio
from pathlib import Path

@pytest.fixture(scope="session")
def event_loop():
    # one event loop per test session for async tests
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def pglite_test_db(tmp_path):
    """Isolated PGLite DB for each test."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    init_schema(conn)   # runs schema.sql in-memory
    yield conn
    conn.close()

@pytest.fixture
def chroma_tmp_dir(tmp_path):
    """Isolated ChromaDB dir for each test."""
    d = tmp_path / "chroma"
    d.mkdir()
    return str(d)

@pytest.fixture
def mock_openrouter():
    """Pretend OpenRouter that returns fixed responses for routing tests."""
    with patch("openrouter.chat.completions.create") as mock:
        mock.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="engineer"))]
        )
        yield mock

@pytest.fixture
def skill_yaml_valid():
    return Path("backend/tests/fixtures/skills/valid-subscription-refund.yaml").read_text()

@pytest.fixture
def skill_yaml_with_cycle():
    return Path("backend/tests/fixtures/skills/invalid-cycle-skill.yaml").read_text()
```

---

### 5.6.3 Test Types by Layer

#### Unit Tests (always, no external dependencies)

**`test_classify_task_type.py`** — covers every entry in `TASK_TYPE_RULES`:

```python
@pytest.mark.parametrize("query,expected", [
    ("refund my subscription", "finance"),
    ("post to linkedin", "content"),
    ("analyze competitor pricing", "research"),
    ("debug my API", "engineering"),
    ("check my calendar", "operations"),
    ("what's the weather", "general"),
])
def test_classify_task_type(query, expected):
    assert classify_task_type(query) == expected
```

**`test_skill_graph_validation.py`** — structural tests:

```python
def test_rejects_cycle(skill_yaml_with_cycle):
    errors = validate_skill_graph(yaml.safe_load(skill_yaml_with_cycle))
    assert any("Cycle" in e for e in errors)

def test_rejects_missing_node_reference(skill_yaml):
    skill = yaml.safe_load(skill_yaml)
    skill["edges"].append({"from": "nonexistent", "to": "verify", "condition": "x"})
    errors = validate_skill_graph(skill)
    assert any("missing node" in e for e in errors)

def test_rejects_approval_node_with_no_outgoing_edges(skill_yaml):
    skill = yaml.safe_load(skill_yaml)
    for node in skill["nodes"]:
        if node["id"] == "draft":
            node["requires_approval"] = True
    skill["edges"] = [e for e in skill["edges"] if e["from"] != "draft"]
    errors = validate_skill_graph(skill)
    assert any("requires approval" in e and "no outgoing" in e for e in errors)

def test_accepts_valid_skill(skill_yaml_valid):
    errors = validate_skill_graph(yaml.safe_load(skill_yaml_valid))
    assert errors == []
```

**`test_safe_yaml_loading.py`** — canary for the RCE vector in Section 3b.1:

```python
MALICIOUS_YAML = """
name: bomb
yaml_content: |
  !!python/object/apply:os.system ["echo pwned"]
"""

def test_safe_yaml_rejects_object_deserialization():
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.safe_load(MALICIOUS_YAML)
    # FullLoader would succeed here — safe_load must reject
```

**`test_hmac_tamper_detection.py`** — Section 3b.8 coverage:

```python
def test_semantic_read_excludes_tampered_entry(tmp_path):
    store = SharedMemoryStore(chroma_dir=str(tmp_path), hmac_key=b"test-key")
    # Write a legitimate entry
    await store.write_semantic("customer prefers replacement", project_id="p1",
                                task_id="t1", agent_role="cmo")
    # Tamper with it directly in ChromaDB
    chroma = store.vector_store
    entry = chroma.get(where={"task_id": "t1"})[0]
    chroma.update(entry["id"], {"hmac": "tampered-signature"})
    # Read it back
    results = store.read_semantic("customer prefers", project_id="p1")
    # Tampered entry must be excluded
    assert not any(r.id == entry["id"] for r in results)
    # Log warning is sufficient evidence of detection
```

**`test_fernet_round_trip.py`** — Section 4.3 coverage:

```python
from cryptography.fernet import Fernet

def test_token_encryption_round_trip():
    key = Fernet.generate_key()
    f = Fernet(key)
    original = b"gho_xxxxxxxxxxxxx"
    encrypted = f.encrypt(original)
    assert encrypted != original
    assert f.decrypt(encrypted) == original

def test_different_keys_produce_different_ciphertext():
    k1, k2 = Fernet.generate_key(), Fernet.generate_key()
    assert Fernet(k1).encrypt(b"secret") != Fernet(k2).encrypt(b"secret")

def test_scrub_redacts_all_sensitive_fields():
    payload = {
        "task_id": "123",
        "auth_token_enc": "super-secret",
        "nested": {"access_token": "also-secret", "safe_field": "ok"},
        "list": [{"password": "bad", "role": "admin"}],
    }
    result = scrub(payload)
    assert result["auth_token_enc"] == "[REDACTED]"
    assert result["nested"]["access_token"] == "[REDACTED]"
    assert result["nested"]["safe_field"] == "ok"
    assert result["list"][0]["password"] == "[REDACTED]"
    assert result["list"][0]["role"] == "admin"
```

**`test_circuit_breaker.py`** — LLM failure handling (Section 5b):

```python
@pytest.mark.parametrize("failures,expected_model", [
    (0, "openai/gpt-4o"),
    (4, "openai/gpt-4o"),
    (5, "anthropic/claude-3.5-sonnet"),  # circuit open, skip gpt
    (7, "google/gemini-2.0-flash"),       # all failed, last resort
])
def test_circuit_breaker_skips_broken_model(failures, expected_model):
    cb = CircuitBreaker(FALLBACK_CHAIN, max_failures=5)
    for _ in range(failures):
        cb.record_failure()
    assert cb.get_next() == expected_model
```

**`test_rate_limiter.py`** — integration semaphore (Section 5b):

```python
@pytest.mark.asyncio
async def test_github_semaphore_allows_5_concurrent():
    sem = INTEGRATION_RATE_LIMITS["github"]
    async with sem:
        async with sem:
            async with sem:
                async with sem:
                    async with sem:
                        # 5th slot taken — 6th would block
                        start = asyncio.get_event_loop().time()
                        try:
                            async with asyncio.wait_for(sem.acquire(), timeout=0.1):
                                pass
                        except asyncio.TimeoutError:
                            pass  # correctly blocked
                        elapsed = asyncio.get_event_loop().time() - start
                        assert elapsed < 0.05  # immediate rejection, no wait
```

---

#### Integration Tests (real stores, no real LLM)

**`test_task_lifecycle.py`** — full state machine (Section 4.1):

```python
@pytest.mark.asyncio
async def test_task_transitions_pending_to_completed():
    task_id = await create_task("Summarize my GitHub commits")
    state = await get_task(task_id)
    assert state["status"] == "pending"

    await start_task(task_id)
    state = await get_task(task_id)
    assert state["status"] == "running"

    # skill node has no approval gate — runs through
    await wait_for_completion(task_id, timeout=30)
    state = await get_task(task_id)
    assert state["status"] == "completed"
    assert state["completed_at"] is not None

@pytest.mark.asyncio
async def test_task_pauses_at_approval_gate():
    task_id = await create_task("Draft a refund email")
    await start_task(task_id)
    state = await wait_for_status(task_id, "draft", timeout=30)
    assert state["context"]["approval_deadline_iso"] is not None

    await resolve_approval(task_id, action="approved")
    state = await wait_for_status(task_id, "executing", timeout=10)
    assert state["context"]["draft_content"] is not None
```

**`test_draft_approval_flow.py`** — Sections 2.5 and 2.7.3:

```python
@pytest.mark.asyncio
async def test_websocket_sends_draft_ready_on_approval_gate(webserver):
    task_id = await create_task("Draft customer reply")
    await start_task(task_id)

    msg = await webserver.get_message(type="draft_ready", timeout=10)
    assert msg["task_id"] == task_id
    assert msg["node_id"] == "draft"
    assert "body" in msg["draft"]

@pytest.mark.asyncio
async def test_editing_draft_before_approval_sets_edited_content():
    task_id = await create_task("Draft customer reply")
    await start_task(task_id)
    await wait_for_status(task_id, "draft")

    edited = {"subject": "Re: your email", "body": "Hi, here's the reply..."}
    await resolve_approval(task_id, action="approved", edited_content=edited)

    task = await get_task(task_id)
    assert task["steps"][-1]["approval_edited_content"] == edited
    assert task["context"]["draft_content"] == edited  # replaces draft
```

**`test_chroma_semantic_memory.py`** — TTL, LRU, project scoping:

```python
@pytest.mark.asyncio
async def test_semantic_memory_respects_project_scope(chroma_tmp_dir):
    store = SemanticMemory(chroma_tmp_dir)
    await store.add("client secret info", project_id="acme")
    await store.add("general wisdom", project_id=None)

    acme_results = await store.search("client", project_id="acme")
    assert all(r["project_id"] == "acme" for r in acme_results)

    global_results = await store.search("general", project_id=None)
    assert all(r["project_id"] is None for r in global_results)

    # acme query should not return global-only memories
    acme_texts = [r["text"] for r in acme_results]
    assert "general wisdom" not in str(acme_texts)

@pytest.mark.usefixtures("freezegun")
@pytest.mark.asyncio
async def test_semantic_memory_evicts_after_90d(chroma_tmp_dir):
    store = SemanticMemory(chroma_tmp_dir, ttl_days=90)
    with freezegun.freeze_time("2025-01-01"):
        await store.add("old memory", project_id="p1")
    with freezegun.freeze_time("2025-04-01"):  # 90 days later
        results = await store.search("old memory", project_id="p1")
        # After TTL, entry should be excluded
        assert len(results) == 0
```

**`test_websocket_messages.py`** — protocol completeness:

```python
def test_ws_message_serializes_all_variants():
    for msg_type, payload in WSMessage.__annotations__.items():
        msg = construct_ws_message(msg_type, payload)
        json_str = json.dumps(msg)
        parsed = json.loads(json_str)
        assert parsed["type"] == msg_type

@pytest.mark.asyncio
async def test_ws_reconnect_sync_includes_all_active_tasks(run_server, webclient):
    task_ids = [await create_task(f"task {i}") for i in range(3)]
    # disconnect, reconnect
    await webclient.disconnect()
    await webclient.connect()
    sync = await webclient.get_message(type="sync", timeout=5)
    assert set(sync["tasks"]) == set(task_ids)
```

---

#### E2E Tests (Playwright — full stack)

```python
# backend/tests/e2e/test_task_submission_flow.py
import pytest
from playwright.sync_api import expect, Page

def test_user_submits_task_and_sees_routing_state(live_server: LiveServer, page: Page):
    page.goto(live_server.url)
    page.get_by_placeholder("Ask your AI team...").fill(
        "Summarize my GitHub commits from the last 24 hours"
    )
    page.get_by_role("button", name="Send").click()
    # Should see routing state immediately
    expect(page.get_by_text("Routing to Engineer agent")).to_be_visible()

def test_draft_approval_card_shows_edit_button(live_server: Page):
    # Set up: task reaches approval gate
    task_id = create_task_with_approval_gate()
    page.goto(f"{live_server.url}/tasks/{task_id}")
    expect(page.get_by_text("Awaiting your approval")).to_be_visible()
    expect(page.get_by_role("button", name="Edit draft before approving")).to_be_visible()

def test_ws_disconnect_shows_banner(live_server: Page, ws_server):
    page.goto(live_server.url)
    ws_server.close()  # simulate disconnect
    expect(page.get_by_text("Live updates paused")).to_be_visible()
```

---

### 5.6.4 LLM/Agent Testing Strategy

Testing an LLM-powered system without burning API credits or hitting non-determinism:

**Routing tests (supervisor)** — use a mock LLM that returns controlled text.
The mock is injected at the LangChain chat model layer:

```python
def test_supervisor_routes_content_task_to_cmo():
    with patch("langchain_openai.ChatOpenAI") as mock_llm:
        mock_llm.return_value.invoke.return_value = MagicMock(content="cmo")
        result = supervisor({"current_task": "write a linkedin post"})
        assert result == "cmo"
```

**Draft output tests** — do NOT assert on exact copy. Assert on structure:

```python
def test_draft_has_required_fields():
    draft = run_skill_node(skill_id="subscription-refund", task="refund request")
    assert "subject" in draft
    assert "body" in draft
    assert len(draft["body"]) > 20
    assert draft["subject"] != ""  # not empty

def test_draft_respects_writing_style():
    profile = WritingProfile(tone="casual", sentence_length="short", ...)
    draft = render_draft("thanks for your help", style=profile)
    words = draft["body"].split()
    avg_len = sum(len(w) for w in words) / len(words)
    assert avg_len < 8  # short words for casual tone
```

**Fuzzy LLM output testing with Hypothesis:**

```python
from hypothesis import given, strategies as st, settings

@given(task_type=strategy(st.sampled_from(["email", "content", "research", "engineering"])))
@settings(max_examples=200)
def test_classify_task_type_covers_all_types(task_type):
    # Verify keyword rules don't overlap into "general" for known types
    result = classify_task_type(f"test {task_type} task")
    assert result != "general" or task_type == "general"
```

---

### 5.6.5 Coverage Targets

| Layer | Metric | Minimum |
|---|---|---|
| Backend unit tests | Line coverage | 70% |
| Backend integration tests | Line coverage | 50% |
| Skill validation + security primitives | Line coverage | 95% |
| Frontend unit tests | Component coverage | 60% |
| Key paths (task submit → complete, draft → approve) | E2E | 100% |

Coverage gates enforced in CI: `pytest --cov=backend --cov-report=term-missing --cov-fail-under=70`.

Critical paths that must never regress without human review:
- `validate_skill_graph()` — 0% tolerance for coverage drop
- `yaml.safe_load()` path — 100% coverage required
- `hmac.verify()` read path — 100% coverage
- `scrub()` — 100% coverage
- All task state machine transitions — 100% E2E coverage

---

### 5.6.6 CI/CD Pipeline

**GitHub Actions — `tests.yml`:**

```yaml
name: Tests

on:
  push:
    branches: [main, fix/**]
  pull_request:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      chroma:
        image: chromadb/chroma:0.4.22
        ports: ["8000:8000"]
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
        ports: ["5432:5432"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e "backend[test]"
      - run: pytest backend/tests/unit -q --tb=short
      - run: pytest backend/tests/integration -q --tb=short
        env:
          CHROMA_HOST: localhost:8000
          POSTGRES_HOST: localhost:5432
      - uses: codecov/codecov-action@v4

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: npm ci
      - run: npm run test:unit -- --coverage
      - run: npm run test:e2e
        env:
          VITE_API_URL: http://localhost:8000

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install ruff mypy
      - run: ruff check backend/ --fix
      - run: mypy backend/ --ignore-missing-imports
      - run: npm run lint
```

**Branch protection (main):** Require passing CI, 1 approving review.
**Merge requirement:** All unit tests green, no new `pytest.mark.skip` added without justification.

---

### 5.6.7 Phase Exit Criteria as Test Assertions

Each phase's exit criteria must be expressed as automated test assertions, not
human-verifiable descriptions:

| Phase | Exit Criterion | Test Assertion |
|---|---|---|
| Phase 1 | Task enters system → agent retrieves memories → output stored | `test_task_stores_episodic_on_completion` |
| Phase 1 | Agent resumes after restart (checkpointer) | `test_langgraph_checkpointer_resume` |
| Phase 2 | Draft-first pauses and resumes on approval | `test_draft_approval_flow_blocks_until_approved` |
| Phase 2 | Skill version pinning: mid-execution update doesn't affect running task | `test_skill_version_pinned_at_invocation` |
| Phase 3 | Temporal worker handles task failure with retry and DLQ | `test_temporal_retry_on_transient_failure` |
| Phase 3 | Webhook delivers Stripe event → agent processes → action taken | `test_stripe_webhook_triggers_temporal_workflow` |
| Phase 4 | Agent runs 7 days without manual restart | `test_seven_day_continuous_run` (separate stress test) |
| Phase 4 | Draft-first completes on 5 different skill types | `test_draft_first_completes_all_skill_types` |

---

### 5.6.8 Frontend Testing Stack

| Tool | Purpose |
|---|---|
| `vitest` | Test runner for Vite-based React project |
| `@testing-library/react` | DOM interaction testing (not implementation details) |
| `@testing-library/user-event` | Simulate real user interactions (type, click, keyboard) |
| `msw` (Mock Service Worker) | Mock API responses at the network layer, not just at fetch calls |
| `playwright` | Browser E2E tests (full stack, real HTTP) |
| `happy-dom` | Lightweight DOM for unit tests without a browser |

**Example RTL test for `DraftReview` card:**

```typescript
// frontend/src/tests/unit/DraftReview.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DraftReviewCard } from '../../components/DraftReview';

const draft = {
  task_id: '123',
  node_id: 'draft',
  subject: 'Re: your subscription',
  body: 'Hi Sarah,\n\nThanks for reaching out...',
  approval_deadline_iso: new Date(Date.now() + 86400000).toISOString(),
};

it('shows edited badge when user modifies draft', async () => {
  const user = userEvent.setup();
  render(<DraftReviewCard draft={draft} onApprove={vi.fn()} onReject={vi.fn()} />);

  await user.click(screen.getByText('Edit draft before approving'));
  const textarea = screen.getByRole('textbox');
  await user.clear(textarea);
  await user.type(textarea, 'Hi Sarah,\n\nI am happy to help...');

  expect(screen.getByText('You modified this draft')).toBeInTheDocument();
});
```

---

### 5.6.9 Exception Taxonomy

Every exception in MindForge belongs to one of four categories. Tests must assert
the correct category for each error type:

| Category | Symbol | Examples | What tests must verify |
|---|---|---|---|
| **Retried** | `E_RETRY` | `RateLimitError`, `IntegrationTimeout`, `TransientFailure` | Retry count increments; no episodic memory write; task stays `in_progress` |
| **Escalated** | `E_ESCALATE` | `PermissionError`, `AuthFailure`, `SafetyViolation` | COO agent notified; task → `escalated`; error stored in episodic memory |
| **Logged only** | `E_LOG` | `HMACTamperError`, `InvalidTokenError`, `ScrubbedDataWarning` | Logged with scrubbed context; task continues or fails gracefully; no exception propagates |
| **Panic** | `E_PANIC` | `OutOfMemory`, `UnrecoverableState`, `DatabaseCorruption` | Task → `failed`; Temporal workflow cancelled; human alert fired |

**Implementation:**

```python
# backend/exceptions.py
from enum import Enum

class ExceptionCategory(str, Enum):
    RETRY = "retry"       # safe to retry automatically
    ESCALATE = "escalate" # requires human intervention
    LOG = "log"           # record only, do not propagate
    PANIC = "panic"       # unrecoverable, halt

EXCEPTION_CATEGORY: dict[type[Exception], ExceptionCategory] = {
    RateLimitError:     ExceptionCategory.RETRY,
    IntegrationTimeout: ExceptionCategory.RETRY,
    TransientFailure:   ExceptionCategory.RETRY,
    PermissionError:    ExceptionCategory.ESCALATE,
    AuthFailure:        ExceptionCategory.ESCALATE,
    SafetyViolation:    ExceptionCategory.ESCALATE,
    HMACTamperError:    ExceptionCategory.LOG,
    InvalidTokenError:  ExceptionCategory.LOG,
    ScrubbedDataWarning: ExceptionCategory.LOG,
    OutOfMemory:        ExceptionCategory.PANIC,
    DatabaseCorruption: ExceptionCategory.PANIC,
}

def classify_exception(exc: Exception) -> ExceptionCategory:
    for exc_type, category in EXCEPTION_CATEGORY.items():
        if isinstance(exc, exc_type):
            return category
    return ExceptionCategory.ESCALATE  # unknown → conservative default
```

**Test expectations for each category:**

```python
# E_RETRY: task stays in_progress, retry_count incremented, no final output stored
def test_rate_limit_error_triggers_retry(task_in_progress):
    task = task_in_progress(status="in_progress")
    exc = RateLimitError("GitHub rate limit hit")
    result = handle_exception(task, exc)
    assert result.action == "retry"
    assert task.retry_count == 1
    assert task.status == "in_progress"

# E_ESCALATE: task → escalated, COO notified, error logged
def test_permission_error_escalates(task_in_progress):
    task = task_in_progress(status="in_progress")
    exc = PermissionError("not allowed to use stripe")
    result = handle_exception(task, exc)
    assert result.action == "escalate"
    assert task.status == "escalated"
    mock_notify_coo.assert_called_once()

# E_LOG: task continues, warning logged
def test_hmac_error_logged_but_continues(task_in_progress):
    task = task_in_progress(status="in_progress")
    exc = HMACTamperError("HMAC mismatch on GitHub webhook")
    result = handle_exception(task, exc)
    assert result.action == "log"
    assert task.status == "in_progress"  # task not stopped

# E_PANIC: task → failed, workflow cancelled, human alerted
def test_database_corruption_is_panic(task_in_progress):
    task = task_in_progress(status="in_progress")
    exc = DatabaseCorruption("checksum mismatch in PGLite")
    result = handle_exception(task, exc)
    assert result.action == "panic"
    assert task.status == "failed"
    mock_alert_human.assert_called_once()
```

---

### Data Deletion (single-user)

Since this is a single-user self-hosted installation, data deletion is simple — just run
the deletion commands against the local stores. In Phase 4+, a dashboard button handles this:

```
DELETE /memories/all
  → Delete all SemanticMemory (ChromaDB truncate collection)
  → Delete all EpisodicMemory (PGLite DELETE FROM episodic_memory)
  → Reset WritingProfile fields to defaults
  → Returns: { "deleted_vectors": N, "deleted_records": M }

GET /export
  → Return all memories as JSON: semantic + episodic + profile
  → Review before requesting deletion

DELETE /reset
  → Full factory reset: all of the above + clear all Integration records + Task history
  → This is irreversible — a confirmation prompt is required in the UI
```

### Cost Estimation (self-hosted, single-user)

Rough monthly budget for a solo self-hosted setup:

| Cost center | Estimate |
|---|---|
| OpenRouter API (gpt-4o, ~$15/1M tokens) | $0–$50/mo depending on usage |
| ChromaDB (self-hosted, 1GB RAM) | $0 (your existing machine) |
| PGLite (self-hosted) | $0 |
| Temporal (self-hosted) | $0 |
| Composio Cloud (Phase 4, 1000 free calls/mo) | $0–$25/mo |
| Redis (self-hosted or cloud) | $0–$10/mo |
| Email (IMAP/SMTP — existing provider) | $0 |
| **Total** | **$0–$85/mo** |

The cost is driven almost entirely by LLM usage. Aggressive caching and lower-cost models
(gemini-2-flash at ~$0.07/1M tokens) bring the total to near zero for light usage.

---

## 5.7 AI/ML Architecture

This section specifies inference routing, the RAG pipeline, prompt caching,
tool/skills/MCP layering, and model-level configuration. It applies across all phases.

---

### 5.7.1 Hybrid Inference Router

**Principle:** Not every prompt needs a frontier cloud model. Routing simple prompts to a
local inference server reduces cost and latency without sacrificing quality where it matters.

#### Routing tiers

| Tier | Criteria | Model | Latency target | Cost |
|---|---|---|---|---|
| `local` | ≤256 tokens, no tool calls, no multi-step reasoning, no images | Ollama (`llama3.2:3b` or `qwen2.5:7b`) | <200ms | Free |
| `cloud_fast` | ≤2048 tokens, simple tool use, single-step | OpenRouter: `google/gemini-2.0-flash` | <2s | ~$0.001/1K |
| `cloud_heavy` | >2048 tokens, multi-step, complex reasoning, or explicit request | OpenRouter: `openai/gpt-4o` → `anthropic/claude-3.5-sonnet` | <10s | ~$0.01-0.03/1K |

#### Routing implementation

```python
# backend/agents/inference.py
from dataclasses import dataclass
from enum import Enum

class InferenceTier(str, Enum):
    LOCAL = "local"
    CLOUD_FAST = "cloud_fast"
    CLOUD_HEAVY = "cloud_heavy"

@dataclass
class LLMConfig:
    tier: InferenceTier
    model: str
    local_url: str = "http://127.0.0.1:11434/api/generate"
    cloud_provider: str = "openrouter"
    max_tokens: int = 4096
    temperature: float = 0.0

TIER_CONFIGS: dict[InferenceTier, LLMConfig] = {
    InferenceTier.LOCAL:       LLMConfig(InferenceTier.LOCAL,       "llama3.2:3b"),
    InferenceTier.CLOUD_FAST:  LLMConfig(InferenceTier.CLOUD_FAST,  "google/gemini-2.0-flash"),
    InferenceTier.CLOUD_HEAVY:  LLMConfig(InferenceTier.CLOUD_HEAVY, "openai/gpt-4o"),
}

def classify_tier(task_description: str, estimated_tokens: int,
                  has_tools: bool, is_multi_step: bool) -> InferenceTier:
    """Routing heuristic — no LLM call needed."""
    if estimated_tokens <= 256 and not has_tools and not is_multi_step:
        return InferenceTier.LOCAL
    if estimated_tokens <= 2048 and not is_multi_step:
        return InferenceTier.CLOUD_FAST
    return InferenceTier.CLOUD_HEAVY

def estimate_tokens(text: str) -> int:
    """Rough token estimate: 4 chars/token for English."""
    return len(text) // 4

async def llm_complete(prompt: str, tier: InferenceTier | None = None,
                       system: str = "") -> str:
    if tier is None:
        tier = classify_tier(prompt, estimate_tokens(prompt),
                             has_tools=False, is_multi_step=False)

    cfg = TIER_CONFIGS[tier]

    if cfg.tier == InferenceTier.LOCAL:
        return await _ollama_complete(cfg, system, prompt)
    return await _openrouter_complete(cfg, system, prompt)
```

**Ollama server:** `ollama serve` runs locally. Pull models once:
`ollama pull llama3.2:3b`. GPU recommended (P40 has 24GB VRAM — fits 7B Q4 comfortably).
CPU fallback works for 3B at ~30 tokens/sec.

**OpenRouter key:** stored in `.env` as `OPENROUTER_API_KEY`, passed via header
`Authorization: Bearer {key}`.

#### Model-per-role assignment

Each agent role can be pinned to a specific tier:

```python
AGENT_MODEL_CONFIG: dict[str, InferenceTier] = {
    "coo":        InferenceTier.CLOUD_HEAVY,  # planning, escalation decisions
    "cmo":        InferenceTier.CLOUD_FAST,   # email drafting, most tasks
    "researcher": InferenceTier.CLOUD_HEAVY, # multi-source analysis
    "engineer":   InferenceTier.CLOUD_FAST,   # GitHub API summaries, code review
}
```

The supervisor passes `agent_role` to `llm_complete()` which selects the tier
from `AGENT_MODEL_CONFIG` unless overridden by the skill definition.

---

### 5.7.2 `classify_intent()` — Skill Intent Classifier

Called when keyword matching misses (Section 2.3, step 3). A lightweight, structured
classification over the known skill intent taxonomy.

```python
# backend/skills/classifier.py

SKILL_INTENTS = [
    "email_draft", "email_reply", "email_summary",
    "github_activity", "github_issue", "github_pr_review",
    "refund_negotiation", "billing_inquiry", "invoice_review",
    "content_post", "content_edit", "content_strategy",
    "research_summary", "research_comparison", "research_alert",
    "calendar_schedule", "calendar_conflict", "meeting_prep",
    "general",
]

CLASSIFY_INTENT_PROMPT = """\
You are a task classifier. Given the user query, output exactly one intent label
from this list: {intents}.

Query: {query}
Intent:"""

async def classify_intent(query: str) -> str:
    """Lightweight LLM call for skill intent classification."""
    rendered = CLASSIFY_INTENT_PROMPT.format(
        intents=", ".join(SKILL_INTENTS),
        query=query
    )
    result = await llm_complete(
        rendered,
        tier=InferenceTier.CLOUD_FAST,  # always cloud fast, never local
        system="Output only the intent label, nothing else."
    )
    label = result.strip().lower()
    # Validate against known taxonomy
    if label in SKILL_INTENTS:
        return label
    # Fallback: fuzzy match on first word
    for intent in SKILL_INTENTS:
        if intent.startswith(label.split()[0]):
            return intent
    return "general"
```

**Design notes:**
- Uses `CLOUD_FAST` tier — never local, never the heaviest model.
- No JSON mode needed; structured output validated against the taxonomy.
- `classify_task_type()` for episodic memory uses keyword matching only (Section 2.2);
  `classify_intent()` is a separate, skill-specific taxonomy used for skill routing.

---

### 5.7.3 Embedding Pipeline

#### Embedding model

| Model | Dimensions | notes |
|---|---|---|
| `nomic-embed-text:latest` | 768 | **Recommended** — local, 1.5GB, good quality, Ollama-compatible |
| `text-embedding-3-small` (OpenAI) | 1536 | Cloud, paid per 1K tokens, SOTA quality |
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | CPU-friendly, fast, good for short texts |

**Recommended for this build:** `nomic-embed-text` via Ollama — runs on the local GPU,
free, and produces high-quality embeddings for under 2GB VRAM.

```python
# backend/memory/embeddings.py
import ollama

EMBEDDING_MODEL = "nomic-embed-text"

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings via local Ollama server."""
    response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=texts[0])
    return [response["embedding"]]
```

#### Chunking strategy

Text is chunked before embedding to ensure precise retrieval boundaries:

```python
# backend/memory/chunker.py
from dataclasses import dataclass

@dataclass
class ChunkConfig:
    chunk_size: int = 512       # tokens per chunk (not characters)
    chunk_overlap: int = 64     # tokens of overlap between chunks
    min_chunk_size: int = 32   # drop chunks below this size

def chunk_text(text: str, config: ChunkConfig = ChunkConfig()) -> list[dict]:
    """
    Split text into overlapping token-bounded chunks.
    Splits on sentence boundaries where possible to preserve meaning.
    """
    # 1. Rough character estimate (4 chars/token for English)
    char_limit = config.chunk_size * 4
    sentences = _split_into_sentences(text)
    chunks, current, current_len = [], [], 0

    for sent in sentences:
        sent_len = len(sent) // 4  # token estimate
        if current_len + sent_len > char_limit and current:
            chunks.append({"text": " ".join(current), "token_count": current_len})
            # Keep overlap
            overlap_text = " ".join(current)[-config.chunk_overlap * 4:]
            current = [overlap_text, sent]
            current_len = len(overlap_text) // 4 + sent_len
        else:
            current.append(sent)
            current_len += sent_len

    if current:
        chunks.append({"text": " ".join(current), "token_count": current_len})
    return [c for c in chunks if c["token_count"] >= config.min_chunk_size]
```

**Write path:** When `SharedMemoryStore.write_semantic()` is called, the text is chunked,
each chunk is embedded, and stored with metadata `{project_id, task_id, agent_role, chunk_index}`.

**Read path:** The query is embedded once; cosine similarity is computed against all chunks;
top-k results are fetched, then **reassembled into their original text** by grouping by
`task_id` before being injected into the prompt.

---

### 5.7.4 Retrieval — Hybrid Search + Reranking

#### Hybrid search

Pure vector search misses exact keyword matches. Combine it with BM25:

```python
# backend/memory/retriever.py
from rank_bm25 import BM25Okapi
import numpy as np

class HybridRetriever:
    def __init__(self, vector_store, chunk_config: ChunkConfig):
        self.vector_store = vector_store
        self.chunk_config = chunk_config
        self._bm25_index: BM25Okapi | None = None
        self._corpus: list[str] = []
        self._corpus_ids: list[str] = []

    def build_bm25_index(self, texts: list[str], ids: list[str]):
        """Rebuild BM25 index after writes. Called periodically (not on every write)."""
        self._corpus = texts
        self._corpus_ids = ids
        tokenized = [t.lower().split() for t in texts]
        self._bm25_index = BM25Okapi(tokenized)

    async def retrieve(self, query: str, project_id: str | None = None,
                      top_k: int = 5, min_similarity: float = 0.65) -> list[dict]:
        # 1. Vector search
        query_emb = embed_texts([query])[0]
        vector_results = self.vector_store.similarity_search_with_score(
            query_emb, k=top_k * 2,
            filter={"project_id": project_id} if project_id else {}
        )
        vector_ids = {r["id"]: r for r in vector_results}

        # 2. BM25 search (if index is built)
        bm25_scores: dict[str, float] = {}
        if self._bm25_index is not None:
            tokenized_q = query.lower().split()
            bm25_scores_raw = self._bm25_index.get_scores(tokenized_q)
            max_bm25 = max(bm25_scores_raw) if max(bm25_scores_raw) > 0 else 1
            bm25_scores = {
                self._corpus_ids[i]: s / max_bm25
                for i, s in enumerate(bm25_scores_raw)
            }

        # 3. Reciprocal Rank Fusion
        fused: dict[str, float] = {}
        all_ids = set(list(vector_ids.keys()) + list(bm25_scores.keys()))
        k = 60  # RRF constant
        for rid in all_ids:
            v_score = 1 - vector_ids[rid]["score"]  # convert distance → similarity
            b_score = bm25_scores.get(rid, 0)
            fused[rid] = (0.5 / (k + 1 + v_score)) + (0.5 / (k + 1 + b_score))

        # 4. Filter by minimum similarity and return top-k
        results = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        return [
            {**vector_ids[rid], "fused_score": score}
            for rid, score in results
            if rid in vector_ids and score >= min_similarity
        ][:top_k]
```

#### Retrieval threshold

Cosine similarity < 0.65 is discarded — this prevents low-relevance memories from
polluting the prompt context.

#### Reranking (optional, Phase 3+)

After hybrid retrieval, a cross-encoder reranker scores (query, document) pairs
and reorders the final top-k:

```python
# Phase 3 addition
from sentence_transformers import CrossEncoder

RERANKER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

def rerank(query: str, results: list[dict], top_k: int = 5) -> list[dict]:
    pairs = [(query, r["text"]) for r in results]
    scores = RERANKER.predict(pairs)
    ranked = sorted(zip(results, scores), key=lambda x: x[1], reverse=True)
    return [r for r, _ in ranked[:top_k]]
```

---

### 5.7.5 Prompt Caching

OpenRouter and OpenAI support `cache_control` for cached context reuse. This spec
uses it to eliminate repeated transmission of system prompts and memory context.

#### Cacheable segments

| Segment | Refresh trigger | Cache TTL |
|---|---|---|
| System prompt (agent role + capabilities) | Skill version bump | 24h or until skill change |
| Writing style profile | `WritingProfile` update | Same |
| Skill template (node instructions) | Skill version bump | Same |
| Memory context (retrieved chunks) | Every LLM call | Per-call, no reuse |

```python
# backend/agents/prompt_builder.py
from dataclasses import dataclass, field

@dataclass
class PromptSegment:
    content: str
    cached: bool = False           # include in cache_control block
    cache_key: str | None = None  # stable key for cache invalidation

@dataclass
class Prompt:
    segments: list[PromptSegment] = field(default_factory=list)
    max_tokens: int = 4096

    def build_messages(self) -> list[dict]:
        messages = []
        cache_blocks = []
        for seg in self.segments:
            msg = {"content": seg.content}
            if seg.cached and seg.cache_key:
                msg["cache_control"] = {"type": "ephemeral", "metadata": {"key": seg.cache_key}}
                cache_blocks.append(seg.cache_key)
            messages.append(msg)
        return messages

# Usage
def build_supervisor_prompt(task: str, agent_role: str,
                             memory_context: str, skill_name: str | None):
    return Prompt(segments=[
        PromptSegment(
            content=AGENT_ROLES[agent_role],
            cached=True,
            cache_key=f"system:{agent_role}"  # invalidated on skill change
        ),
        PromptSegment(
            content=f"Relevant context:\n{memory_context}",
            cached=False  # unique per call
        ),
        PromptSegment(
            content=f"Task: {task}",
            cached=False
        ),
    ])
```

**Cache invalidation events:** When a `Skill` row is updated (version bump), the
`cache_key` for `system:{agent_role}` changes, forcing re-cache of the system prompt.
Writing style profile updates invalidate `style:user:default`.

---

### 5.7.6 `max_context_tokens` Guard

The combined prompt must not exceed the model's context window. Enforce a hard limit:

```python
# backend/agents/prompt_builder.py
from transformers import AutoTokenizer

TOKENIZER = AutoTokenizer.from_pretrained("cl100k_base")  # OpenAI's tokenizer

MAX_CONTEXT = {
    InferenceTier.LOCAL:       8192,
    InferenceTier.CLOUD_FAST:  128_000,   # gemini-2.0-flash context
    InferenceTier.CLOUD_HEAVY: 200_000,   # gpt-4o / claude context
}

def truncate_prompt(prompt: Prompt, tier: InferenceTier) -> Prompt:
    """Truncate segments (non-cached first) to fit within context window."""
    limit = MAX_CONTEXT[tier] - 512  # reserve 512 tokens for response
    total = sum(len(TOKENIZER.encode(seg.content)) for seg in prompt.segments)
    if total <= limit:
        return prompt

    # Drop non-cached segments oldest-first until within limit
    truncated = [seg for seg in prompt.segments if seg.cached]
    for seg in prompt.segments:
        if seg.cached:
            continue
        seg_tokens = len(TOKENIZER.encode(seg.content))
        if total - seg_tokens >= limit:
            total -= seg_tokens
        else:
            # Partial keep — truncate text
            truncated.append(PromptSegment(
                content=_truncate_to_tokens(seg.content, total - limit),
                cached=False
            ))
            break
    return Prompt(segments=truncated)
```

---

### 5.7.7 Unified Tool Interface

"Tool" is overloaded in this spec. This section defines the canonical tool interface
and resolves the ambiguity between LangGraph tools, integration API calls, and MCP endpoints.

#### Tool contract

Every tool — regardless of underlying implementation — conforms to this interface:

```python
# backend/tools/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ToolResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    tool_name: str = ""
    latency_ms: float = 0.0

class BaseTool(ABC):
    name: str                    # e.g. "stripe_api", "github_fetch"
    description: str             # used by the LLM to select the right tool
    input_schema: dict           # JSON Schema for tool arguments
    retry_config: dict           # from skill YAML or default
    required_integrations: list[str] = []  # integration IDs this tool needs

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        ...

    @abstractmethod
    async def validate_auth(self) -> bool:
        """Check that credentials are present and not expired."""
        ...
```

#### Tool registration

Tools are registered at startup from the integration registry and MCP servers:

```python
# backend/tools/registry.py
class ToolRegistry:
    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool):
        cls._tools[tool.name] = tool

    @classmethod
    def get(cls, name: str) -> BaseTool:
        if name not in cls._tools:
            raise ToolNotFoundError(f"Tool '{name}' not registered")
        return cls._tools[name]

    @classmethod
    def list_(cls) -> list[BaseTool]:
        return list(cls._tools.values())

    @classmethod
    def for_skill(cls, skill_definition: dict) -> list[BaseTool]:
        """Return tools required by a skill, checked against allowed integrations."""
        tool_names = skill_definition.get("tools", [])
        return [cls.get(n) for n in tool_names]

# Skill YAML tool resolution — no longer a dict lookup in node_state
# Now uses the canonical registry:
tool = ToolRegistry.get("stripe_api")
result = await tool.execute(**tool_args)
```

#### MCP client (Phase 4)

MCP servers expose tools over stdio. The MCP client wraps them as `BaseTool`:

```python
# backend/tools/mcp_client.py
from contextlib import asynccontextmanager
import json, subprocess

class MCPServer:
    def __init__(self, name: str, command: list[str], env: dict | None = None):
        self.name = name
        self.command = command
        self.env = env or {}
        self._process: subprocess.AsyncPopen | None = None

    @asynccontextmanager
    async def session(self):
        """Start MCP server, establish session, yield client, clean up on exit."""
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            env={**os.environ, **self.env}
        )
        # Send initialize handshake
        await self._send({"jsonrpc": "2.0", "id": 0,
                           "method": "initialize", "params": {}})
        yield self
        self._process.terminate()
        await self._process.wait()

    async def call_tool(self, tool_name: str, arguments: dict) -> ToolResult:
        resp = await self._request("tools/call",
                                    {"name": tool_name, "arguments": arguments})
        return ToolResult(success=resp.get("success", False),
                          data=resp.get("result", {}),
                          error=resp.get("error"),
                          tool_name=tool_name)

    async def _request(self, method: str, params: dict) -> dict:
        msg = json.dumps({"jsonrpc": "2.0", "id": self._msg_id(),
                          "method": method, "params": params})
        self._process.stdin.write((msg + "\n").encode())
        await self._process.stdin.drain()
        raw = await self._process.stdout.readline()
        return json.loads(raw.decode())
```

**Phase 4 integration config:**

```yaml
# compose.yaml services
mcp-github:
  image: ghcr.io/github/copilot-mcp-server:latest
  command: ["--token", "${GITHUB_TOKEN}"]
mcp-stripe:
  build: ./mcp-servers/stripe/
```

---

### 5.7.8 Skill Graph Tool Resolution

With the unified `ToolRegistry`, the skill graph executor resolves tools at execution
time, not at graph-build time:

```python
# backend/skills/executor.py
async def execute_node(node: SkillNode, context: SkillExecutionContext) -> NodeResult:
    # Resolve tools from registry (not from node_state dict)
    tools = [ToolRegistry.get(name) for name in node.tools]

    # Validate auth for each required integration
    for tool in tools:
        if not await tool.validate_auth():
            return NodeResult(status="failed", error=f"Auth failed for {tool.name}")

    # Build LLM prompt with injected memory context
    memory = await context.memory_store.retrieve(
        query=context.task_description,
        project_id=context.project_id,
        memory_types=node.memory_layers,
    )
    prompt = render_node_prompt(node, context.task_description, memory)

    # Route to appropriate inference tier
    tier = AGENT_MODEL_CONFIG.get(context.agent_role, InferenceTier.CLOUD_FAST)
    response = await llm_complete(prompt, tier=tier, system=node.system_prompt or "")

    # Parse output against output_schema if defined
    if node.output_schema:
        parsed = validate_output(response, node.output_schema)
        if parsed is None:
            return NodeResult(status="failed", error="Output schema validation failed")
        response = parsed

    return NodeResult(status="completed", output=response, tools_used=[t.name for t in tools])
```

**Removed:** The spec previously said "LangGraph executor resolves them using a simple
dictionary lookup (`node_state.get('verify.success')`)" — this was underspecified and
has been replaced with the canonical `ToolRegistry` approach above.

---

### 5.7.9 Streaming Output

Agent output (especially long drafts) streams token-by-token to the dashboard via
WebSocket, reducing perceived latency:

```python
# backend/agents/streaming.py
async def llm_complete_stream(prompt: str, tier: InferenceTier,
                               system: str = "") -> AsyncGenerator[str, None]:
    """Yield tokens as they arrive from the LLM."""
    cfg = TIER_CONFIGS[tier]
    if cfg.tier == InferenceTier.LOCAL:
        async for token in _ollama_stream(cfg, system, prompt):
            yield token
    else:
        async for token in _openrouter_stream(cfg, system, prompt):
            yield token

async def _openrouter_stream(cfg: LLMConfig, system: str,
                              prompt: str) -> AsyncGenerator[str, None]:
    stream = await openrouter.chat.completions.create(
        model=cfg.model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": prompt}],
        stream=True,
        max_tokens=cfg.max_tokens,
    )
    async for chunk in stream:
        token = chunk.choices[0].delta.content or ""
        if token:
            yield token
```

The WebSocket handler broadcasts each token to the dashboard:

```python
# When a skill node starts streaming its draft:
ws_manager = WSConnectionManager()

async def stream_skill_output(task_id: str, node_id: str,
                               token_stream: AsyncGenerator[str, None]):
    accumulated = ""
    async for token in token_stream:
        accumulated += token
        await ws_manager.send(task_id, {
            "type": "stream_token",
            "task_id": task_id,
            "node_id": node_id,
            "token": token,
        })
    # Stream complete — send final assembled content
    await ws_manager.send(task_id, {
        "type": "node_completed",
        "task_id": task_id,
        "node_id": node_id,
        "output": accumulated,
    })
```

---

### 5.7.10 Cost Tracking

OpenRouter spend accumulates per-month. Track it live:

```python
# backend/agents/cost_tracker.py
import httpx
from datetime import datetime

class CostTracker:
    def __init__(self, api_key: str, monthly_budget_usd: float = 10.0):
        self.api_key = api_key
        self.monthly_budget = monthly_budget_usd
        self._spent: float = 0.0
        self._month: str = datetime.utcnow().strftime("%Y-%m")

    async def refresh(self):
        """Fetch current billing period spend from OpenRouter API."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/generation",
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            data = resp.json()
            self._spent = data.get("total_spend", 0.0)
            self._month = data.get("period", self._month)

    def warn_if_exceeded(self):
        if self._spent >= self.monthly_budget:
            logger.warning(
                f"OpenRouter budget exceeded: ${self._spent:.2f} / ${self.monthly_budget:.2f}"
            )

    def record_call(self, model: str, input_tokens: int, output_tokens: int):
        """Record a call for local tracking when billing API is unreachable."""
        # Rough local estimate — OpenRouter API is source of truth
        rate_per_1k = {"openai/gpt-4o": 2.5, "anthropic/claude-3.5-sonnet": 3.0,
                        "google/gemini-2.0-flash": 0.1}
        rate = rate_per_1k.get(model, 0.5)
        self._spent += (input_tokens + output_tokens) / 1000 * rate

        if self._spent > self.monthly_budget:
            self.warn_if_exceeded()
```

Wire `CostTracker.record_call()` into `llm_complete()` after every LLM call.
Call `CostTracker.refresh()` once per day and on startup.

---

### 5.7.11 Unified Retry Abstraction

The spec previously had two separate retry configs: `LLM_RETRY_CONFIG` (Section 5b)
for LLM calls and `retry` in skill YAML for integration API calls. Unify them:

```python
# backend/utils/retry.py
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

DEFAULT_RETRY = {
    "max_attempts": 3,
    "backoff_factor": 2,
    "jitter": True,
    "exceptions": (TimeoutError, RateLimitError, ConnectionError),
}

def with_retry(config: dict | None = None, **overrides):
    cfg = {**DEFAULT_RETRY, **(config or {}), **overrides}
    return retry(
        stop=stop_after_attempt(cfg["max_attempts"]),
        wait=wait_exponential(
            multiplier=cfg["backoff_factor"],
            jitter=cfg["jitter"]
        ),
        retry=retry_if_exception(cfg["exceptions"]),
        reraise=True,
    )

# Usage: replace inline retry logic in skill executor and LLM client
@with_retry(config=skill_node.retry_config)
async def call_llm(prompt: str, tier: InferenceTier) -> str:
    return await llm_complete(prompt, tier)

@with_retry(config={"max_attempts": 2, "backoff_factor": 1.5})
async def call_integration(tool: BaseTool, **kwargs) -> ToolResult:
    return await tool.execute(**kwargs)
```

`with_retry()` handles both cases with a single abstraction, keyed on the config dict
passed at call site.

---

## 5.8 DevOps & Release Engineering

This section covers containerization, service composition, startup ordering, health
reporting, structured logging, backup/restore, database migrations, release management,
rollback procedures, and the local development workflow.

---

### 5e.1 Dockerfiles

#### `backend/Dockerfile` — multi-stage build

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --prefix=/install -r /tmp/requirements.lock

# ── runtime stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Non-root user (matches Section 3b.4 requirement)
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local/lib/python3.12/site-packages

# Copy application code
COPY backend/ /app/backend/

# Run as non-root
USER appuser

# Read-only filesystem (partial — /tmp needed for PGLite and ChromaDB writes)
# Full read-only is set at compose level via --read-only + tmpfs mounts
VOLUME ["/app/data", "/app/logs"]

EXPOSE 8000

# Health check — docker inspects this
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s \
    CMD python -c "import httpx; httpx.get('http://127.0.0.1:8000/health').raise_for_status()"

ENTRYPOINT ["python", "-m", "backend.main"]
```

**Key decisions:**
- Multi-stage build keeps runtime image small (~200MB vs ~1GB).
- `requirements.lock` (not `requirements.txt`) ensures reproducible installs.
- Non-root user enforces the isolation specified in Section 3b.4.
- `HEALTHCHECK` enables `docker inspect` and `depends_on` `condition: service_healthy`.
- `VOLUME` declarations ensure data directories are persisted, not image layers.

#### `frontend/Dockerfile` — multi-stage build

```dockerfile
# syntax=docker/dockerfile:1
FROM node:20-alpine AS builder

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ── runtime stage ────────────────────────────────────────────────────────────
FROM nginx:1.25-alpine

# Remove default site
RUN rm -rf /usr/share/nginx/html/*

# Copy Vite build output
COPY --from=builder /app/dist /usr/share/nginx/html/

# Custom nginx.conf for SPA routing (all non-file routes → index.html)
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD wget -qO- http://127.0.0.1:3000/ || exit 1

ENTRYPOINT ["nginx", "-g", "daemon off;"]
```

#### `frontend/nginx.conf`

```nginx
server {
    listen 3000;
    root /usr/share/nginx/html;
    index index.html;

    # SPA: serve index.html for all non-file routes
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy API calls to backend
    location /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }

    # Proxy WebSocket to backend
    location /ws {
        proxy_pass http://backend:8000/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

### 5e.2 `compose.yaml` — Complete Service Definition

```yaml
# compose.yaml — self-hosted mindforge-local
# Usage:
#   docker compose up -d                    # production (all services)
#   docker compose --profile dev up -d     # + frontend dev watcher
#   docker compose --profile with-mcp up   # + MCP servers (Phase 4)
#   docker compose --profile test up -d    # integration test environment

services:

  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    profiles: [dev, prod, with-mcp, test]
    restart: unless-stopped
    volumes:
      - backend_data:/app/data          # PGLite DB + ChromaDB
      - ./logs/backend:/app/logs         # structured logs
    environment:
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - FERNET_KEY=${FERNET_KEY}
      - Temporal_HOST=temporal:7233
      - CHROMA_HOST=http://chroma:8000
      - OLLAMA_BASE_URL=http://ollama:11434   # local inference
    env_file: [.env, .env.local]         # .env.local is gitignored secrets
    depends_on:
      chroma:
        condition: service_healthy
      temporal:
        condition: service_healthy
      ollama:
        condition: service_healthy
    networks:
      - mindforge
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://127.0.0.1:8000/health').raise_for_status()"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
    profiles: [prod, test]
    restart: unless-stopped
    ports:
      - "127.0.0.1:3000:3000"           # localhost-only in prod
    depends_on:
      - backend
    networks:
      - mindforge
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:3000/"]
      interval: 30s
      timeout: 5s
      retries: 3

  frontend_dev:
    build:
      context: .
      dockerfile: frontend/Dockerfile.dev   # npm run dev (Vite HMR)
    profiles: [dev]
    restart: unless-stopped
    ports:
      - "127.0.0.1:3000:3000"
      - "127.0.0.1:5173:5173"               # Vite HMR
    depends_on:
      - backend
    networks:
      - mindforge

  chroma:
    image: chromadb/chroma:0.4.22
    profiles: [prod, dev, test]
    restart: unless-stopped
    volumes:
      - chroma_data:/chroma/chroma
    networks:
      - mindforge
    healthcheck:
      test: ["CMD", "python", "-c", "import httpx; httpx.get('http://127.0.0.1:8000/api/v1/heartbeat').raise_for_status()"]
      interval: 30s
      timeout: 10s
      retries: 3
    read_only: true                       # Section 3b.4: read-only where possible
    tmpfs:
      - /tmp                               # ChromaDB write-ahead log

  temporal:
    image: temporalio/auto-setup:1.22.0
    profiles: [prod, dev, test]
    restart: unless-stopped
    environment:
      - DB=sqlite                                           # dev: SQLite backend
      - DYNAMIC_CONFIG_FILE=/etc/temporal/dynamic_config.yaml
    volumes:
      - temporal_data:/var/temporal
      - ./config/temporal/dynamic_config.yaml:/etc/temporal/dynamic_config.yaml:ro
    networks:
      - mindforge
    healthcheck:
      test: ["CMD-SHELL", "temporal-operator health --address localhost:7233 || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s

  ollama:
    image: ollama/ollama:latest
    profiles: [prod, dev]          # test profile uses mock LLM — no Ollama needed
    restart: unless-stopped
    volumes:
      - ollama_data:/root/.ollama
    networks:
      - mindforge
    environment:
      - OLLAMA_HOST=0.0.0.0:11434
    # GPU support — automatically detected if nvidia-container-toolkit is installed
    # shm_size: 2g           # uncomment if running without GPU (reduces shm contention)
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:11434/api/tags || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 120s          # Ollama pulls model on first start if not cached

  # ── Phase 4 MCP servers (optional) ─────────────────────────────────────────
  mcp-github:
    image: ghcr.io/github/copilot-mcp-server:latest
    profiles: [with-mcp]
    restart: unless-stopped
    command: ["--token", "${GITHUB_TOKEN}"]
    networks:
      - mindforge
    depends_on:
      - backend

networks:
  mindforge:
    driver: bridge

volumes:
  backend_data:                          # PGLite + ChromaDB persistent storage
  chroma_data:                           # ChromaDB vector store
  temporal_data:                        # Temporal SQLite + workflow history
  ollama_data:                          # Ollama model cache
```

---

### 5e.3 Startup Ordering and Readiness

Docker Compose `depends_on` with `condition: service_healthy` blocks the backend until
ChromaDB, Temporal, and Ollama are genuinely ready, not just "container started":

```
docker compose up -d
# 1. chroma starts → health check passes → backend starts
# 2. temporal starts → health check passes → backend starts
# 3. ollama starts → health check passes → backend starts
# 4. backend /health returns 200 → frontend starts
# 5. frontend health check passes → all containers "healthy"
```

The `start_period` on each healthcheck gives slow-starting services (Ollama first-pull,
Temporal schema initialization) time to stabilize before the health check begins failing.

---

### 5e.4 Health Endpoints

```python
# backend/app/health.py
from fastapi import FastAPI
from contextlib import asynccontextmanager

app = FastAPI()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify all stores are reachable
    await verify_pglite()
    await verify_chroma()
    await verify_temporal()
    yield
    # Shutdown: drain Temporal workflows (see 5e.9)

@app.get("/health")
async def health():
    """Liveness probe — am I alive?"""
    return {"status": "ok"}

@app.get("/ready")
async def ready():
    """Readiness probe — am I ready to serve traffic?"""
    checks = {
        "pglite": await check_pglite(),
        "chroma": await check_chroma(),
        "temporal": await check_temporal(),
        "ollama": await check_ollama(),
    }
    all_healthy = all(checks.values())
    return {
        "status": "ready" if all_healthy else "not_ready",
        "checks": checks,
    }

# Wired into docker-compose healthcheck:
# HEALTHCHECK --interval=30s CMD python -c "import httpx; httpx.get('http://127.0.0.1:8000/health').raise_for_status()"
```

---

### 5e.5 Structured Logging

```python
# backend/app/logging_config.py
import structlog, logging, sys

def configure_logging(log_level: str = "INFO"):
    """JSON structured logs → stdout (captured by docker logs)."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.CallsiteParameterAdder(
                [structlog.processors.CallsiteParameter.MODULE,
                 structlog.processors.CallsiteParameter.FUNC_NAME]
            ),
            # Scrub sensitive fields before emission (Section 3b.6)
            scrub_processor,
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

# In backend/main.py:
configure_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = structlog.get_logger()
```

Log output example (machine-parseable):

```json
{"event": "llm_call_complete", "model": "google/gemini-2.0-flash", "tokens_in": 312, "tokens_out": 87, "latency_ms": 1240, "tier": "cloud_fast", "task_id": "abc123", "logger": "backend.agents.inference", "level": "info", "timestamp": "2026-05-13T02:15:00.123Z"}
```

**In `docker-compose.yaml`:**
```yaml
logging:
  driver: json-file           # docker logs --follow shows structured output
  options:
    max-size: "50m"
    max-file: "3"
```

---

### 5e.6 PGLite Migrations (Alembic)

Even though PGLite uses SQLite compatibility, schema evolution needs a migration tool:

```bash
# backend/db/migrations/
# 001_add_integration_permissions.sql
# 002_add_skill_version_index.sql
```

```python
# backend/db/migrate.py
import alembic.config
from alembic.runtime.migration import MigrationContext
from alembic import command

def run_migrations(connection):
    context = MigrationContext.configure(connection)
    command.upgrade(context, "head")

def get_current_revision(connection):
    context = MigrationContext.configure(connection)
    return context.get_current_revision()

# In CI: runs `alembic upgrade head` before starting the backend container
# docker compose run --rm backend alembic upgrade head
```

**Alembic ini (backend/alembic.ini):**
```ini
[alembic]
script_location = backend/db/migrations
prepend_sys_path = backend
sqlalchemy.url = sqlite+pglite:///app/data/mindforge.db
```

**CI integration (tests.yml):**
```yaml
- name: Run migrations
  run: |
    docker compose up -d chroma temporal
    docker compose run --rm backend alembic upgrade head
```

---

### 5e.7 Backup and Restore

```bash
#!/bin/bash
# scripts/backup.sh — run nightly via cron: 0 3 * * * /app/scripts/backup.sh

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/$TIMESTAMP"
CONTAINER="mindforge-backend-1"        # docker compose container name

mkdir -p "$DEST"

# PGLite (SQLite)
docker cp "$CONTAINER:/app/data/mindforge.db" "$DEST/mindforge.db"

# ChromaDB
docker cp "$CONTAINER:/app/data/chroma" "$DEST/chroma_data/"

# Skill YAML files
docker cp "$CONTAINER:/app/backend/skills" "$DEST/skills/"

# Fernet key (critical — without it backups are useless)
# The key is stored in .env; back it up separately from the DB
cp .env "$DEST/.env.encrypted"          # .env itself should be encrypted at rest

# Retention: keep 7 days
find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;

echo "Backup complete: $DEST"
```

```bash
#!/bin/bash
# scripts/restore.sh — run to restore from backup

set -euo pipefail

BACKUP_DIR="$1"                         # pass backup timestamp as argument
CONTAINER="mindforge-backend-1"

if [[ ! -d "$BACKUP_DIR" ]]; then
    echo "Backup directory not found: $BACKUP_DIR"
    exit 1
fi

# Stop services
docker compose stop

# Restore files
docker cp "$BACKUP_DIR/mindforge.db" "$CONTAINER:/app/data/mindforge.db"
docker cp "$BACKUP_DIR/chroma_data/." "$CONTAINER:/app/data/chroma/"

# Restart services
docker compose start

echo "Restore complete from $BACKUP_DIR"
```

**Cron schedule:**
```cron
0 3 * * * /app/scripts/backup.sh >> /var/log/mindforge_backup.log 2>&1
```

#### Data Portability (GDPR/CCPA) — `scripts/export.sh`

Required for GDPR Article 20 (right to data portability) and CCPA data disclosure requests.
Export all data for a given `PROJECT_ID` as a self-contained JSON archive:

```bash
#!/bin/bash
# scripts/export.sh — export all data for a project as JSON
# Usage: ./export.sh <PROJECT_ID> [output_dir]

set -euo pipefail
PROJECT_ID="${1:-default}"
OUTPUT_DIR="${2:-./exports}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
EXPORT_DIR="$OUTPUT_DIR/${PROJECT_ID}_${TIMESTAMP}"
mkdir -p "$EXPORT_DIR"

BACKUP_CONTAINER="mindforge-backend-1"
DB_PATH="/app/data/mindforge.db"
CHROMA_DATA="/app/data/chroma"

echo "Exporting project: $PROJECT_ID"

# 1. Export PGLite task history + integrations + skills
docker exec "$BACKUP_CONTAINER" python - << 'EOF'
import sqlite3, json, sys
project_id = sys.argv[1]
out_dir = sys.argv[2]
conn = sqlite3.connect(out_dir + "/_pglite_export.db")
conn.row_factory = sqlite3.Row
with open(out_dir + "/tasks.json", "w") as f:
    json.dump([dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE project_id = ?", (project_id,)
    )], f, indent=2, default=str)
with open(out_dir + "/integrations.json", "w") as f:
    json.dump([dict(r) for r in conn.execute(
        "SELECT * FROM integrations WHERE project_id = ?", (project_id,)
    )], f, indent=2, default=str)
with open(out_dir + "/skills.json", "w") as f:
    json.dump([dict(r) for r in conn.execute(
        "SELECT * FROM skills WHERE project_id = ?", (project_id,)
    )], f, indent=2, default=str)
EOF

# 2. Export ChromaDB semantic memories (metadata includes project_id)
docker exec "$BACKUP_CONTAINER" python - << 'EOF'
import chromadb, json, sys
project_id = sys.argv[1]
out_dir = sys.argv[2]
client = chromadb.PersistentClient(path=out_dir + "/_chroma_export")
collection = client.get_collection("memory")
results = collection.get(where={"project_id": project_id})
with open(out_dir + "/semantic_memory.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
EOF

# 3. Create manifest
cat > "$EXPORT_DIR/manifest.json" << 'EOF'
{
  "project_id": "%s",
  "exported_at": "%s",
  "files": ["tasks.json", "integrations.json", "skills.json", "semantic_memory.json"],
  "format": "MindForge local export v1"
}
EOF

echo "Export complete: $EXPORT_DIR"
echo "Total size: $(du -sh $EXPORT_DIR | cut -f1)"
```

#### Data Deletion (GDPR/CCPA) — `scripts/delete_project.sh`

Required for GDPR Article 17 (right to erasure / "right to be forgotten"). Permanently
deletes all data associated with a `PROJECT_ID`. This is irreversible — a confirmation
prompt is required before execution:

```bash
#!/bin/bash
# scripts/delete_project.sh — permanently delete all data for a project
# Usage: ./delete_project.sh <PROJECT_ID> [--confirm]

set -euo pipefail
PROJECT_ID="${1:-}"
CONFIRM="${2:-}"

if [[ "$CONFIRM" != "--confirm" ]]; then
    echo "ERROR: Confirmation required."
    echo "Usage: ./delete_project.sh <PROJECT_ID> --confirm"
    echo ""
    echo "This will PERMANENTLY DELETE all data for project: $PROJECT_ID"
    echo "  - All task history from PGLite"
    echo "  - All semantic memories from ChromaDB"
    echo "  - All integration credentials"
    echo "  - All skill configurations"
    echo ""
    echo "This action CANNOT be undone."
    exit 1
fi

BACKUP_CONTAINER="mindforge-backend-1"

echo "DELETING project: $PROJECT_ID"
echo "  Deleting PGLite records..."
docker exec "$BACKUP_CONTAINER" python - << 'EOF'
import sqlite3, sys
project_id = sys.argv[1]
conn = sqlite3.connect("/app/data/mindforge.db")
for table in ["tasks", "integrations", "skills", "episodic_memory"]:
    conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
conn.commit()
print(f"  PGLite records deleted from {len(conn.execute(f'SELECT 1 FROM tasks WHERE project_id = ?', (project_id,)).fetchall())} remaining tasks")
EOF

echo "  Deleting ChromaDB semantic memories..."
docker exec "$BACKUP_CONTAINER" python - << 'EOF'
import chromadb, sys
project_id = sys.argv[1]
client = chromadb.PersistentClient(path="/app/data/chroma")
collection = client.get_collection("memory")
ids_to_del = [m["id"] for m in collection.get(where={"project_id": project_id})["metadatas"] or [] if m.get("project_id") == project_id]
if ids_to_del:
    collection.delete(ids=ids_to_del)
    print(f"  Deleted {len(ids_to_del)} ChromaDB vectors")
else:
    print("  No ChromaDB vectors found for project")
EOF

echo ""
echo "Deletion complete for project: $PROJECT_ID"
echo "NOTE: Encrypted integration tokens in the Fernet key store are now orphaned."
echo "      They are cryptographically inaccessible but the ciphertext blobs remain."
```

**Important:** `delete_project.sh` clears the data but does NOT zero-fill the database
pages or wipe the Fernet key store. For maximum privacy, run ` VACUUM` on the PGLite
database after deletion (`docker exec $BACKUP_CONTAINER python -c "import sqlite3; ..."`).
Full cryptographic erasure requires regenerating `FERNET_KEY` and re-encrypting all
remaining tokens (see Section 3b.7 Key Rotation Procedure).

---

### 5e.8 Release Management

#### Version file

```toml
# backend/VERSION
version = "1.0.0-alpha"
commit  = "{{ .Commit }}"      # injected at build time by goreleater or docker build-arg
```

#### `CHANGELOG.md` — maintained with conventional commits

```markdown
# Changelog

## [1.0.0-alpha] — 2026-05-13

### Added
- Hybrid inference router with local Ollama + cloud OpenRouter tiers (5.7.1)
- Unified tool interface and ToolRegistry (5.7.7)
- Dockerfiles for backend and frontend (5e.1)
- Complete compose.yaml with health checks and profiles (5e.2)
- Structured logging with structlog (5e.5)
- Health endpoints `/health` and `/ready` (5e.4)
- Backup/restore scripts (5e.7)
- Alembic migration setup for PGLite (5e.6)

### Changed
- `schedule/temporal_app.py` (was `celery_app.py`) — Temporal migration

### Security
- PyYAML SafeLoader enforced on all skill YAML (3b.1)
- Fernet key rotation procedure documented (3b.7)
- Non-root user in Dockerfiles (3b.4)
```

#### Git tag and release CI

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          # Extract VERSION from file for image tag
      - name: Set version
        run: echo "VERSION=${GITHUB_REF#refs/tags/v}" >> $GITHUB_ENV

      - name: Build and push backend image
        run: |
          docker compose build backend
          docker compose push ghcr.io/${{ github.repository }}/backend:${{ env.VERSION }}

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v1
        with:
          files: CHANGELOG.md
```

---

### 5e.9 Graceful Shutdown

When `docker stop` is called, the backend must drain in-flight Temporal workflows before exiting:

```python
# backend/app/lifespan.py (in main.py)
from contextlib import asynccontextmanager

async def lifespan(app: FastAPI):
    # Startup — handled by /ready health check dependencies
    yield

    # Shutdown — drain Temporal workflows
    logger.info("shutdown_initiated")
    temporal_client = await get_temporal_client()

    # Stop accepting new tasks
    await temporal_client.worker.stop()
    logger.info("temporal_worker_stopped")

    # Wait for in-flight workflows (max 30s, then force-exit)
    done, pending = await asyncio.wait_for(
        temporal_client.workflow_sutdown(wait_seconds=30),
        timeout=30
    )
    logger.info("workflows_drained", completed=len(done), pending=len(pending))

    logger.info("shutdown_complete")
    raise SystemExit(0)
```

**Docker stop timeout:** `docker compose stop` sends SIGTERM; Docker waits
`shutdown_grace_period: 30s` before SIGKILL. Set this in compose:

```yaml
backend:
  stop_grace_period: 30s
```

---

### 5e.10 Rollback Procedure

A rollback restores the previous git tag and restarts services:

```bash
# Rollback to the previous release tag
git checkout v1.2.1
docker compose build backend
docker compose up -d backend

# Verify
docker compose logs --tail=20 backend
curl -s http://localhost:8000/health
```

The key constraint: **PGLite schema is backward-compatible forward only.**
Never rollback to a schema version that doesn't understand the current data.
Use `alembic history` to confirm migration integrity before rolling forward again.

---

### 5e.11 Local Development Workflow

```makefile
# Makefile — developer shortcuts (run: make <target>)

.PHONY: help setup dev test lint fmt clean logs

help:
	@grep -E '^[a-zA-Z_-]+:' Makefile | sed 's/:.*//'

setup:                          # First-time setup
	python -m venv .venv && source .venv/bin/activate && pip install -r backend/requirements.dev.txt
	cd frontend && npm ci
	cp .env.example .env
	docker compose up -d chroma temporal ollama
	@echo "Open http://localhost:8000/docs to verify API"

dev:                            # Start development environment
	docker compose --profile dev up -d
	cd frontend && npm run dev &
	source .venv/bin/activate && uvicorn backend.main:app --reload --port 8000

test:                           # Run test suite
	docker compose --profile test up -d
	docker compose exec backend pytest backend/tests/ -q --tb=short

lint:                           # Lint + type-check
	ruff check backend/
	mypy backend/ --ignore-missing-imports
	cd frontend && npm run lint

fmt:                            # Format code
	ruff format backend/
	cd frontend && npm run format

logs:                           # Tail backend logs
	docker compose logs -f backend

clean:                          # Remove containers + volumes
	docker compose down -v --remove-orphans
	rm -rf frontend/dist .venv
```

**`CONTRIBUTING.md`** (one page):

```markdown
# Contributing to mindforge-local

## Prerequisites
- Docker + Docker Compose v2
- Python 3.12
- Node 20
- GPU (optional — enables local Ollama inference)

## Setup
```bash
cp .env.example .env          # fill in OPENROUTER_API_KEY and FERNET_KEY
make setup
make dev
```

## Running Tests
```bash
make test          # full integration suite
```

## Adding a Skill
1. Create `backend/skills/skills/my-skill.yaml` from the schema (Section 2.3)
2. Run `python -m backend.skills.registry` to validate
3. Add a test in `backend/tests/unit/test_skill_graph_validation.py`

## Adding an Integration
1. Implement `BaseTool` in `backend/tools/<name>.py` (Section 5.7.7)
2. Register in `backend/tools/registry.py`
3. Add fixtures in `backend/tests/fixtures/integrations/`
```

---

### 5e.12 Service Table — Ports, Profiles, Dependencies

| Service | Port | Profiles | Depends on | Purpose |
|---|---|---|---|---|
| backend (prod) | 8000 | prod | chroma, temporal, ollama | FastAPI server |
| backend_dev | 8000 | dev | chroma, temporal, ollama | FastAPI with --reload |
| frontend (prod) | 3000 | prod | backend | Nginx + SPA |
| frontend_dev | 3000, 5173 | dev | backend_dev | Vite HMR dev |
| chroma | 8000 (internal) | prod, dev, test | — | Vector store |
| temporal | 7233 (internal) | prod, dev, test | — | Workflow engine |
| temporal_web | 8080 (internal) | prod, dev | temporal | Temporal web UI |
| ollama | 11434 (internal) | prod, dev | — | Local LLM inference |
| mcp-github | — | with-mcp | backend | GitHub MCP server |
| test (runner) | — | test | chroma, temporal | Pytest via compose |

---

### 5e.13 CI — Complete Pipeline

Building on Section 5.6.6, the full CI pipeline covers build, test, and release:

```yaml
# .github/workflows/ci.yml  (extends tests.yml from 5.6.6)
name: CI

on:
  push:
    branches: [main, fix/**, feat/**]
  pull_request:
    branches: [main]

jobs:
  lint-and-typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ruff mypy
      - run: ruff check backend/ --fix
      - run: mypy backend/ --ignore-missing-imports

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e "backend[test]"
      - run: docker compose --profile test up -d
      - run: sleep 10  # wait for services
      - run: pytest backend/tests/unit -q --tb=short
      - run: pytest backend/tests/integration -q --tb=short

  build-images:
    runs-on: ubuntu-latest
    needs: [lint-and-typecheck, test]
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build and push
        run: |
          VERSION=$(date +%Y%m%d%H%M)
          docker compose build backend frontend
          docker compose push ghcr.io/${{ github.repository }}/backend:$VERSION
          docker compose push ghcr.io/${{ github.repository }}/frontend:$VERSION

  release:
    runs-on: ubuntu-latest
    needs: [build-images]
    if: startsWith(github.ref, 'refs/tags/v')
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: softprops/action-gh-release@v1
        with:
          files: CHANGELOG.md
```

---

## 5.9 Glossary

**Architectural terms:**

| Term | Definition |
|---|---|
| **Episodic Memory** | Structured records of completed tasks, stored in PGLite. Enables the agent to answer "what did we do last week?" — not semantic facts. |
| **Semantic Memory** | Unstructured knowledge embedded in ChromaDB. Enables relevance-based retrieval — the agent finds "things related to Acme Corp" without explicit recall. |
| **Procedural Memory** | The skill registry (YAML files + execution patterns). Not human-readable memory — the agent's "how to do X." |
| **HMAC** | Hash-based Message Authentication Code. Used to verify that semantic memory entries written to ChromaDB were created by this system, not injected by an attacker. |
| **RRF** | Reciprocal Rank Fusion. A rank aggregation formula (k=60) used to combine BM25 keyword scores and vector similarity scores in the hybrid retriever. |
| **BM25** | Best Matching 25 — a probabilistic keyword retrieval algorithm. Complements vector similarity which misses exact matches. |
| **HyDE** | Hypothetical Document Embeddings — a retrieval technique where a small LLM generates a hypothetical answer, then both the query and the hypothetical are embedded to improve recall. |
| **circuit breaker** | A pattern that "breaks" a circuit (stops calling a model) after N consecutive failures, preventing cascade failures and wasted retries. |

**Agent roles:**

| Term | Definition |
|---|---|
| **COO** | Chief Operating Officer agent — routing, task orchestration, escalation decisions |
| **CMO** | Chief Marketing Officer agent — writing, content, social, communications |
| **Researcher** | Research agent — analysis, competitive intelligence, information gathering |
| **Engineer** | Engineer agent — code, GitHub, technical tasks |

**Workflow terms:**

| Term | Definition |
|---|---|
| **Draft-first** | The agent produces a draft output (not sent to external systems) for human review before any execution proceeds. |
| **Approval gate** | A skill graph node that pauses execution pending human approval. Encoded as a state transition to `draft` in the task state machine. |
| **Clarification request** | A synchronous pause in the LangGraph supervisor where the agent surfaces a specific question to the user before proceeding with an ambiguous task. |
| **Escalation** | A skill graph node that routes to the COO with a notification when retry budgets are exhausted or a draft times out. |

**Infrastructure terms:**

| Term | Definition |
|---|---|
| **PGLite** | Postgres-compatible SQLite. A single-file SQLite database with a Postgres wire protocol adapter, used for structured relational data (tasks, skills, profiles). |
| **ChromaDB** | An open-source vector database used for semantic memory storage and similarity search. |
| **Temporal** | A workflow orchestration engine that durably persists workflow state across process restarts. Replaces Celery for long-running proactive tasks. |
| **Fernet** | A symmetric encryption scheme (AES-128-CBC + HMAC) from the `cryptography` library. Used for encrypting sensitive fields at rest in PGLite. |

---

## 5.10 Version Strategy

MindForge uses Semantic Versioning (SemVer). The API surface, skill YAML schema, and
memory format are all considered "public contracts" — changes that break any of them
trigger a minor version bump even before v1.0.

### Version Format

```
MAJOR.MINOR.PRE+METADATA
Examples: 0.3.0-alpha, 0.4.0-beta+20260513, 1.0.0
```

| Component | Meaning |
|---|---|
| `MAJOR` | Breaking change to any public API, skill YAML schema, or memory format. Post-1.0 only. |
| `MINOR` | New capability; backward-compatible change. Phase exits always bump minor. |
| `PATCH` | Bug fix, no new capability. |
| `PRE` | Pre-release tag: `alpha`, `beta`, `rc`. Alpha = internal testing; Beta = external-ready; RC = release candidate. |
| `+METADATA` | Optional build timestamp (ISO date). Included in Docker image tags. |

### Pre-1.0 Policy

Before v1.0, the `MAJOR` version stays at 0. Any backward-compatible change bumps `MINOR`.
Breaking changes before v1.0 also bump `MINOR` (not `MAJOR`) because the API is explicitly
unstable. Only promote to v1.0 when:

- All four phases are shipped
- Skill YAML schema is stable (no planned structural changes)
- Memory format has a migration path documented
- Phase exit criteria have been verified by automated tests

### Version Bump Map

| Event | Version Change | Rationale |
|---|---|---|
| Phase 1 shipped (core loop functional) | `0.1.0` → `0.2.0` | Minor: new capability |
| Phase 2 shipped (multi-agent + skills) | `0.2.0` → `0.3.0` | Minor |
| Phase 3 shipped (24/7 proactive) | `0.3.0` → `0.4.0` | Minor |
| Phase 4 shipped (full integrations) | `0.4.0` → `1.0.0-alpha` | First stable API surface |
| Bug fix | `0.x.y` → `0.x.y+1` | Patch |
| Breaking skill YAML schema change | `0.x` → `0.x+1.0` | Minor (pre-1.0 rule) |
| Promote alpha → beta | `0.4.0-alpha` → `0.4.0-beta` | Pre-release progression |
| Promote beta → stable | `0.4.0-beta` → `1.0.0` | Major promotion |

### Git Tag Convention

```
v<MAJOR>.<MINOR>.<PATCH>[<-PRE>]
Examples: v0.2.0, v0.3.0-alpha, v1.0.0
```

The `v` prefix distinguishes tags from branch names. Each phase exit must include a tag:

```bash
# Phase 2 exit
git tag -a v0.2.0 -m "Phase 2 complete: multi-agent + skills"
git push origin v0.2.0
```

### Where version is stored

| Location | What it stores |
|---|---|
| `backend/VERSION` | Exact version string (e.g., `0.3.0-alpha`) |
| `pyproject.toml` | `tool.poetry.version` or `setuptools version` |
| `package.json` | Frontend version (mirrors backend) |
| Docker image tag | Includes `+METADATA` if built from CI: `ghcr.io/user/mindforge/backend:0.3.0+20260513` |

### Deprecation Policy

Before removing any feature, skill YAML field, or API endpoint:

1. Announce deprecation in `CHANGELOG.md` with the version that introduces it
2. Continue supporting the deprecated feature for at least 2 minor versions
3. Document the removal in the migration guide

---

## 5.11 Community & Contributor Guidance

This section covers everything a human or AI contributor needs to navigate, understand, and
contribute to MindForge. It is the single source of truth for contributor-facing documentation.

---

### 5.11.1 README.md

This is the public face of the repository. It lives at `~/mindforge/README.md` (not inside
SPEC.md). Generate it with:

```markdown
# MindForge

> Your sovereign AI operating system. Multi-agent team, persistent memory,
> draft-first workflow, 24/7 proactive execution — all self-hosted.

[![CI](https://github.com/<user>/mindforge/actions/workflows/ci.yml/badge.svg)](https://github.com/<user>/mindforge/actions)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)

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
git clone https://github.com/<user>/mindforge.git
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
```

---

### 5.11.2 LICENSE — AGPL-3.0 Rationale

**Recommended license: GNU Affero General Public License v3.0 (AGPL-3.0)**

This project runs autonomous agents that take real actions (sending email, creating GitHub PRs,
executing Stripe refunds). AGPL-3.0 is appropriate because:

1. **Network interaction trigger**: AGPL requires that if this software is used over a
   network (including localhost), the source must be made available. A self-hosted AI agent
   platform qualifies.
2. **Autonomous action amplification**: Unlike a passive web app, every commit/PR/email
   this system creates has real-world consequences. Contributors must be aware that
   modifications could affect systems beyond this codebase.
3. **Derivative work clarity**: Skills (YAML files) define agent behavior but are data,
   not code — they do not trigger copyleft. Only modifications to the agent runtime
   and orchestration code trigger the AGPL requirement.

If AGPL is too strong, Apache-2.0 is the fallback — but it does not cover the autonomous
action dimension. MIT and BSD are explicitly insufficient for a system that modifies
external services on the user's behalf.

```txt
# LICENSE — place at ~/mindforge/LICENSE

GNU AFFERO GENERAL PUBLIC LICENSE
Version 3, 19 November 2007
```

Full text: https://www.gnu.org/licenses/agpl-3.0.en.html

---

### 5.11.3 CODE_OF_CONDUCT.md

**Contributor Covenant Code of Conduct 2.1**

```markdown
# Code of Conduct

## Our Pledge

We as members, contributors, and leaders pledge to make participation in MindForge
a harassment-free experience for everyone. We pledge to act and interact in ways
that contribute to an open, welcoming, diverse, and healthy community.

## Our Standards

Examples of behavior that contributes to a positive environment:
- Using welcoming and inclusive language
- Being respectful of differing viewpoints and experiences
- Gracefully accepting constructive criticism
- Focusing on what is best for the community and system users

Examples of unacceptable behavior:
- Publishing others' private information without permission
- Autonomous actions that bypass human approval gates
- Introducing untrusted skills or integrations without disclosure

## Enforcement

Instances of abusive, harassing, or otherwise unacceptable behavior may be reported
to the maintainers at <owner-email>. All complaints will be reviewed and investigated
and will result in a response that is deemed necessary and appropriate.

##特别说明 (AI Agent Note)

MindForge agents must not:
- Execute actions outside approval gates without explicit user consent
- Share memory context across projects without user authorization
- Modify or delete data outside the designated project scope
- Connect to integrations the user has not explicitly approved
```

---

### 5.11.4 SECURITY.md

```markdown
# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.4.x   | :white_check_mark: |
| < 0.4   | :x:                |

## Reporting a Vulnerability

Please report security vulnerabilities to <owner-email> with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested mitigations

Response timeline: acknowledgment within 48h, fix within 14 days for critical issues.

## Security Model

MindForge is a single-user self-hosted system. The security boundary is the
local machine and the OS user account running the containers. Assume that any
process running under the same user account has full access to all credentials
and data.

Key security boundaries:
- Fernet encryption key (`.env`) — protects sensitive fields at rest in PGLite
- HMAC signatures on semantic memory writes — prevent injection attacks
- `yaml.safe_load()` on all skill YAML — prevents RCE via deserialization
- No exposure of the API server outside localhost
```

---

### 5.11.5 agents.md — AI Agent Navigation Guide

GitHub's `agents.md` feature allows AI coding agents (Claude Code, Copilot, Codex, etc.)
to understand a repository on first contact. This is the definitive navigation document
for AI agents working on MindForge.

```markdown
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
| `Temporal_HOST` | Auto | Workflow engine |
| `OLLAMA_BASE_URL` | No | Local inference (optional) |

## Contact

For questions about this codebase: open an issue or contact the maintainer directly.
```

---

### 5.11.6 Issue Templates

#### `/.github/ISSUE_TEMPLATE/bug_report.md`

```markdown
---
name: Bug report
about: Report something that is broken
title: "[Bug] "
labels: bug
assignees: ''
---

## Bug Description
A clear description of the bug. What did you expect to happen, and what
actually happened?

## Steps to Reproduce
1.
2.
3.

## Environment
- MindForge version: (run `cat backend/VERSION`)
- Docker version:
- Python version (if running without Docker):
- Deployment: (local / VPS / etc.)

## Relevant Log Output
Paste any error messages, tracebacks, or log lines here.
Wrap in ``` for formatting.

## Expected Behavior
What should happen.

## Actual Behavior
What happens instead.

## Suggested Fix
If you have an idea of what is causing this, describe it here.
```

#### `/.github/ISSUE_TEMPLATE/feature_request.md`

```markdown
---
name: Feature request
about: Propose a new capability
title: "[Feature] "
labels: enhancement
assignees: ''
---

## Use Case
Who would use this feature and why? What problem does it solve?

## Proposed Solution
Describe the proposed implementation.

## Alternatives Considered
What else did you consider? Why did you reject those approaches?

## Phase Alignment
Which implementation phase does this belong to? (Check SPEC.md Section 5.1–5.4)
- [ ] Phase 1 — Core Loop
- [ ] Phase 2 — Multi-Agent + Skills
- [ ] Phase 3 — Proactive Execution
- [ ] Phase 4 — Composio + Production

## Breaking Change
Does this require a change to the skill YAML schema, API surface, or memory format?
If yes, it is a minor version bump (see SPEC.md Section 5.10).

## References
Link to any relevant issues, discussions, or documentation.
```

#### `/.github/ISSUE_TEMPLATE/skill_submission.md`

```markdown
---
name: Skill submission
about: Submit a new YAML skill for review
title: "[Skill] "
labels: skill
assignees: ''
---

## Skill Name
A short, descriptive name. e.g., `linear-issue-creator`

## Integration Requirements
Which integrations does this skill need?
- [ ] GitHub
- [ ] Linear
- [ ] Gmail
- [ ] Stripe
- [ ] Other: ________

## Approval Gate
Does this skill perform external actions (send email, create PR, issue refund)?
- [ ] Yes — all external actions are behind approval gates
- [ ] No — read/query only

## Skill YAML
Paste the full skill YAML below. See SPEC.md Section 2.3 for the schema.

```yaml
# Paste skill YAML here
```

## Test Case
Describe a task that this skill should be able to complete. What is the input?
What is the expected output?

## Compatibility
- MindForge version tested with:
- Phase: 1 / 2 / 3 / 4
```

#### `/.github/ISSUE_TEMPLATE/integration_request.md`

```markdown
---
name: Integration request
about: Request a new integration
title: "[Integration] "
labels: integration
assignees: ''
---

## Target Service
Name of the service (e.g., Notion, Airtable, HubSpot)

## Auth Method
How does the integration authenticate?
- [ ] API key
- [ ] OAuth 2.0
- [ ] Personal token
- [ ] Other: ________

## Required Actions
What actions should the agent be able to perform with this integration?
(e.g., "Create a Notion page", "Update a contact in HubSpot")

## Risk Assessment
Rate the risk of this integration:
- **Low** — read-only query (e.g., fetching data)
- **Medium** — creates or modifies data within existing records
- **High** — deletes data, sends communications, or makes financial changes

## Phase Alignment
- [ ] Phase 1 — Core Loop (direct API only)
- [ ] Phase 2 — Multi-Agent + Skills
- [ ] Phase 4 — Composio (for 864+ integration library)
```

#### `/.github/ISSUE_TEMPLATE/good_first_issue.md`

```markdown
---
name: Good first issue
about: A task suitable for new contributors
title: "[Good First Issue] "
labels: good first issue
assignees: ''
---

## Description
A clear, self-contained task that a new contributor can complete in
1–3 hours without needing deep context.

## Context
Why does this need to be done? What will break or improve if it's done?

## Tasks
- [ ] Task 1
- [ ] Task 2
- [ ] Task 3

## Expected Outcome
What does "done" look like? What should be tested?

## References
- Relevant SPEC.md section: Section __.__
- Related issue/discussion: #__
```

---

### 5.11.7 PR Template

```markdown
<!-- /.github/PULL_REQUEST_TEMPLATE.md -->

## Description
Brief description of what this PR does and why.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Skill addition
- [ ] Integration addition
- [ ] Documentation
- [ ] Refactor
- [ ] Test improvement

## Phase Alignment
- [ ] Phase 1 — Core Loop
- [ ] Phase 2 — Multi-Agent + Skills
- [ ] Phase 3 — Proactive Execution
- [ ] Phase 4 — Composio + Production
- [ ] Cross-phase (affects all phases)

## Breaking Change
Does this PR change the skill YAML schema, API surface, or memory format?
- [ ] Yes — minor version bump required (see Section 5.10)
- [ ] No

## Testing
What testing was done?

- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual verification: _______________

## Checklist

- [ ] Code follows the style guidelines (run `make lint`)
- [ ] Self-review completed
- [ ] Comments added for complex logic
- [ ] All new integrations documented in `SECURITY.md`
- [ ] All new environment variables documented in `.env.example`
- [ ] If adding a skill: validated with `python -m backend.skills.registry validate`
- [ ] If changing memory layer: HMAC verification passes
```

---

### 5.11.8 CONTRIBUTING.md — Root Document

This supersedes the CONTRIBUTING block in Section 5e.11. It lives at `~/mindforge/CONTRIBUTING.md`.

```markdown
# Contributing to MindForge

Thank you for contributing to MindForge. This document covers everything you need
to know to get your first contribution in.

## Code of Conduct

By participating, you agree to uphold our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

### First-Time Setup

```bash
git clone https://github.com/<user>/mindforge.git
cd mindforge
cp .env.example .env       # fill in OPENROUTER_API_KEY and FERNET_KEY
make setup                 # Python venv + frontend deps + Docker containers
make dev                   # start dev services with hot reload
make test                  # verify full test suite passes
```

### Reading the Spec

Before making any non-trivial change, read the relevant section of [SPEC.md](SPEC.md):
- Skill changes → Section 2.3
- Memory changes → Section 2.2
- Agent changes → Section 2.1
- UI changes → Section 2.7
- Infrastructure changes → Section 5.8

## Branching Strategy

| Branch | Purpose |
|---|---|
| `main` | Stable, always deployable |
| `feat/<name>` | New features |
| `fix/<name>` | Bug fixes |
| `skill/<name>` | Skill additions |
| `integration/<name>` | Integration additions |
| `docs/<name>` | Documentation only |

Branch from `main`, target `main`.

## Commit Message Format

Conventional Commits (required for all commits):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

| Type | When to use |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `test` | Test additions or fixes |
| `refactor` | Code restructure, no behavior change |
| `perf` | Performance improvement |
| `security` | Security fix or hardening |
| `chore` | Build, deps, CI |

Examples:
```
feat(skills): add linear-issue-creator skill
fix(memory): correct HMAC verification on semantic memory reads
docs(api): document /ready endpoint response shape
test(retriever): add hybrid search RRF unit test
```

## Running the Test Suite

```bash
make test              # full suite (unit + integration)
make lint              # ruff check + mypy type check
make fmt               # auto-format code

# Run only a subset
pytest backend/tests/unit -q
pytest backend/tests/unit/test_skill_graph_validation.py -q
```

## Adding a Skill

1. Create `backend/skills/skills/my-skill.yaml` (see SPEC.md Section 2.3 for schema)
2. Validate: `python -m backend.skills.registry validate backend/skills/skills/my-skill.yaml`
3. Add test in `backend/tests/unit/test_skill_graph_validation.py`
4. Add integration test in `backend/tests/integration/test_skill_execution.py`
5. Submit PR with `skill/<name>` branch

## Adding an Integration

1. Implement `BaseTool` in `backend/tools/<name>.py` (see SPEC.md Section 5.7.7)
2. Register in `backend/tools/registry.py`
3. Add fixtures in `backend/tests/fixtures/integrations/`
4. Add to `INTEGRATION_RATE_LIMITS` (SPEC.md Section 5.5)
5. Document auth method in `SECURITY.md`
6. Submit PR with `integration/<name>` branch

## Phase Contribution Process

MindForge is built in 4 phases (SPEC.md Sections 5.1–5.4). Contributions must
state which phase they target. Contributions requiring Phase 4 infrastructure
(Composio, full OAuth) will be accepted as PRs but held for the Phase 4 merge.

## Pull Request Review Criteria

PRs are reviewed for:
1. Correctness — does it do what it says?
2. Security — no credential leakage, no approval gate bypass, safe YAML loading
3. Testing — new code has tests
4. Spec compliance — changes are reflected in SPEC.md
5. Breaking change disclosure — skill schema or API changes flagged

Review timeline: acknowledgment within 48h, decision within 7 days.

## Labels

| Label | Meaning |
|---|---|
| `bug` | Confirmed bug |
| `enhancement` | New feature or improvement |
| `skill` | Skill-related change |
| `integration` | Integration-related change |
| `good first issue` | Suitable for new contributors |
| `security` | Security-sensitive change |
| `breaking` | Requires version bump |
| `docs` | Documentation only |
```

---

### 5.11.9 GOVERNANCE.md — Summary

Full document at `~/mindforge/GOVERNANCE.md`.

```markdown
# Governance

## Project Owner
Alex — owns the project direction, phase scope, and final merge authority.

## Decision Making
Benevolent dictator model. The owner makes final decisions after seeking
community input. Consensus is sought but not required for routine changes.

## Maintainer Criteria
Maintainers are contributors who have:
- Submitted 3+ merged PRs
- Demonstrated understanding of the spec
- Responded to issues within 48h

## Phase Exit Criteria
Each phase exit (SPEC.md Section 5.1–5.4) requires:
1. All automated tests passing
2. Manual verification of phase exit criteria
3. Version bump git tag
4. CHANGELOG.md entry

## Skill Marketplace Policy
Phase 4 includes a skill marketplace. Submitted skills must:
- Pass `yaml.safe_load()` validation
- Have no external actions without approval gates
- Include a test case
- Be licensed under AGPL-3.0 or compatible
```

---

### 5.11.10 CODEOWNERS

```markdown
# /.github/CODEOWNERS

# Default owner
*   @<github-handle>

# Phase-specific ownership
/backend/agents/            @<github-handle>
/backend/memory/           @<github-handle>
/backend/skills/           @<github-handle>
/backend/tools/             @<github-handle>
/backend/scheduler/         @<github-handle>
/frontend/                  @<github-handle>
/.github/                   @<github-handle>
```

---

### 5.11.11 Community SLA

| Commitment | Target |
|---|---|
| Issue acknowledgment | Within 48h |
| PR initial review | Within 7 days |
| Bug fix (confirmed) | Within 14 days |
| Security disclosure response | Within 48h |
| Good first issue guidance | Within 7 days |

**Contribution acceptance:** All contributions are welcome. Merging is not
guaranteed — contributions must pass review criteria (Section 5.11.8) and
align with the phase scope. Low-quality PRs (missing tests, no spec update,
breaking changes without disclosure) will be closed with guidance.

**Phase gates:** Phase 4 infrastructure contributions (Composio, full OAuth)
will be accepted as PRs but not merged until Phase 4 begins. Label with
`Phase 4` and `on-hold` to signal this.

---

### 5.11.12 Legal & Intellectual Property Considerations

> **⚠️ Disclaimer:** This section documents legal and IP considerations for informational
> purposes only. It does not constitute legal advice. Consult a qualified attorney before
> making legal decisions about trademark, licensing, or data protection.

---

#### Trademark — "MindForge" Name

**Current status:** The name `MindForge` was chosen to avoid confusion with `SureThing` /
`surething.io`. It is not yet registered as a trademark.

**Recommended actions:**
1. Conduct a clearance search before committing to the name:
   - USPTO TESS (uspto.gov/tess) — US federal trademarks
   - EUIPO eSearch — EU trademarks
   - GitHub search for existing projects with the same name
   - Google search for "MindForge AI" / "MindForge agent"
2. If the name is clear, file a US Trademark Application (TEAS Plus, ~$250) under
   IC 042 (computer services) before public announcement
3. Add `™` symbol to the name in the README and docs once filed
4. If the name is already taken, fallback candidates in priority order:
   - `ForgeMind`
   - `BrainForge`
   - `AgentForge`
   - `PlanCraft`

**Do not use:** Any name containing "SureThing" or "ST" — risk of confusion and trademark infringement.

---

#### License — AGPL-3.0

**Chosen because:** MindForge makes network calls to external LLM APIs (OpenRouter) and
operates autonomous agents that take actions on behalf of users. AGPL-3.0 is appropriate
because:
- The "network use" provision of AGPL triggers when a user interacts with MindForge over
  a network — anyone who modifies the server component must disclose their modifications
- This protects the open-source nature of the core agent system even when deployed as
  a service
- It is the strongest copyleft license that is still compatible with the Python ecosystem
  (LangGraph, Temporal, etc. are all Apache 2.0 or permissive)

**What AGPL-3.0 requires of contributors:**
- If you modify MindForge's core server code and distribute it (including hosting it as
  a service), you must disclose your modifications under AGPL-3.0
- Skill YAML files are data (not code) and are NOT subject to copyleft
- Integration configurations and `.env` templates are not derivative works

**Compatibility notes:**
| License | Compatible with AGPL-3.0? | Notes |
|---|---|---|
| Apache 2.0 | ✅ Yes | Can use in AGPL project |
| MIT | ✅ Yes | Can use in AGPL project |
| BSD | ✅ Yes | Can use in AGPL project |
| GPL 2.0 / 3.0 | ⚠️ Incompatible | Cannot link into AGPL project |
| Proprietary | ❌ No | Cannot combine without AGPL-compatible rewrite |

**If AGPL is too restrictive**, switch to **Apache 2.0** — this removes the network use
trigger but also removes the autonomous-agent protection. Do this only if MindForge will
never be distributed as a service or if the autonomous-agent concern is addressed
through other means (e.g., a commercial license).

---

#### Data Protection — Local-Only Does Not Mean No Obligations

Even though MindForge is a local-only system with no network-exposed services, it still
processes personal data (emails, calendar events, potentially financial data from Stripe).
This creates potential obligations:

| Concern | Risk level | Mitigation |
|---|---|---|
| GDPR (EU residents) | Medium | If you process data of EU users, you are subject to GDPR even for local processing. Provide a data export script (`scripts/export.sh`) |
| CCPA (California residents) | Low-Medium | Same logic as GDPR; data export feature covers this |
| Data backup | High | Encrypted backups (Section 5e.7) protect stored personal data |
| Right to deletion | Low-Medium | `scripts/delete_project.sh` that purges PGLite + ChromaDB for a project_id covers this |
| Privacy policy | Low | A local-only personal tool does not typically require a public privacy policy; consult legal counsel if you distribute the app |

**Required for GDPR/CCPA minimum compliance:**
1. `scripts/export.sh` — export all data for a given project_id as JSON
2. `scripts/delete_project.sh` — permanently delete all data for a project_id
3. A minimal `PRIVACY.md` document stating: what data is stored, how long it is retained,
   and how to request deletion

---

#### OpenRouter API — Data Processing Agreement

OpenRouter processes LLM prompts containing user data (task descriptions, retrieved memory,
integration responses) when you route requests through their API. Key points:

- OpenRouter's Terms of Service govern what they can do with your data
- Their Privacy Policy describes data retention (typically 30 days forprompts/responses)
- For GDPR compliance: OpenRouter is a "data processor" — you need a DPA with them
  (available on request via their support)
- For maximum data privacy: use Ollama (fully local, no data leaves the machine)

---

#### Composio (Phase 4) — Third-Party API Risk

Composio acts as an intermediary for 864+ integrations. Each integration has its own
terms of service and data handling practices. Phase 4 introduces:

- **GitHub:** OAuth tokens stored via Composio; GitHub's terms prohibit automated
  scraping and impose rate limits
- **Stripe:** Composio accesses payment data; PCI-DSS compliance is Composio's
  responsibility (they are PCI-DSS compliant), not MindForge's
- **Gmail/Google Workspace:** Google's API terms restrict automated access to Gmail;
  OAuth scopes must be minimally scoped to `gmail.readonly` or `gmail.send`

**Recommendation:** Before Phase 4, review Composio's current terms and each
integration's data handling policy. Document any restrictions in `SECURITY.md`.

---

#### Autonomous Agent Liability — Out of Scope but Noted

MindForge's agents take actions: sending emails, creating GitHub PRs, posting to Slack.
If an agent acts incorrectly (sends a wrong email, pushes bad code), the liability
is with the operator (you). This is why:
- `approval_required: true` on high-stakes skill nodes (Section 2.3) is not optional
- The draft-first workflow (Section 2.7) requires explicit human acknowledgment
- `high_stakes_integrations` in Layer 3 of Section 3b.8 gates execution when memory
  is the primary input

This spec does not address professional liability; consult a lawyer if you operate
MindForge for third parties.

## 5.12 Dependency & Library Selection

This section specifies the exact Python packages, JavaScript packages, and infrastructure
services used by MindForge, with version constraints and rationale for each choice.

---

### 5.12.1 Python Dependencies

#### Core Framework

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `fastapi` | `>=0.115` | HTTP API server | Lifespan context manager pattern; replaces startup/shutdown events |
| `uvicorn` | `>=0.34` | ASGI server | Runs FastAPI; `uvicorn` CLI for dev, `gunicorn` for prod |
| `pydantic` | `>=2.10` | Data validation | v2 only; v1 has breaking changes. All data models use v2 |
| `pydantic_yaml` | `>=1.8` | YAML → Pydantic parsing | Preferred over raw `yaml.safe_load()` for skill validation — provides field-level type checking, validators, and IDE autocompletion for skill authors |
| `python-multipart` | `>=0.0.10` | Form/file upload parsing | Required for `fastapi.UploadFile` and `Form` field handling |
| `orjson` | `>=3.10` | Fast JSON serialization | 10x faster than stdlib `json`; FastAPI auto-uses it if installed. Used for all API responses and structured log output |

#### Agent Orchestration

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `langgraph` | `>=0.2` | Graph-based agent orchestration | Defines the supervisor/agent workflow as a directed graph |
| `langchain-openai` | `>=0.3` | OpenRouter LLM client | OpenRouter is OpenAI-API-compatible; this client works with base URL override |
| `langchain-anthropic` | `>=0.3` | Anthropic LLM client | For Claude models via OpenRouter |
| `langchain-core` | `>=0.3` | LangChain shared primitives | Shared abstractions (chat models, prompts, tools) |

#### Async HTTP

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `httpx` | `>=0.28` | Async HTTP client | asyncio-native; HTTP/2 support via `httpx[http2]`. Used for all external API calls |
| `aiohttp` | `>=3.11` | Async WebSocket client | Only if Ollama or other services require `aiohttp` instead of `httpx` |

#### Workflow & Background Tasks

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `temporalio` | `>=1.0` | Temporal Python SDK | Phase 3+. Handles 24/7 background workflows |
| `temporallite` | (bundled) | Embedded Temporal dev server | Dev-only; replaces full Temporal+Postgres cluster for `dev` profile |
| `croniter` | `>=2.0` | Cron expression parsing | For scheduling recurring agent tasks in Phase 3 |

#### Database & Storage

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `pglite` | `>=0.2` | Embedded PostgreSQL | SQLite-compatible; single-file per project. Used for episodic memory and task history |
| `chromadb` | `>=0.5` | Vector database | Semantic memory store. Client-server mode via `chroma` service |
| `psycopg2-binary` | `>=2.9` | PostgreSQL adapter | Only needed for `prod` Temporal profile |
| `alembic` | `>=1.14` | Database migrations | PGLite schema migrations; not needed for Phase 1 (drop-create is acceptable) |

#### Security

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `cryptography` | `>=44` | Fernet AES-GCM encryption | Token encryption at rest; `fernet.Fernet` class |
| `passlib[bcrypt]` | `>=1.7` | Password hashing | Future use only (if local auth is added); currently no passwords |

#### Observability

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `structlog` | `>=24` | Structured logging | JSON output to stdout → Docker logs; context binding for request IDs |
| `opentelemetry-api` | `>=1.27` | Tracing API | Minimal interface |
| `opentelemetry-sdk` | `>=1.27` | Tracing SDK | Span creation and export |
| `opentelemetry-exporter-otlp` | `>=1.27` | OTLP exporter | Sends spans to Jaeger or LangSmith |
| `psutil` | `>=6` | System metrics | CPU/memory for health endpoints |

#### Retry & Resilience

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `tenacity` | `>=9` | Retry decorator | Used for LLM calls and integration calls; configured with exponential backoff |

#### Text Processing & Embeddings

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `rank_bm25` | `>=0.2` | BM25 sparse retrieval | `BM25Okapi` class; pure Python, no C extension needed. Used in hybrid search |
| `sentence-transformers` | `>=3` | Dense embedding model | For cross-encoder reranking (Phase 3+). `all-MiniLM-L6-v2` as default |
| `numpy` | `>=2` | Numerical computing | Required by `rank_bm25` and `sentence-transformers` |

#### Development & Testing

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `pytest` | `>=8` | Test runner | `pytest-asyncio` for async tests; `pytest-cov` for coverage |
| `pytest-asyncio` | `>=0.25` | Async test support | Required for `async def` test functions |
| `pytest-mock` | `>=3` | Mocking | `pytest-mock.patch` context managers |
| `ruff` | `>=0.9` | Linter + formatter | Replaces `flake8`, `black`, `isort`. Run `ruff check . && ruff format .` |
| `mypy` | `>=1.14` | Static type checker | Strict mode: `mypy backend --strict` |
| `pre-commit` | `>=4` | Git hook runner | Runs ruff + mypy + seed requirements check on commit |

#### Optional / GPU

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `uvloop` | `>=0.21` | Fast asyncio event loop | Linux only; 2–4x faster event loop. Install in container build |
| `torch` | `>=2` | GPU tensor compute | Only if GPU is present and Ollama is not used; heavy dependency |
| `nomic` | (Ollama) | Local embeddings | Pulled via `ollama pull`; not a pip package |

---

### 5.12.2 JavaScript Dependencies

#### Frontend Framework

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `react` | `>=19` | UI framework | Latest stable |
| `react-dom` | `>=19` | React DOM renderer | Paired with React |
| `@tanstack/react-query` | `>=5` | Server state management | **Renamed from `react-query` v4→v5 in 2023.** Package is `@tanstack/react-query`. Old `react-query` package is abandoned |
| `@tanstack/react-router` | `>=1` | Router | For SPA routing. Alternatively `react-router-dom` v6 |
| `zustand` | `>=5` | Client state management | For UI state (modals, draft cache, notifications) |
| `zustand/vanilla` | `>=5` | Core store | If React-specific wrappers are not needed |

#### Build & Tooling

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `vite` | `>=6` | Build tool | Fast HMR dev server; production builds |
| `@vitejs/plugin-react` | `>=4` | React plugin for Vite | SWC fast refresh |
| `typescript` | `>=5` | Type system | Strict mode; frontend uses TS |
| `eslint` | `>=9` | Linter | With `eslint-plugin-react` and `eslint-plugin-react-hooks` |
| `prettier` | `>=4` | Formatter | Single config; run on save and pre-commit |

#### Testing

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `vitest` | `>=3` | Test runner | Vite-native; faster than Jest |
| `@playwright/test` | `>=1.50` | E2E testing | `npx playwright install` for browser binaries |
| `msw` | `>=2` | API mocking | Mocking integration API responses in tests |

#### UI Components

| Package | Version | Purpose | Notes |
|---|---|---|---|
| `lucide-react` | `>=0.500` | Icons | Tree-shakeable; consistent stroke weight |
| `clsx` | `>=2` | Conditional classnames | Lightweight; no runtime overhead |
| `date-fns` | `>=4` | Date formatting | For timestamps in task history |

---

### 5.12.3 Infrastructure Services (compose.yaml)

#### Production Services

| Service | Image | Port | Purpose | Notes |
|---|---|---|---|---|
| `chroma` | `chromadb/chroma:0.6` | 8000 | Vector database | Embedded mode not used; client-server via Docker |
| `temporal` | `temporalio/auto-setup:1.28` | 7233 | Workflow engine | Includes ` Temporal UI` on 8088. Requires `postgres` service |
| `postgres` | `postgres:16-alpine` | 5432 | Temporal persistence | Only for `prod` profile. SQLite/Temporalite for `dev` profile |
| `ollama` | `ollama/ollama:latest` | 11434 | Local inference | GPU support via `nvidia-container-toolkit`. Pull models at startup |

#### Development Services (dev profile)

| Service | Image | Port | Purpose | Notes |
|---|---|---|---|---|
| `temporallite` | (embedded) | — | Local Temporal | `temporallite` runs in-process via Python; no separate container |
| `chroma` | `chromadb/chroma:0.6` | 8000 | Same as prod | Single container, no data persistence on `docker compose down -v` |

#### Orphaned / Deprecated

| Service | Status | Reason |
|---|---|---|
| `redis` | **REMOVE** | Not used by Temporal (which persists to Postgres/SQLite). No HTTP caching layer is specified. Remove from all compose profiles to reduce complexity and false expectations |

---

### 5.12.4 Critical Fixes for compose.yaml

#### CRITICAL: Fernet_KEY case mismatch

The environment variable name is case-sensitive on Linux. `Fernet_KEY` and `FERNET_KEY`
are different variables. Docker compose passes `Fernet_KEY` as an empty string, causing
all token decryption to fail at runtime with a silent `cryptography.fernet.InvalidToken`.

**Before (broken):**
```yaml
environment:
  - Fernet_KEY=${FERNET_KEY}      # reads host env var FERNET_KEY, passes as Fernet_KEY
```

**After (correct):**
```yaml
environment:
  - FERNET_KEY=${FERNET_KEY}        # consistent with Python os.environ["FERNET_KEY"]
```

---

#### CRITICAL: Ollama healthcheck tests wrong port

`ollama serve` exposes its API on port `11434`, not the FastAPI healthcheck port.

```yaml
# Before (wrong — port 8000 is the backend API, not Ollama)
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]

# After (correct)
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
  interval: 30s
  timeout: 10s
  start_period: 60s
```

---

### 5.12.5 Temporalite vs Full Temporal — Dev vs Prod Profiles

Temporal's Python SDK supports two runtime modes:

**`dev` profile — Temporalite (embedded, no Docker service)**

Temporalite is a SQLite-backed Temporal server that runs in-process. It is started
by the backend container on `make dev`:

```python
# backend/scheduler/temporallite.py  (imported in dev only)
from temporalio.runtime import Runtime
from temporalio.server import Server

Runtime().server.run()  # starts on 127.0.0.1:7233
```

Pros: Zero external dependency, instant startup, no Postgres needed.
Cons: No horizontal scaling, no durable persistence across restarts.

**`prod` profile — Full Temporal + PostgreSQL**

```yaml
# compose.yaml prod profile
temporal:
  image: temporalio/auto-setup:1.28
  environment:
    - DB_TYPE=postgres
    - DB_HOST=postgres
    - DB_PORT=5432
    - DB_NAME=temporal
    - DB_USER=temporal
    - DB_PASSWORD=${TEMPORAL_DB_PASSWORD}
  depends_on:
    postgres:
      condition: service_healthy

postgres:
  image: postgres:16-alpine
  environment:
    POSTGRES_USER: temporal
    POSTGRES_PASSWORD: ${TEMPORAL_DB_PASSWORD}
  volumes:
    - postgres_data:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U temporal"]
```

The `backend` container detects which profile is active via `TEMPORAL_MODE=dev|prod`
and imports the appropriate scheduler.

---

### 5.12.6 Why pydantic_yaml instead of raw yaml.safe_load()

Skill files are YAML with a known schema. Parsing them with `yaml.safe_load()` alone
produces a raw dict with no validation — a missing required field or a wrong type is
only caught at runtime, at the first invocation.

```python
# Before (raw YAML — no validation)
import yaml
with open(skill_path) as f:
    skill_data = yaml.safe_load(f)
# BUG: missing "nodes" field raises KeyError only when the skill is executed
```

```python
# After (pydantic_yaml — validated at load time)
from pydantic import BaseModel, field_validator, model_validator
from pydantic_yaml import parse_yaml_raw_as
from enum import Enum

class AgentRole(str, Enum):
    COO = "coo"
    CMO = "cmo"
    RESEARCHER = "researcher"
    ENGINEER = "engineer"

class SkillNode(BaseModel):
    id: str
    agent: AgentRole
    prompt: str
    approval_required: bool = False
    tools: list[str] = []

    @field_validator("id")
    def id_snake_case(cls, v):
        assert re.match(r"^[a-z][a-z0-9_]*$"), f"Invalid node id: {v}"
        return v

class SkillModel(BaseModel):
    name: str
    description: str
    version: str
    execution_graph_type: str = "directed_acyclic_graph"
    nodes: list[SkillNode]

    @model_validator(mode="after")
    def has_end_node(self):
        ids = {n.id for n in self.nodes}
        assert "end" in ids, "Skill must have at least one 'end' node"
        return self

skill = parse_yaml_raw_as(SkillModel, skill_yaml_bytes)
# Missing field → PydanticValidationError at load time, not runtime
# Type error → immediate feedback with field name and expected type
```

`pydantic_yaml.parse_yaml_raw_as` reads YAML and validates against the Pydantic model
in one step. Skill authors also get autocomplete in IDEs that support Pydantic schemas.

---

### 5.12.7 Dependency Version Pins

Minimum versions are specified above. For reproducible builds, pin exact versions
in `requirements.txt` (backend) and `package.json` (frontend). A `/backend/requirements.txt`
stub exists in the spec but is not fully populated. It should contain:

```
# Backend — pin exact versions for reproducible builds
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
pydantic>=2.10.0
pydantic_yaml>=1.8.0
python-multipart>=0.0.10
orjson>=3.10.0
langgraph>=0.2.0
langchain-openai>=0.3.0
langchain-anthropic>=0.3.0
langchain-core>=0.3.0
httpx>=0.28.0
temporalio>=1.0.0
pglite>=0.2.0
chromadb>=0.5.0
cryptography>=44.0.0
structlog>=24.0.0
opentelemetry-api>=1.27.0
opentelemetry-sdk>=1.27.0
opentelemetry-exporter-otlp>=1.27.0
tenacity>=9.0.0
rank_bm25>=0.2.0
sentence-transformers>=3.0.0
numpy>=2.0.0
ruff>=0.9.0
mypy>=1.14.0
pytest>=8.0.0
pytest-asyncio>=0.25.0
pytest-mock>=3.0.0
```

Regenerate pins with: `pip freeze > requirements.txt` after `pip install -e .`

---

## 6. Reference: REAL-Agent Benchmark Dimensions

SureThing benchmarks itself on 4 dimensions (from their research page):

| Dimension | What it measures | Key capabilities needed |
|---|---|---|
| **Autonomous Resolution** (base score) | Task completion from intent to result | Tool use (OAuth, API keys), multi-step execution chains, error recovery |
| **Memory Depth** (multiplier) | Does the agent recall all context for a task? | Semantic + episodic + style memory, retrieval at task start |
| **Proactive Agency** (multiplier) | Does it act without being asked? | Background scheduling, inbox monitoring, anomaly detection |
| **Security & Guardrails** (multiplier) | Is the execution environment safe? | Sandboxed tool execution, approval gates, audit logging |

**Design implication:** Every feature you build maps to one of these four dimensions.
If a feature doesn't improve at least one dimension, it's not a SureThing-core capability.

---

## 7. Alternative Approaches and Honest Trade-offs

**Can you actually replicate SureThing perfectly?**

Partial replication is very achievable. The hardest parts are:

1. **The "always on" infrastructure** — requires Temporal or Celery background workers, not just
   on-demand API calls. This is real infrastructure, not just LLM prompting.

2. **864+ app integrations** — building and maintaining that many integrations is
   enormous. Composio solves this but costs ~$75/mo (pro plan). The difference between
   "I connect my Gmail" and "SureThing reads my inbox and drafts replies in my voice" is ~50hrs
   of integration work per app.

3. **Writing style memory** — the structured extraction approach (Section 2.2) is replicable,
   but it takes weeks of approved-draft feedback to build an accurate profile. Early drafts
   will feel generic.

4. **The 24/7 proactive loop** — email monitoring, follow-up detection, calendar
   conflict alerts. This is the "agency" part of AI agency. It requires polling
   infrastructure and is where the real utility lives.

**Realistic assessment:**
- A solo developer can build Phase 1–3 in 10–14 weeks (not 4–6)
  — Phase 1 alone is 3–4 weeks; multi-agent coordination is harder than it looks
- Composio is a hard dependency — there is no self-hosted alternative for 864 apps
- The core experience (multi-agent team, shared memory, draft-first workflow,
  proactive monitoring) is fully replicable with the architecture in this spec
- The main costs are LLM API calls (~$5–$50/mo for personal usage) and your time

---

## 8. Key Files to Create

If you want a reference implementation skeleton to start from:

```
~/mindforge/
├── SPEC.md                          # This document
├── backend/
│   ├── main.py                      # FastAPI entry point
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── supervisor.py            # LangGraph supervisor orchestrator
│   │   ├── coo.py                   # COO agent
│   │   ├── cmo.py                   # CMO agent
│   │   ├── researcher.py            # Researcher agent
│   │   └── engineer.py              # Engineer agent
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── store.py                 # SharedMemoryStore
│   │   ├── semantic.py             # ChromaDB vector memory
│   │   ├── episodic.py             # PGLite task history
│   │   └── style.py                 # Writing style profile
│   ├── skills/
│   │   ├── registry.py             # Skill loader/executor
│   │   └── skills/                 # YAML skill definitions
│   │       ├── github-daily-summary.yaml
│   │       ├── subscription-refund.yaml
│   │       └── distill-your-own-skill.yaml
│   ├── integrations/
│   │   ├── manager.py               # Integration connection manager
│   │   ├── composio_client.py       # Composio MCP bridge
│   │   └── direct/                  # Direct API implementations
│   │       ├── gmail.py
│   │       ├── github.py
│   │       ├── linear.py
│   │       └── stripe.py
│   ├── scheduler/
│   │   ├── __init__.py
│   │   ├── temporal_app.py           # Temporal client + workflow definitions
│   │   └── tasks.py                 # Proactive monitoring task definitions
│   └── db/
│       ├── schema.sql               # PGLite schema (User, Task, TaskStep, etc.)
│       └── models.py
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── ChatInterface.tsx
│   │   │   ├── TaskTracker.tsx
│   │   │   ├── DraftReview.tsx      # Approval UI
│   │   │   ├── MemoryViewer.tsx
│   │   │   ├── SkillLauncher.tsx
│   │   │   └── NotificationBell.tsx
│   │   ├── stores/
│   │   │   ├── taskStore.ts         # Zustand — canonical task state
│   │   │   └── notificationStore.ts
│   │   └── lib/
│   │       ├── api.ts               # TanStack Query fetchers
│   │       └── websocket.ts         # WebSocket client + reconnect logic
│   └── package.json
├── compose.yaml                      # Services: app, temporal, redis, chroma
└── .env.example                     # OPENROUTER_API_KEY, etc.
```

---

*Last updated: 2026-05-13
*Source: Primary research from surething.io (landing page, pricing, skills directory,
integrations page, research/REAL-Agent benchmark page), verified against secondary reviews.

Full changelog in CHANGELOG.md — all spec patches are documented at time of commit.---

