"""GitHub API tool. Phase 1 integration -- personal access token (not OAuth)."""

from __future__ import annotations

import logging
from datetime import UTC

import httpx

from .base import BaseTool, ToolResult
from .rate_limiter import integration_call

logger = logging.getLogger(__name__)

INTEGRATION_RATE_LIMITS = {"github": 5}


class GitHubTool(BaseTool):  # type: ignore[override]
    name = "github_api"
    description = "Fetch GitHub commits, issues, PRs for a repository"
    required_integrations = ["github"]

    async def execute(
        self,
        action: str,
        agent_identity: str | None = None,
        integration_config: dict | None = None,
        **kwargs,
    ) -> ToolResult:
        """action: commits | issues | prs | create_issue | create_pr"""
        import time

        start = time.monotonic()

        token = kwargs.get("token", "")
        repo = kwargs.get("repo", "")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

        async with httpx.AsyncClient(timeout=30.0) as client:

            async def _get(url: str, **request_kwargs) -> httpx.Response:
                return await integration_call(
                    "github",
                    client.get,
                    url,
                    **request_kwargs,
                )

            async def _post(url: str, **request_kwargs) -> httpx.Response:
                return await integration_call(
                    "github",
                    client.post,
                    url,
                    **request_kwargs,
                )

            try:
                if action == "commits":
                    all_commits: list[dict] = []
                    base_url = f"https://api.github.com/repos/{repo}/commits"
                    page_url: str | None = base_url
                    params: dict = {"per_page": 100}
                    since = kwargs.get("since")
                    if since:
                        params["since"] = since

                    while page_url:
                        resp = await _get(page_url, headers=headers, params=params)

                        # Handle HTTP errors (including 403 rate limit)
                        if resp.status_code == 403:
                            reset_info = ""
                            if "X-RateLimit-Reset" in resp.headers:
                                reset_ts = int(resp.headers["X-RateLimit-Reset"])
                                from datetime import datetime

                                reset_dt = datetime.fromtimestamp(reset_ts, tz=UTC)
                                reset_info = f" (resets at {reset_dt.isoformat()})"
                            logger.error("GitHub API rate limit exceeded (403)")
                            return ToolResult(
                                success=False,
                                error=f"GitHub API rate limit exceeded (403){reset_info}",
                                latency_ms=(time.monotonic() - start) * 1000,
                            )
                        if resp.status_code >= 400:
                            logger.error("GitHub API error: %s", resp.status_code)
                            return ToolResult(
                                success=False,
                                error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                                latency_ms=(time.monotonic() - start) * 1000,
                            )

                        resp_headers = dict(resp.headers)

                        # Parse Link header for next page URL
                        # httpx NormalizedHeaders normalizes keys to title case ("Link")
                        page_url = None
                        link_header = resp_headers.get("Link", "")
                        if link_header:
                            for part in link_header.split(","):
                                part = part.strip()
                                if 'rel="next"' in part:
                                    # Extract URL from <URL> — may be relative or absolute
                                    url_start = part.find("<")
                                    url_end = part.find(">")
                                    if url_start != -1 and url_end != -1:
                                        raw_url = part[url_start + 1 : url_end]
                                        # Resolve relative URL against base (GitHub uses relative next links)
                                        if raw_url.startswith("/"):
                                            # Relative — append to base path
                                            page_url = f"https://api.github.com{raw_url}"
                                        elif raw_url.startswith("?"):
                                            # Query-only relative — append to base URL
                                            page_url = f"{base_url}{raw_url}"
                                        else:
                                            page_url = raw_url
                                    break

                        page_commits = resp.json()
                        if not page_commits:
                            break

                        # If since filter is set, stop when we hit commits older than since
                        if since:
                            # GitHub API returns commits newest-first.
                            # Check oldest commit in this page; if it's before since, stop.
                            oldest = page_commits[-1]
                            oldest_date = oldest["commit"]["author"]["date"]
                            if oldest_date < f"{since}T00:00:00Z":
                                # Filter out commits older than since
                                filtered = [
                                    c
                                    for c in page_commits
                                    if c["commit"]["author"]["date"] >= f"{since}T00:00:00Z"
                                ]
                                all_commits.extend(self._normalize_commit(c) for c in filtered)
                                break

                        all_commits.extend(self._normalize_commit(c) for c in page_commits)
                        # Clear params for subsequent pages (URL already has them)
                        params = {}

                    return ToolResult(
                        success=True,
                        data={"commits": all_commits},
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

                elif action == "issues":
                    resp = await _get(
                        f"https://api.github.com/repos/{repo}/issues",
                        headers=headers,
                        params={"state": "open", "per_page": 20},
                    )
                    issues = [
                        {"number": i["number"], "title": i["title"], "state": i["state"]}
                        for i in resp.json()
                    ]
                    return ToolResult(
                        success=True,
                        data={"issues": issues},
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

                elif action == "create_issue":
                    resp = await _post(
                        f"https://api.github.com/repos/{repo}/issues",
                        headers=headers,
                        json={"title": kwargs["title"], "body": kwargs.get("body", "")},
                    )
                    issue = resp.json()
                    return ToolResult(
                        success=True,
                        data={"issue_url": issue["html_url"], "number": issue["number"]},
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

                else:
                    return ToolResult(
                        success=False,
                        error=f"Unknown action: {action}",
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

            except httpx.HTTPStatusError as exc:
                logger.error("GitHub API error: %s", exc.response.status_code)
                return ToolResult(
                    success=False,
                    error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                    latency_ms=(time.monotonic() - start) * 1000,
                )
            except Exception as exc:
                logger.exception("GitHub tool error")
                return ToolResult(
                    success=False, error=str(exc), latency_ms=(time.monotonic() - start) * 1000
                )

    def _normalize_commit(self, c: dict) -> dict:
        """Normalize a GitHub commit object to our standard format."""
        return {
            "sha": c["sha"][:7],
            "message": c["commit"]["message"].split("\n")[0],
            "author": c["commit"]["author"]["name"],
            "date": c["commit"]["author"]["date"],
        }

    async def validate_auth(self, token: str | None = None) -> bool:
        """Probe the user's real GitHub PAT against /user.

        Pre-fix: this sent `Authorization: Bearer ` (empty token), which
        always failed; it then returned `resp.status_code == 200` — so the
        result was permanently False regardless of whether the user had
        configured a valid token.
        """
        if not token:
            return False
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await integration_call(
                    "github",
                    client.get,
                    "https://api.github.com/user",
                    headers={"Authorization": f"Bearer {token}"},
                )
                return resp.status_code == 200
            except Exception as exc:
                logger.warning("GitHub validate_auth failed: %s", exc)
                return False
