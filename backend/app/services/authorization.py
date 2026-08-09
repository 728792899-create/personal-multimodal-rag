from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request

from app.services.auth import WorkspaceContext


ROLE_PERMISSIONS = {
    "admin": frozenset({"read", "write", "member_admin", "system_admin"}),
    "editor": frozenset({"read", "write"}),
    "viewer": frozenset({"read"}),
    # Compatibility only for pre-v1 synthetic sessions and tests. Persisted
    # memberships are migrated to ``admin``.
    "owner": frozenset({"read", "write", "member_admin", "system_admin"}),
}

_READ_LIKE_POST_PATHS = frozenset(
    {
        "/api/search",
        "/api/search/compare",
        "/api/ask",
        "/api/feedback",
        "/api/auth/logout",
        "/api/auth/password",
    }
)


def required_permission(method: str, path: str) -> str:
    """Map an API request to the minimum RBAC permission.

    The policy is intentionally deny-by-default for mutations: new write
    routes automatically require an editor unless they are explicitly listed
    as read-like inference calls. High-impact control-plane routes are
    classified separately so they cannot accidentally inherit editor access.
    """

    normalized_method = method.upper()
    normalized_path = path.rstrip("/") or "/"

    if normalized_path.startswith("/api/auth/members"):
        return "member_admin"
    if normalized_path.startswith("/api/indexes"):
        return "system_admin"
    if normalized_path in {
        "/api/operations",
        "/api/metrics",
        "/api/history",
        "/api/index-jobs/dead-letters",
    } or normalized_path.startswith(("/api/system/", "/api/exports/history/")):
        return "system_admin"
    if normalized_method not in {"GET", "HEAD", "OPTIONS"}:
        if normalized_path.startswith("/api/providers/"):
            return "system_admin"
        if normalized_method == "DELETE" and normalized_path.startswith(
            "/api/knowledge-bases/"
        ):
            return "system_admin"
        if normalized_method == "PATCH" and normalized_path.startswith(
            "/api/eval/cases/"
        ):
            return "system_admin"
        if normalized_path == "/api/documents/rebuild-all" or (
            normalized_path.startswith("/api/documents/")
            and normalized_path.endswith(("/rebuild", "/reindex"))
        ):
            return "system_admin"
        if normalized_path.startswith("/api/index-jobs/") and (
            normalized_method == "DELETE" or normalized_path.endswith("/retry")
        ):
            return "system_admin"
        if normalized_path in _READ_LIKE_POST_PATHS or (
            normalized_path == "/api/conversations"
            or normalized_path.startswith("/api/conversations/")
            or normalized_path == "/api/query-assets"
            or normalized_path.startswith("/api/query-assets/")
        ):
            return "read"
        return "write"
    if normalized_path == "/api/feedback" or normalized_path.startswith("/api/eval/"):
        return "write"
    return "read"


def is_authorized(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(str(role or ""), frozenset())


def identity_from_request(request: Request) -> WorkspaceContext:
    identity = request.scope.get("state", {}).get("identity")
    if identity is None:
        raise HTTPException(status_code=401, detail="请先登录后再继续。")
    return identity


def enforce_roles(request: Request, *roles: str) -> WorkspaceContext:
    identity = identity_from_request(request)
    accepted = set(roles)
    if "admin" in accepted:
        accepted.add("owner")
    if identity.role not in accepted:
        raise HTTPException(status_code=403, detail="当前账号没有执行此操作的权限。")
    return identity


def require_roles(*roles: str) -> Callable[[Request], WorkspaceContext]:
    """FastAPI dependency factory for route-level role enforcement."""

    accepted = tuple(roles)

    def dependency(request: Request) -> WorkspaceContext:
        return enforce_roles(request, *accepted)

    return dependency


def require_permission(request: Request, permission: str) -> WorkspaceContext:
    identity = identity_from_request(request)
    if not is_authorized(identity.role, permission):
        raise HTTPException(status_code=403, detail="当前账号没有执行此操作的权限。")
    return identity
