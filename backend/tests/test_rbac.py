from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.auth import build_auth_router
from app.middleware.request_guards import RequestGuardMiddleware
from app.services.auth import AuthService
from app.services.document_registry import DocumentRegistry
from app.services.authorization import required_permission


ADMIN_PASSWORD = "correct horse battery staple"


def _application() -> tuple[FastAPI, DocumentRegistry, AuthService]:
    registry = DocumentRegistry(":memory:")
    auth = AuthService(
        registry,
        password_hash=AuthService.hash_password(ADMIN_PASSWORD),
        session_ttl_seconds=3600,
        cookie_secure=False,
    )
    app = FastAPI()
    app.include_router(build_auth_router(auth), prefix="/api")

    @app.post("/api/private")
    def private():
        return {"ok": True}

    app.add_middleware(
        RequestGuardMiddleware,
        auth_service=auth,
        rate_limit_requests=200,
        rate_limit_window_seconds=60,
        login_rate_limit_requests=50,
        login_rate_limit_window_seconds=300,
    )
    return app, registry, auth


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["session"]


def _create_member(
    client: TestClient,
    csrf: str,
    *,
    username: str,
    password: str,
    role: str = "viewer",
) -> dict:
    response = client.post(
        "/api/auth/members",
        headers={"X-CSRF-Token": csrf},
        json={
            "username": username,
            "display_name": username.title(),
            "role": role,
            "temporary_password": password,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["member"]


def test_legacy_hash_bootstraps_database_backed_admin_and_is_not_reapplied():
    registry = DocumentRegistry(":memory:")
    first_hash = AuthService.hash_password(ADMIN_PASSWORD)
    auth = AuthService(registry, password_hash=first_hash, cookie_secure=False)

    admin = registry.get_user_by_username("admin", include_password=True)
    assert admin is not None
    assert admin["user_id"] == "owner"
    assert admin["role"] == "admin"
    assert admin["password_hash"].startswith("$argon2id$")
    assert admin["must_change_password"] is False

    new_password = "admin replacement password"
    registry.update_member(
        "owner",
        password_hash=AuthService.hash_password(new_password),
        must_change_password=False,
    )
    AuthService(
        registry,
        password_hash=AuthService.hash_password("ignored startup password"),
        cookie_secure=False,
    )
    _, context = auth.login(new_password, username="admin")
    assert context.username == "admin"
    assert context.role == "admin"


def test_v7_owner_schema_migrates_to_admin_without_losing_identity(tmp_path):
    path = tmp_path / "v7-registry.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (7, '2026-01-01')"
        )
        connection.execute(
            """
            CREATE TABLE workspaces (
              workspace_id TEXT PRIMARY KEY, name TEXT NOT NULL,
              is_default INTEGER NOT NULL, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO workspaces VALUES ('default', 'Legacy', 1, '2026-01-01', '2026-01-01')"
        )
        connection.execute(
            """
            CREATE TABLE users (
              user_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
              role TEXT NOT NULL, display_name TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO users VALUES ('owner', 'default', 'owner', 'Owner', '2026-01-01')"
        )
        connection.execute(
            """
            CREATE TABLE memberships (
              workspace_id TEXT NOT NULL, user_id TEXT NOT NULL,
              role TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY (workspace_id, user_id)
            )
            """
        )
        connection.execute(
            "INSERT INTO memberships VALUES ('default', 'owner', 'owner', '2026-01-01')"
        )
        connection.execute(
            """
            CREATE TABLE conversations (
              conversation_id TEXT PRIMARY KEY, title TEXT NOT NULL,
              knowledge_base_ids TEXT NOT NULL, created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO conversations VALUES (
              'legacy-conversation', 'Legacy chat', '["default"]',
              '2026-01-01', '2026-01-01'
            )
            """
        )

    registry = DocumentRegistry(str(path))
    AuthService(
        registry,
        password_hash=AuthService.hash_password(ADMIN_PASSWORD),
        cookie_secure=False,
    )

    admin = registry.get_user_by_username("admin", include_password=True)
    assert registry.schema_version == 9
    assert admin is not None
    assert admin["user_id"] == "owner"
    assert admin["role"] == "admin"
    assert admin["password_hash"].startswith("$argon2id$")
    legacy_conversation = registry.get_conversation(
        "legacy-conversation",
        user_id="owner",
        workspace_id="default",
    )
    assert legacy_conversation is not None
    assert legacy_conversation["user_id"] == "owner"
    assert legacy_conversation["workspace_id"] == "default"
    assert list(tmp_path.glob("v7-registry.sqlite3.bak-*"))


def test_admin_creates_local_member_and_temporary_password_is_forced_to_change():
    app, registry, _ = _application()
    admin_client = TestClient(app)
    admin_session = _login(admin_client, "admin", ADMIN_PASSWORD)
    member = _create_member(
        admin_client,
        admin_session["csrf_token"],
        username="reader",
        password="temporary reader password",
    )

    assert member["role"] == "viewer"
    assert member["must_change_password"] is True
    assert "password_hash" not in member

    reader_client = TestClient(app)
    reader_session = _login(reader_client, "reader", "temporary reader password")
    assert reader_session["must_change_password"] is True
    blocked = reader_client.post(
        "/api/private",
        headers={"X-CSRF-Token": reader_session["csrf_token"]},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "首次登录后必须先修改临时密码。"

    changed = reader_client.post(
        "/api/auth/password",
        headers={"X-CSRF-Token": reader_session["csrf_token"]},
        json={
            "current_password": "temporary reader password",
            "new_password": "permanent reader password",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["reauthentication_required"] is True
    assert reader_client.get("/api/auth/session").json()["session"]["authenticated"] is False

    refreshed = _login(reader_client, "reader", "permanent reader password")
    assert refreshed["must_change_password"] is False
    forbidden = reader_client.get("/api/auth/members")
    assert forbidden.status_code == 403

    operations = json.dumps(registry.list_operations(100), ensure_ascii=False)
    assert "temporary reader password" not in operations
    assert "permanent reader password" not in operations
    assert "$argon2" not in operations


def test_role_change_disable_and_password_reset_revoke_member_sessions():
    app, _, _ = _application()
    admin_client = TestClient(app)
    admin_session = _login(admin_client, "admin", ADMIN_PASSWORD)
    member = _create_member(
        admin_client,
        admin_session["csrf_token"],
        username="writer",
        password="temporary writer password",
        role="editor",
    )

    writer_client = TestClient(app)
    _login(writer_client, "writer", "temporary writer password")
    changed = admin_client.patch(
        f"/api/auth/members/{member['user_id']}",
        headers={"X-CSRF-Token": admin_session["csrf_token"]},
        json={"role": "viewer"},
    )
    assert changed.status_code == 200
    assert changed.json()["member"]["role"] == "viewer"
    assert writer_client.get("/api/auth/session").json()["session"]["authenticated"] is False

    writer_session = _login(writer_client, "writer", "temporary writer password")
    reset = admin_client.post(
        f"/api/auth/members/{member['user_id']}/reset-password",
        headers={"X-CSRF-Token": admin_session["csrf_token"]},
        json={"temporary_password": "replacement writer password"},
    )
    assert reset.status_code == 200
    assert reset.json()["member"]["must_change_password"] is True
    assert writer_client.get("/api/auth/session").json()["session"]["authenticated"] is False

    writer_session = _login(writer_client, "writer", "replacement writer password")
    disabled = admin_client.delete(
        f"/api/auth/members/{member['user_id']}",
        headers={"X-CSRF-Token": admin_session["csrf_token"]},
    )
    assert disabled.status_code == 200
    assert disabled.json()["member"]["is_active"] is False
    assert writer_client.get("/api/auth/session").json()["session"]["authenticated"] is False
    denied = writer_client.post(
        "/api/auth/login",
        json={
            "username": "writer",
            "password": "replacement writer password",
        },
    )
    assert denied.status_code == 401
    assert writer_session["must_change_password"] is True


def test_last_active_admin_cannot_be_disabled_or_demoted():
    app, _, _ = _application()
    admin_client = TestClient(app)
    session = _login(admin_client, "admin", ADMIN_PASSWORD)

    demote = admin_client.patch(
        "/api/auth/members/owner",
        headers={"X-CSRF-Token": session["csrf_token"]},
        json={"role": "editor"},
    )
    assert demote.status_code == 409
    assert demote.json()["detail"] == "不能禁用或降级最后一个管理员。"

    disable = admin_client.delete(
        "/api/auth/members/owner",
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert disable.status_code == 409
    assert disable.json()["detail"] == "不能禁用或降级最后一个管理员。"


def test_session_role_is_resolved_from_membership_on_every_request():
    _, registry, auth = _application()
    raw_token, initial = auth.login(ADMIN_PASSWORD, username="admin")
    assert initial.role == "admin"

    with registry.transaction() as connection:
        connection.execute(
            "UPDATE users SET role = 'editor' WHERE user_id = 'owner'"
        )
        connection.execute(
            "UPDATE memberships SET role = 'editor' WHERE user_id = 'owner'"
        )

    resolved = auth.resolve_token(raw_token)
    assert resolved is not None
    assert resolved.role == "editor"


@pytest.mark.parametrize(
    ("method", "path", "permission"),
    [
        ("GET", "/api/documents", "read"),
        ("POST", "/api/documents", "write"),
        ("POST", "/api/ask", "read"),
        ("POST", "/api/feedback", "read"),
        ("GET", "/api/feedback", "write"),
        ("GET", "/api/operations", "system_admin"),
        ("DELETE", "/api/knowledge-bases/default", "system_admin"),
        ("POST", "/api/providers/deepseek/runtime", "system_admin"),
        ("PATCH", "/api/eval/cases/case-1", "system_admin"),
        ("POST", "/api/documents/doc-1/reindex", "system_admin"),
        ("POST", "/api/indexes/index-1/activate", "system_admin"),
        ("POST", "/api/conversations", "read"),
        ("PATCH", "/api/conversations/conversation-1", "read"),
        ("DELETE", "/api/conversations/conversation-1", "read"),
        ("POST", "/api/query-assets", "read"),
        ("DELETE", "/api/query-assets/asset-1", "read"),
        ("GET", "/api/history", "system_admin"),
        ("DELETE", "/api/history", "system_admin"),
        ("GET", "/api/exports/history/history-1.md", "system_admin"),
    ],
)
def test_route_permission_matrix(method: str, path: str, permission: str):
    assert required_permission(method, path) == permission


def test_request_guard_enforces_viewer_editor_admin_matrix():
    registry = DocumentRegistry(":memory:")
    auth = AuthService(
        registry,
        password_hash=AuthService.hash_password(ADMIN_PASSWORD),
        session_ttl_seconds=3600,
        cookie_secure=False,
    )
    for username, role in (("editor", "editor"), ("viewer", "viewer")):
        registry.create_member(
            username=username,
            password_hash=AuthService.hash_password(f"{username} permanent password"),
            display_name=username.title(),
            role=role,
            must_change_password=False,
        )

    app = FastAPI()
    app.include_router(build_auth_router(auth), prefix="/api")

    @app.get("/api/read")
    def read_route():
        return {"ok": True}

    @app.post("/api/write")
    def write_route():
        return {"ok": True}

    @app.post("/api/ask")
    def ask_route():
        return {"ok": True}

    @app.post("/api/feedback")
    def feedback_route():
        return {"ok": True}

    @app.get("/api/operations")
    def operations_route():
        return {"ok": True}

    @app.get("/api/history")
    def history_route():
        return {"ok": True}

    @app.delete("/api/knowledge-bases/example")
    def delete_knowledge_base_route():
        return {"ok": True}

    app.add_middleware(
        RequestGuardMiddleware,
        auth_service=auth,
        rate_limit_requests=200,
        rate_limit_window_seconds=60,
        login_rate_limit_requests=50,
        login_rate_limit_window_seconds=300,
    )

    clients: dict[str, tuple[TestClient, str]] = {}
    for username, password in (
        ("admin", ADMIN_PASSWORD),
        ("editor", "editor permanent password"),
        ("viewer", "viewer permanent password"),
    ):
        client = TestClient(app)
        session = _login(client, username, password)
        clients[username] = (client, session["csrf_token"])

    viewer, viewer_csrf = clients["viewer"]
    assert viewer.get("/api/read").status_code == 200
    assert viewer.post(
        "/api/ask", headers={"X-CSRF-Token": viewer_csrf}
    ).status_code == 200
    assert viewer.post(
        "/api/feedback", headers={"X-CSRF-Token": viewer_csrf}
    ).status_code == 200
    assert viewer.post(
        "/api/write", headers={"X-CSRF-Token": viewer_csrf}
    ).status_code == 403
    assert viewer.get("/api/operations").status_code == 403
    assert viewer.get("/api/history").status_code == 403

    editor, editor_csrf = clients["editor"]
    assert editor.post(
        "/api/write", headers={"X-CSRF-Token": editor_csrf}
    ).status_code == 200
    assert editor.delete(
        "/api/knowledge-bases/example",
        headers={"X-CSRF-Token": editor_csrf},
    ).status_code == 403
    assert editor.get("/api/operations").status_code == 403
    assert editor.get("/api/history").status_code == 403

    admin, admin_csrf = clients["admin"]
    assert admin.post(
        "/api/write", headers={"X-CSRF-Token": admin_csrf}
    ).status_code == 200
    assert admin.delete(
        "/api/knowledge-bases/example",
        headers={"X-CSRF-Token": admin_csrf},
    ).status_code == 200
    assert admin.get("/api/operations").status_code == 200
    assert admin.get("/api/history").status_code == 200


def test_conversations_are_scoped_to_the_authenticated_owner(monkeypatch):
    from app.api.routers import conversations as conversations_router
    from app.api.routers import exports as exports_router

    registry = DocumentRegistry(":memory:")
    auth = AuthService(
        registry,
        password_hash=AuthService.hash_password(ADMIN_PASSWORD),
        session_ttl_seconds=3600,
        cookie_secure=False,
    )
    for username in ("alice", "bob"):
        registry.create_member(
            username=username,
            password_hash=AuthService.hash_password(f"{username} permanent password"),
            display_name=username.title(),
            role="viewer",
            must_change_password=False,
        )
    monkeypatch.setattr(conversations_router, "registry", registry)
    monkeypatch.setattr(exports_router, "registry", registry)

    app = FastAPI()
    app.include_router(build_auth_router(auth), prefix="/api")
    app.include_router(conversations_router.router, prefix="/api")
    app.include_router(exports_router.router, prefix="/api")
    app.add_middleware(
        RequestGuardMiddleware,
        auth_service=auth,
        rate_limit_requests=200,
        rate_limit_window_seconds=60,
        login_rate_limit_requests=50,
        login_rate_limit_window_seconds=300,
    )

    alice = TestClient(app)
    alice_session = _login(alice, "alice", "alice permanent password")
    bob = TestClient(app)
    bob_session = _login(bob, "bob", "bob permanent password")

    created = alice.post(
        "/api/conversations",
        headers={"X-CSRF-Token": alice_session["csrf_token"]},
        json={"title": "Alice private chat", "knowledge_base_ids": ["default"]},
    )
    assert created.status_code == 201
    conversation = created.json()["conversation"]
    assert conversation["user_id"] == alice_session["user_id"]
    assert conversation["workspace_id"] == "default"
    conversation_id = conversation["id"]

    assert [item["id"] for item in alice.get("/api/conversations").json()["conversations"]] == [
        conversation_id
    ]
    assert bob.get("/api/conversations").json()["conversations"] == []
    assert bob.get(f"/api/conversations/{conversation_id}").status_code == 404
    assert bob.get(f"/api/conversations/{conversation_id}/messages").status_code == 404
    assert bob.get(
        f"/api/exports/conversations/{conversation_id}.md"
    ).status_code == 404
    assert bob.patch(
        f"/api/conversations/{conversation_id}",
        headers={"X-CSRF-Token": bob_session["csrf_token"]},
        json={"title": "stolen"},
    ).status_code == 404
    assert bob.post(
        f"/api/conversations/{conversation_id}/messages:stream",
        headers={"X-CSRF-Token": bob_session["csrf_token"]},
        json={"question": "Can I read this?"},
    ).status_code == 404
    assert bob.delete(
        f"/api/conversations/{conversation_id}",
        headers={"X-CSRF-Token": bob_session["csrf_token"]},
    ).status_code == 404

    updated = alice.patch(
        f"/api/conversations/{conversation_id}",
        headers={"X-CSRF-Token": alice_session["csrf_token"]},
        json={"title": "Alice updated chat"},
    )
    assert updated.status_code == 200
    assert updated.json()["conversation"]["title"] == "Alice updated chat"
    assert alice.delete(
        f"/api/conversations/{conversation_id}",
        headers={"X-CSRF-Token": alice_session["csrf_token"]},
    ).status_code == 200


def test_history_and_feedback_are_scoped_to_the_creating_member():
    registry = DocumentRegistry(":memory:")
    history = registry.save_history(
        "Alice private question",
        {"answer": "private", "citations": []},
        user_id="alice",
        workspace_id="default",
    )

    assert registry.get_history(
        history["id"], user_id="alice", workspace_id="default"
    )
    assert registry.get_history(
        history["id"], user_id="bob", workspace_id="default"
    ) is None
    assert registry.list_history(
        user_id="bob", workspace_id="default"
    ) == []

    registry.save_feedback(
        {"history_id": history["id"], "rating": "down"},
        user_id="alice",
        workspace_id="default",
    )
    assert registry.feedback_stats(
        user_id="alice", workspace_id="default"
    )["negative"] == 1
    assert registry.list_feedback(
        user_id="bob", workspace_id="default"
    ) == []
