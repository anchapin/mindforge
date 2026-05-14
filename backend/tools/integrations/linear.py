"""Linear API tool — Task 11.

Phase 1 integration using personal API token (not OAuth).
GraphQL API at https://api.linear.app/graphql

Actions:
  - list_issues: query issues (supports team_id, state filter, pagination)
  - create_issue: createIssue mutation
  - update_issue: updateIssue mutation (issue_id + fields to update)
  - get_issue: single issue query by ID
"""

from __future__ import annotations

import logging
import time

import httpx

from ..base import BaseTool, ToolResult
from ..rate_limiter import integration_call

logger = logging.getLogger(__name__)

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_HEADERS = {"Content-Type": "application/json"}


class LinearTool(BaseTool):  # type: ignore[override]
    name = "linear_api"
    description = "Manage Linear issues: list, create, update, get"
    required_integrations = ["linear"]

    async def execute(self, action: str, **kwargs) -> ToolResult:  # noqa: C901  # type: ignore[override]
        """action: list_issues | create_issue | update_issue | get_issue"""

        start = time.monotonic()

        api_key = kwargs.get("api_key", "")
        headers = {**LINEAR_HEADERS, "Authorization": f"Bearer {api_key}"}

        async def _call(payload: dict) -> dict:
            """Execute GraphQL call through the rate limiter."""
            return await integration_call("linear", self._http_post, payload, headers)

        try:
            if action == "list_issues":
                team_id = kwargs.get("team_id")
                state = kwargs.get("state")  # e.g. "In Progress"
                cursor = kwargs.get("cursor")
                limit = kwargs.get("limit", 50)

                query = """
                query ListIssues($teamId: String, $state: String, $cursor: String, $limit: Int) {
                  issues(
                    first: $limit
                    after: $cursor
                    filter: {
                      team: { id: { eq: $teamId } }
                      state: { name: { eq: $state } }
                    }
                    orderBy: updatedAt
                  ) {
                    nodes {
                      id
                      identifier
                      title
                      description
                      priority
                      url
                      createdAt
                      updatedAt
                      state { name }
                      assignee { name email }
                    }
                    pageInfo {
                      hasNextPage
                      endCursor
                    }
                  }
                }
                """
                variables: dict = {
                    "limit": limit,
                    "teamId": team_id,
                    "state": state,
                    "cursor": cursor,
                }

                data = await _call({"query": query, "variables": variables})
                issues_data = data.get("data", {}).get("issues", {})
                nodes = issues_data.get("nodes", [])
                page_info = issues_data.get("pageInfo", {})

                all_issues: list[dict] = list(nodes)
                # Paginate through all pages
                while page_info.get("hasNextPage") and page_info.get("endCursor"):
                    cursor = page_info["endCursor"]
                    data = await _call(
                        {
                            "query": query,
                            "variables": {
                                "limit": limit,
                                "teamId": team_id,
                                "state": state,
                                "cursor": cursor,
                            },
                        }
                    )
                    issues_data = data.get("data", {}).get("issues", {})
                    all_issues.extend(issues_data.get("nodes", []))
                    page_info = issues_data.get("pageInfo", {})

                return ToolResult(
                    success=True,
                    data={"issues": [self._normalize_issue(i) for i in all_issues]},
                    latency_ms=(time.monotonic() - start) * 1000,
                )

            elif action == "create_issue":
                team_id = kwargs.get("team_id")
                title = kwargs.get("title", "")
                body = kwargs.get("body", "")
                priority = kwargs.get("priority", 0)

                mutation = """
                mutation CreateIssue($teamId: String!, $title: String!, $body: String, $priority: Int) {
                  issueCreate(input: {
                    teamId: $teamId
                    title: $title
                    description: $body
                    priority: $priority
                  }) {
                    success
                    issue {
                      id
                      identifier
                      title
                      url
                    }
                  }
                }
                """
                variables = {"teamId": team_id, "title": title, "body": body, "priority": priority}

                data = await _call({"query": mutation, "variables": variables})
                result_data = data.get("data", {}).get("issueCreate", {})

                if not result_data.get("success"):
                    errors = data.get("errors", [])
                    return ToolResult(
                        success=False,
                        error=f"Failed to create issue: {errors}",
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

                issue = result_data.get("issue", {})
                return ToolResult(
                    success=True,
                    data={
                        "id": issue.get("id"),
                        "number": issue.get("identifier"),
                        "title": issue.get("title"),
                        "issue_url": issue.get("url"),
                    },
                    latency_ms=(time.monotonic() - start) * 1000,
                )

            elif action == "update_issue":
                issue_id = kwargs.get("issue_id", "")
                title = kwargs.get("title")
                body = kwargs.get("body")
                state = kwargs.get("state")
                priority = kwargs.get("priority")

                # Build dynamic update input
                update_input: dict = {}
                if title is not None:
                    update_input["title"] = title
                if body is not None:
                    update_input["description"] = body
                if state is not None:
                    update_input["state"] = state
                if priority is not None:
                    update_input["priority"] = priority

                mutation = """
                mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
                  issueUpdate(id: $id, input: $input) {
                    success
                    issue {
                      id
                      title
                      identifier
                      state { name }
                      priority
                    }
                  }
                }
                """
                variables = {"id": issue_id, "input": update_input}

                data = await _call({"query": mutation, "variables": variables})
                result_data = data.get("data", {}).get("issueUpdate", {})

                if not result_data.get("success"):
                    errors = data.get("errors", [])
                    return ToolResult(
                        success=False,
                        error=f"Failed to update issue: {errors}",
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

                return ToolResult(
                    success=True,
                    data={
                        "success": True,
                        "issue": self._normalize_issue(result_data.get("issue", {})),
                    },
                    latency_ms=(time.monotonic() - start) * 1000,
                )

            elif action == "get_issue":
                issue_id = kwargs.get("issue_id", "")

                query = """
                query GetIssue($id: String!) {
                  issue(id: $id) {
                    id
                    identifier
                    title
                    description
                    priority
                    url
                    createdAt
                    updatedAt
                    state { name }
                    assignee { name email }
                  }
                }
                """
                variables = {"id": issue_id}

                data = await _call({"query": query, "variables": variables})
                issue = data.get("data", {}).get("issue")

                if not issue:
                    return ToolResult(
                        success=False,
                        error=f"Issue {issue_id} not found (null response)",
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

                return ToolResult(
                    success=True,
                    data={"issue": self._normalize_issue(issue)},
                    latency_ms=(time.monotonic() - start) * 1000,
                )

            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown action: {action}",
                    latency_ms=(time.monotonic() - start) * 1000,
                )

        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                error=f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            logger.exception("Linear tool error")
            return ToolResult(
                success=False, error=str(exc), latency_ms=(time.monotonic() - start) * 1000
            )

    async def _http_post(self, payload: dict, headers: dict) -> dict:
        """Make the HTTP call — factored out so integration_call can wrap it."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(LINEAR_API_URL, json=payload, headers=headers)
            return resp.json()

    def _normalize_issue(self, issue: dict) -> dict:
        """Normalize a Linear issue GraphQL response to flat dict."""
        return {
            "id": issue.get("id", ""),
            "identifier": issue.get("identifier", ""),
            "title": issue.get("title", ""),
            "description": issue.get("description", ""),
            "priority": issue.get("priority", 0),
            "url": issue.get("url", ""),
            "state": (issue.get("state") or {}).get("name", ""),
            "assignee_name": (issue.get("assignee") or {}).get("name", ""),
            "assignee_email": (issue.get("assignee") or {}).get("email", ""),
            "created_at": issue.get("createdAt", ""),
            "updated_at": issue.get("updatedAt", ""),
        }

    async def validate_auth(self, api_key: str | None = None) -> bool:
        """Check Linear API key validity with a simple viewer query."""
        if not api_key:
            return False
        query = """
        query {
          viewer {
            id
            name
            email
          }
        }
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await integration_call(
                    "linear",
                    client.post,
                    LINEAR_API_URL,
                    json={"query": query},
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                return resp.status_code == 200
            except Exception:
                return False
