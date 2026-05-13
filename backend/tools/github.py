"""GitHub API tool. Phase 1 integration -- personal access token (not OAuth)."""

from __future__ import annotations

import logging

import httpx

from .base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

INTEGRATION_RATE_LIMITS = {"github": 5}


class GitHubTool(BaseTool):
    name = "github_api"
    description = "Fetch GitHub commits, issues, PRs for a repository"
    required_integrations = ["github"]

    async def execute(self, action: str, **kwargs) -> ToolResult:
        """action: commits | issues | prs | create_issue | create_pr"""
        import time
        start = time.monotonic()

        token = kwargs.get("token", "")
        repo = kwargs.get("repo", "")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                if action == "commits":
                    resp = await client.get(
                        f"https://api.github.com/repos/{repo}/commits",
                        headers=headers,
                        params={"per_page": kwargs.get("per_page", 30)},
                    )
                    commits = [
                        {"sha": c["sha"][:7], "message": c["commit"]["message"].split("\n")[0],
                         "author": c["commit"]["author"]["name"], "date": c["commit"]["author"]["date"]}
                        for c in resp.json()
                    ]
                    return ToolResult(success=True, data={"commits": commits}, latency_ms=(time.monotonic() - start) * 1000)

                elif action == "issues":
                    resp = await client.get(
                        f"https://api.github.com/repos/{repo}/issues",
                        headers=headers, params={"state": "open", "per_page": 20},
                    )
                    issues = [{"number": i["number"], "title": i["title"], "state": i["state"]} for i in resp.json()]
                    return ToolResult(success=True, data={"issues": issues}, latency_ms=(time.monotonic() - start) * 1000)

                elif action == "create_issue":
                    resp = await client.post(
                        f"https://api.github.com/repos/{repo}/issues",
                        headers=headers,
                        json={"title": kwargs["title"], "body": kwargs.get("body", "")},
                    )
                    issue = resp.json()
                    return ToolResult(success=True, data={"issue_url": issue["html_url"], "number": issue["number"]}, latency_ms=(time.monotonic() - start) * 1000)

                else:
                    return ToolResult(success=False, error=f"Unknown action: {action}", latency_ms=(time.monotonic() - start) * 1000)

            except httpx.HTTPStatusError as exc:
                logger.error("GitHub API error: %s", exc.response.status_code)
                return ToolResult(success=False, error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}", latency_ms=(time.monotonic() - start) * 1000)
            except Exception as exc:
                logger.exception("GitHub tool error")
                return ToolResult(success=False, error=str(exc), latency_ms=(time.monotonic() - start) * 1000)

    async def validate_auth(self) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get("https://api.github.com/user", headers={"Authorization": f"Bearer {''}"})
                return resp.status_code == 200
            except Exception:
                return False
