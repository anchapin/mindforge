#!/bin/bash
# Create GitHub issues for MindForge improvements

# Issue 1: memory_ratio dead code
gh issue create \
  --repo anchapin/mindforge \
  --title "CRITICAL: memory_ratio dead code - Layer 3 approval gate never fires" \
  --body "## Problem

The Layer 3 approval gate amplification in \`should_continue()\` cannot trigger because \`state.context.get(\"memory_ratio\", 0.0)\` always returns 0.0. The memory ratio is never calculated or set in the supervisor.

This is a **security critical** issue - the high-stakes action approval amplification designed to protect against prompt injection via memory attacks is completely non-functional.

## Root Cause

In \`backend/agents/supervisor.py\`:
- \`should_continue()\` checks \`memory_ratio > 0.5\` to determine if approval gate should be amplified
- But \`memory_ratio\` is never computed or injected into \`state.context\`
- The condition always evaluates to \`0.0 > 0.5\` = \`False\`

## Required Fix

In \`specialist_node()\`, calculate memory context length ratio before calling \`should_continue()\`:

1. Calculate \`memory_context_length\` from state.context.get(\"memory_context\", \"\")
2. Calculate \`task_description_length\` from state.context.get(\"task_description\", \"\")
3. Compute \`memory_ratio = memory_context_length / total_length\`
4. Inject into state.context before should_continue() check

## Files to Modify

- \`backend/agents/supervisor.py\` - Add memory ratio calculation in specialist_node()

## Acceptance Criteria

1. \`memory_ratio\` is calculated as \`memory_context_length / total_context_length\`
2. \`memory_ratio > 0.5\` triggers amplified approval gate behavior
3. High-stakes actions require stricter approval when memory context is dominant
4. Unit test confirms the ratio calculation and threshold behavior

## Related

See SPEC.md Section 3b.8 Layer 3 for the original design specification." \
  --label "security,critical,approval-gate"

# Issue 2: Agent JSON fragility
gh issue create \
  --repo anchapin/mindforge \
  --title "CRITICAL: Agent JSON output fragility - silent failures on parse error" \
  --body "## Problem

All 4 specialist agents (COO, CMO, Researcher, Engineer) use \`json.loads(response)\` to parse LLM output. If the LLM produces any non-JSON text, the task silently fails:

```python
return {\"error\": f\"Failed to parse JSON: {e}\", \"status\": \"error\"}
```

This causes silent task failures, no retry, and difficult debugging.

## Affected Files

- \`backend/agents/coo.py\`
- \`backend/agents/cmo.py\`
- \`backend/agents/researcher.py\`
- \`backend/agents/engineer.py\`

## Required Fix

1. Create shared JSON recovery function with retry logic
2. Add fallback to extract JSON-like content from malformed responses
3. Preserve raw response in error dict for debugging (truncated)
4. Maximum 2 retry attempts with LLM correction prompt

## Acceptance Criteria

1. JSON parse failures trigger retry with correction prompt
2. Raw response preserved in error dict for debugging
3. Maximum 2 retry attempts before returning error
4. All 4 agents use the shared recovery function
5. Unit tests for valid JSON, invalid JSON, and truncated responses

## Labels

- \`bug\`
- \`reliability\`
- \`agents\`"

# Issue 3: Tool permission enforcement
gh issue create \
  --repo anchapin/mindforge \
  --title "CRITICAL: Tool permission enforcement missing - authorization bypass" \
  --body "## Problem

The database schema includes \`allowed_agents\` and \`permissions\` fields per integration, but \`BaseTool.execute()\` does not validate them. Any agent can call any tool, bypassing intended access control.

This is a **security critical** issue.

## Affected Files

- \`backend/tools/base.py\`
- \`backend/tools/registry.py\`
- \`backend/agents/supervisor.py\`

## Required Fix

1. Pass agent identity to tool execution in supervisor
2. Add permission validation in BaseTool.execute()
3. Check \`allowed_agents\` before processing
4. Check action-specific permissions per call
5. Return clear error for unauthorized agents (not silent failure)

## Acceptance Criteria

1. \`BaseTool.execute()\` validates \`allowed_agents\` before processing
2. Action-specific permissions checked per call
3. Unauthorized agents receive clear error message
4. Permission errors logged with agent identity and requested action
5. Unit tests for authorized/unauthorized agent scenarios

## Related

See SPEC.md Section 3b.6 for original authorization design." \
  --label "security,authorization"

# Issue 4: Duplicate classify_task_type
gh issue create \
  --repo anchapin/mindforge \
  --title "HIGH: Duplicate classify_task_type - drift risk between store.py and supervisor.py" \
  --body "## Problem

The same keyword-based task classification logic is duplicated in:
- \`backend/memory/store.py\` lines 33-41 - \`TASK_TYPE_RULES\`
- \`backend/agents/supervisor.py\` lines 30-38 - \`TASK_TYPE_ROUTING\`

When adding new task types, developers may update one but not the other, causing inconsistent routing.

## Affected Files

- \`backend/memory/store.py\`
- \`backend/agents/supervisor.py\`
- \`backend/agents/routing.py\` (intended location for shared logic)

## Required Fix

1. Create \`backend/agents/routing.py\` with shared \`TASK_TYPE_RULES\`, \`classify_task_type()\`, and \`route_to_agent()\`
2. Remove duplicates from \`store.py\` and \`supervisor.py\`
3. Both import from \`routing.py\`

## Acceptance Criteria

1. Single source of truth for task classification logic
2. \`classify_task_type()\` and \`route_to_agent()\` in \`routing.py\`
3. Both \`store.py\` and \`supervisor.py\` import from \`routing.py\`
4. Adding a new task type requires editing only \`routing.py\`" \
  --label "maintainability,refactoring"

# Issue 5: Sync SQLite in async
gh issue create \
  --repo anchapin/mindforge \
  --title "HIGH: Sync SQLite in async context - blocking I/O in background worker" \
  --body "## Problem

\`EpisodicMemoryStore\` and \`WritingProfileStore\` use synchronous \`sqlite3.connect()\` in an async codebase. Blocking the event loop degrades performance under load.

## Affected Files

- \`backend/memory/episodic.py\`
- \`backend/memory/style.py\`

## Required Fix

Replace \`sqlite3\` with \`aiosqlite\`:
- All database operations become \`async def\`
- Use \`await conn.execute()\` and \`await cursor.fetchall()\`
- Enable WAL mode for better concurrency
- Connection pooling via initialize() pattern

## Acceptance Criteria

1. All database operations use \`aiosqlite\`
2. No \`sqlite3.connect()\` calls in async functions
3. WAL mode enabled for concurrent performance
4. Background write worker no longer blocks event loop
5. Existing tests pass with async implementation" \
  --label "performance,async"

# Issue 6: SupervisorRunner not reused
gh issue create \
  --repo anchapin/mindforge \
  --title "HIGH: SupervisorRunner not reused - expensive graph compilation per task" \
  --body "## Problem

A new \`SupervisorRunner\` instance is created for every task in \`create_task()\`. Each instantiation compiles a LangGraph \`StateGraph\` (~100-500ms). With concurrent tasks, this creates multiple redundant compiled graphs.

## Affected Files

- \`backend/api/routes/tasks.py\`
- \`backend/agents/supervisor.py\`

## Required Fix

Create a supervisor runner pool:
- Pool of 2-4 pre-compiled \`SupervisorRunner\` instances
- Checkout/checkin pattern for task execution
- Pool size configurable
- Graph compilation happens once per instance at startup

## Acceptance Criteria

1. \`SupervisorRunner\` instances are reused across requests
2. Graph compilation happens once per instance at startup
3. Pool size configurable (default 2)
4. Checkpointing still works with shared checkpointer
5. No race conditions in runner checkout/checkin

## Performance Target

- First task: ~500ms (compile + run)
- Subsequent tasks: ~50ms (reuse compiled graph)" \
  --label "performance,architecture"

# Issue 7: Unbounded write queue
gh issue create \
  --repo anchapin/mindforge \
  --title "HIGH: Unbounded write queue - backpressure risk" \
  --body "## Problem

\`SharedMemoryStore._write_queue\` is unbounded. If ChromaDB is slow or unavailable, the queue grows indefinitely, causing memory exhaustion.

## Affected Files

- \`backend/memory/store.py\`

## Required Fix

Replace with \`asyncio.Queue(maxsize=1000)\`:
- Add overflow policy: drop oldest entries or raise exception
- Log warning when queue reaches high watermark (75% capacity)
- Track dropped writes in metrics

## Acceptance Criteria

1. Queue has bounded size (maxsize=1000)
2. Overflow policy defined and implemented
3. Warning logged at 75% capacity
4. Metrics track dropped/failed writes
5. Memory usage stable under backpressure" \
  --label "stability,performance"

# Issue 8: ChromaDB graceful degradation
gh issue create \
  --repo anchapin/mindforge \
  --title "HIGH: ChromaDB graceful degradation missing" \
  --body "## Problem

If ChromaDB is unavailable, semantic memory queries fail completely instead of falling back to degraded mode. Users experience total failure instead of partial functionality.

## Affected Files

- \`backend/memory/semantic.py\`
- \`backend/memory/store.py\`

## Required Fix

1. Add try/catch around ChromaDB queries
2. On failure, fall back to episodic-only retrieval
3. Set \`degraded_quality = True\` flag in response
4. Log warning about degraded mode
5. Surface warning to user via frontend

## Acceptance Criteria

1. Semantic query failures don't crash the request
2. Falls back to episodic-only with degraded_quality flag
3. Warning logged for observability
4. Frontend displays degradation indicator
5. Automatic recovery when ChromaDB comes back" \
  --label "resilience,reliability"

# Issue 9: Skills not re-validated at invocation
gh issue create \
  --repo anchapin/mindforge \
  --title "MEDIUM: Skills not re-validated at invocation time" \
  --body "## Problem

\`validate_skill_graph()\` is only called at skill load time. If skill YAML is edited via API after loading, running executions use the unvalidated (potentially broken) definition.

## Affected Files

- \`backend/skills/registry.py\`

## Required Fix

Add invocation-time validation with caching:
- Validate once per skill version
- Cache validation result
- Invalidate cache on skill update
- Lightweight check: only validate if YAML changed since last validation

## Acceptance Criteria

1. Each skill version validated at most once
2. Validation result cached
3. Cache invalidated on skill update via API
4. Invalid skills rejected at invocation, not load time
5. Clear error message when running invalid skill" \
  --label "reliability,skills"

# Issue 10: WebSocket reconnection race
gh issue create \
  --repo anchapin/mindforge \
  --title "MEDIUM: WebSocket reconnection race condition" \
  --body "## Problem

If the frontend dashboard reconnects during task execution, it may show stale state. There's no sequence number or version vector for reconciliation.

## Affected Files

- \`backend/api/websocket.py\`
- \`frontend/src/stores/taskStore.ts\`

## Required Fix

1. Add sequence numbers to WebSocket messages
2. Client tracks last seen sequence
3. On reconnect, client requests missed events from last sequence + 1
4. Server replays missed events
5. Handle gaps gracefully (some events may be lost)

## Acceptance Criteria

1. Every WS message has incrementing sequence number
2. Client tracks last_seen_sequence
3. Reconnect triggers replay request
4. Server replays missed events
5. Gap handling (some events may be unavailable)" \
  --label "reliability,websocket"

# Issue 11: Rate limiter unused
gh issue create \
  --repo anchapin/mindforge \
  --title "MEDIUM: Rate limiter defined but never integrated" \
  --body "## Problem

\`backend/tools/rate_limiter.py\` defines a semaphore-based rate limiter, but it's never imported or used in any tool. GitHub, Stripe, and other integrations can hit 403 errors from concurrent API calls.

## Affected Files

- \`backend/tools/rate_limiter.py\`
- \`backend/tools/github.py\`
- \`backend/tools/stripe.py\`
- \`backend/tools/email_fetch.py\`
- \`backend/tools/email_send.py\`

## Required Fix

Integrate rate limiter into tool execution:
1. Each integration gets a named semaphore
2. Acquire before API call, release after
3. Configure limits per integration (GitHub: 50/hour, Stripe: 100/minute, etc.)
4. Return rate limit error to agent for retry later

## Acceptance Criteria

1. Rate limiter imported in tool implementations
2. Per-integration semaphore prevents 403s
3. Rate limit errors returned as retryable
4. Logs show when rate limit is hit
5. Limits configurable per integration" \
  --label "integration,rate-limiting"

# Issue 12: Startup error swallowing
gh issue create \
  --repo anchapin/mindforge \
  --title "MEDIUM: Startup error swallowing - silent degraded mode" \
  --body "## Problem

In \`main.py\` lifespan, exceptions are caught with \`logger.warning()\` and the backend continues. Critical components (LLM router, tool registry) can fail silently, leaving the system in a degraded state.

## Affected Files

- \`backend/main.py\`

## Required Fix

Distinguish fatal vs. recoverable errors:

```python
# Fatal - stop startup
try:
    llm_router = LLMRouter()
except LLMRouterInitializationError as e:
    raise RuntimeError(f\"Cannot start without LLM router: {e}\") from e

# Recoverable - continue with warning
try:
    await register_all_tools()
except ToolRegistrationError as e:
    logger.warning(f\"Some tools failed to register: {e}\")
    # Continue - system can work with reduced tool set
```

## Acceptance Criteria

1. LLM router failure is fatal (cannot function without it)
2. Tool registry partial failure is recoverable
3. ChromaDB connection failure is recoverable (degraded mode)
4. All failures logged with full stack trace
5. Health check endpoint reports component status" \
  --label "operability,reliability"

# Issue 13: Shallow copy in AgentState
gh issue create \
  --repo anchapin/mindforge \
  --title "LOW: Shallow copy in AgentState.model_copy()" \
  --body "## Problem

\`AgentState.model_copy()\` uses \`copy.copy()\` which is shallow. Nested \`dict\` or \`list\` in \`context\` or \`messages\` share references. If agents modify nested state, it affects the original.

## Affected Files

- \`backend/agents/supervisor.py\`

## Required Fix

Either:
1. Use \`copy.deepcopy()\` for model_copy()
2. Or restructure to avoid nested mutation

```python
def model_copy(self, **updates):
    # Deep copy to prevent mutation issues
    state = copy.deepcopy(super().model_copy(**updates))
    return state
```

## Acceptance Criteria

1. Nested dict/list modifications don't affect original state
2. Deep copy used instead of shallow copy
3. No performance regression (copy only happens on branch)\
" \
  --label "bug,maintainability"

# Issue 14: HMAC key derivation
gh issue create \
  --repo anchapin/mindforge \
  --title "LOW: HMAC key derivation from FERNET_KEY" \
  --body "## Problem

\`HMAC_KEY = os.getenv(\"MEMORY_HMAC_KEY\", \"dev-only-key\").encode()\` - defaults to weak key in production. Should derive from FERNET_KEY.

## Affected Files

- \`backend/memory/semantic.py\`

## Required Fix

Derive HMAC key from FERNET_KEY using HKDF:

```python
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

def derive_hmac_key(fernet_key: bytes) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b\"mindforge-hmac\",
        info=b\"semantic-memory-signing\",
    )
    return hkdf.derive(fernet_key)
```

## Acceptance Criteria

1. HMAC key derived from FERNET_KEY, not hardcoded
2. HKDF ensures cryptographic randomness
3. Works with existing FERNET_KEY env var
4. Graceful fallback if FERNET_KEY not set" \
  --label "security,cryptography"

# Issue 15: No correlation IDs
gh issue create \
  --repo anchapin/mindforge \
  --title "LOW: No correlation IDs for observability" \
  --body "## Problem

Multi-step skill executions have no correlation ID flowing through logs. Debugging a specific execution across agent, supervisor, and tool logs is difficult.

## Affected Files

- \`backend/agents/supervisor.py\`
- \`backend/memory/store.py\`
- \`backend/tools/base.py\`

## Required Fix

1. Generate correlation_id at task creation (uuid4)
2. Inject into task context
3. Include in all log statements
4. Propagate to tool executions
5. Add to WebSocket messages for frontend correlation

## Acceptance Criteria

1. Every task gets unique correlation_id at creation
2. correlation_id in all log statements for task
3. correlation_id passed to tool executions
4. correlation_id in WS messages
5. Searchable in log aggregation" \
  --label "observability,logging"

# Issue 16: Writing profile extraction not cached
gh issue create \
  --repo anchapin/mindforge \
  --title "LOW: Writing profile extraction prompt not cached" \
  --body "## Problem

\`STYLE_EXTRACTION_PROMPT\` is a constant but it's rendered fresh each time. The prompt is the same for every extraction, so it should be cached in the LLM prompt cache.

## Affected Files

- \`backend/memory/style.py\`

## Required Fix

The prompt cache in \`backend/llm/cache.py\` should cache prompt templates by hash. Ensure \`STYLE_EXTRACTION_PROMPT\` uses the cache:

```python
# In extract_style_fields
cached_prompt = prompt_cache.get(
    key=(\"style_extraction\", STYLE_EXTRACTION_PROMPT, draft_text[:500]),
    compute_fn=lambda: build_extraction_prompt(draft_text)
)
```

## Acceptance Criteria

1. Repeated style extractions use cached prompts
2. Cache hit rate > 80% for typical usage
3. Same draft returns cached result (idempotent)
4. Cache invalidated if prompt template changes" \
  --label "performance,caching"

echo "Created 16 GitHub issues successfully!"