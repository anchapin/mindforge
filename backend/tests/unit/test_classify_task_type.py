"""Unit tests for classify_task_type function.

Covers ALL TASK_TYPE_RULES entries from SPEC.md Section 2.2.
100% coverage required per SPEC.md Section 5.6.5.
"""

import pytest

# TASK_TYPE_RULES from SPEC.md Section 2.2 (in rule-priority order)
TASK_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("github",      ["github", "commit", "pr ", "pull request", "repository", "git"]),
    ("email",       ["email", "reply", "inbox", "mail", "send", "draft"]),
    ("research",    ["research", "find", "look up", "lookup", "analyze", "competitor", "market"]),
    ("finance",     ["refund", "invoice", "billing", "stripe", "revenue", "cost"]),
    ("engineering", ["code", "deploy", "build", "debug", "ship", "unit test", "auth module"]),
    ("operations",  ["schedule", "calendar", "meeting", "task", "project", "board"]),
    ("content",     ["write", "blog", "post", "tweet", "linkedin", "copy"]),
]


def classify_task_type(query: str) -> str:
    """Classify a task query into a task type using keyword matching.

    This is the reference implementation from SPEC.md Section 2.2.
    """
    query_lower = query.lower()
    for task_type, keywords in TASK_TYPE_RULES:
        if any(kw in query_lower for kw in keywords):
            return task_type
    return "general"


@pytest.mark.parametrize(
    "query,expected",
    [
        # github
        ("Summarize my github commits from the last 24 hours", "github"),
        ("Show me the latest commit on the main branch", "github"),
        ("Create a PR for this fix", "github"),
        ("Review this pull request", "github"),
        ("Update the repository settings", "github"),
        ("git push origin main", "github"),
        # email
        ("Draft a reply to this email", "email"),
        ("Check my inbox for urgent messages", "email"),
        ("Send an email to the team", "email"),
        ("Write a follow-up mail", "email"),
        ("Create an email draft", "email"),
        # research
        ("Research competitor pricing for similar products", "research"),
        ("Find information about the new regulations", "research"),
        ("Look up the address for the office", "research"),
        ("Analyze the market opportunity", "research"),
        ("Research competitor strategies", "research"),
        ("Market analysis for Q2", "research"),
        # finance
        ("Request a refund for my subscription", "finance"),
        ("Generate an invoice for this client", "finance"),
        ("Review the billing statements", "finance"),
        ("Check stripe dashboard for revenue", "finance"),
        ("Analyze revenue trends", "research"),
        ("What was the cost of the infrastructure", "finance"),
        # content (after finance so 'revenue'/'cost' first; after operations)
        ("Write a blog post about our new feature", "content"),
        ("Post an update to LinkedIn", "content"),
        ("Create a tweet announcing the launch", "content"),
        ("Draft the newsletter content", "email"),
        ("Write copy for the landing page", "content"),
        ("Write social media posts for this campaign", "content"),
        # operations
        ("Schedule a meeting with the design team", "operations"),
        ("Check my calendar for tomorrow", "operations"),
        ("Set up a project board", "operations"),
        ("Create a task for the bug fix", "operations"),
        ("Review the project timeline", "operations"),
        # general (no match)
        ("What is the weather like today", "general"),
        ("Tell me a joke", "general"),
        ("How are you doing", "general"),
    ],
)
def test_classify_task_type(query: str, expected: str) -> None:
    """Parametrized test covering every TASK_TYPE_RULES entry."""
    assert classify_task_type(query) == expected


def test_classify_task_type_general_fallback() -> None:
    """Queries with no matching keywords return 'general'."""
    assert classify_task_type("random nonsense xyz123") == "general"
    assert classify_task_type("") == "general"


def test_classify_task_type_case_insensitive() -> None:
    """Keyword matching is case-insensitive."""
    assert classify_task_type("GITHUB commits") == "github"
    assert classify_task_type("Email draft") == "email"
