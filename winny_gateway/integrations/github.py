"""GitHub connector — the Engineering/CTO system-of-record, on the connector kit.

Phase 0 uses a Personal Access Token (per-tenant, encrypted via the kit) so it works
without OAuth-callback infra; the kit's OAuth path can replace the PAT later with no
change to callers. Read-only for now (repos + open issues) — writes stay behind the
owner gate when added. Keyless-safe: a bad token is a ConnectorError, never a crash.
"""
from __future__ import annotations

from typing import Any

import httpx

from winny_gateway.integrations.connector import Connector, ConnectorError, register

_API = "https://api.github.com"
_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _auth(token: str) -> dict[str, str]:
    return {**_HEADERS, "Authorization": f"Bearer {token}"}


class GitHubConnector(Connector):
    provider = "github"
    kind = "engineering"
    supported_actions = [{"action": "create_issue", "params": ["repo", "title", "body"], "label": "Open issue"}]

    async def act(self, action: str, params: dict[str, Any], conn: dict[str, Any], token: str) -> dict[str, Any]:
        if action != "create_issue":
            return await super().act(action, params, conn, token)
        repo = (params.get("repo") or "").strip()   # "owner/name"
        title = (params.get("title") or "").strip()
        if not repo or not title:
            raise ConnectorError("create_issue requires 'repo' (owner/name) and 'title'", code="bad_params", status=400)
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(f"{_API}/repos/{repo}/issues",
                                 headers=_auth(token), json={"title": title, "body": params.get("body") or ""})
        except httpx.HTTPError as exc:
            raise ConnectorError(f"GitHub unreachable: {exc}", code="network", status=502) from exc
        if r.status_code >= 400:
            raise ConnectorError(f"GitHub create_issue HTTP {r.status_code}", code="github_error", status=502)
        issue = r.json()
        return {"issue_url": issue.get("html_url"), "number": issue.get("number")}

    async def verify_token(self, token: str, account: str | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(f"{_API}/user", headers=_auth(token))
        except httpx.HTTPError as exc:
            raise ConnectorError(f"GitHub unreachable: {exc}", code="network", status=502) from exc
        if r.status_code == 401:
            raise ConnectorError("invalid GitHub token", code="invalid_token", status=400)
        if r.status_code >= 400:
            raise ConnectorError(f"GitHub error HTTP {r.status_code}", code="github_error", status=502)
        u = r.json()
        return {"external_account": u.get("login"), "github_id": u.get("id")}

    async def sync(self, uid: str, conn: dict[str, Any], token: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get(f"{_API}/user/repos",
                                headers=_auth(token),
                                params={"per_page": 100, "sort": "updated", "affiliation": "owner,collaborator,organization_member"})
        except httpx.HTTPError as exc:
            raise ConnectorError(f"GitHub unreachable: {exc}", code="network", status=502) from exc
        if r.status_code >= 400:
            raise ConnectorError(f"GitHub repos HTTP {r.status_code}", code="github_error", status=502)
        repos = r.json() or []
        open_issues = sum(int(repo.get("open_issues_count") or 0) for repo in repos)
        sample = [{"name": repo.get("full_name"), "open_issues": repo.get("open_issues_count")}
                  for repo in repos[:10]]
        return {
            "metadata": {"repos": len(repos), "open_issues": open_issues, "sample": sample},
            "repos": len(repos),
            "open_issues": open_issues,
        }


register(GitHubConnector())
