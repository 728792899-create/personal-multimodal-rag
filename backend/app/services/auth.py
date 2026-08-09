from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.cookies import SimpleCookie


VALID_ROLES = frozenset({"admin", "editor", "viewer"})
_USERNAME = re.compile(r"^[\w.@+-]{3,64}$", re.UNICODE)


@dataclass(frozen=True)
class WorkspaceContext:
    user_id: str
    workspace_id: str
    role: str
    csrf_token: str
    session_hash: str
    expires_at: str
    username: str = ""
    display_name: str = ""
    must_change_password: bool = False


class AuthService:
    cookie_name = "rag_session"

    def __init__(
        self,
        registry,
        *,
        password_hash: str,
        session_secret: str = "",
        session_ttl_seconds: int = 43_200,
        cookie_secure: bool = True,
    ):
        try:
            from argon2 import PasswordHasher
            from argon2.low_level import Type
        except ImportError as exc:
            raise RuntimeError("启用会话认证需要安装 argon2-cffi。") from exc
        if not password_hash.startswith("$argon2id$"):
            raise ValueError("ADMIN_PASSWORD_HASH 必须配置为 Argon2id 哈希。")
        self.registry = registry
        self.session_secret = (session_secret or secrets.token_hex(32)).encode("utf-8")
        self.session_ttl_seconds = max(300, int(session_ttl_seconds))
        self.cookie_secure = bool(cookie_secure)
        self.password_hasher = PasswordHasher(type=Type.ID)
        # One-time compatibility bridge from the legacy global administrator
        # secret to the database-backed local member model.
        self.registry.bootstrap_admin(password_hash=password_hash)

    @staticmethod
    def hash_password(password: str) -> str:
        AuthService._validate_password(password)
        try:
            from argon2 import PasswordHasher
            from argon2.low_level import Type
        except ImportError as exc:
            raise RuntimeError("生成密码哈希需要安装 argon2-cffi。") from exc
        return PasswordHasher(type=Type.ID).hash(password)

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 12:
            raise ValueError("密码至少需要 12 个字符。")
        if len(password) > 1024:
            raise ValueError("密码不能超过 1024 个字符。")

    @staticmethod
    def normalize_username(username: str) -> str:
        normalized = str(username or "").strip().casefold()
        if not _USERNAME.fullmatch(normalized):
            raise ValueError("用户名需为 3–64 个字符，且不能包含空格或特殊符号。")
        return normalized

    @staticmethod
    def validate_role(role: str) -> str:
        normalized = str(role or "").strip().lower()
        if normalized not in VALID_ROLES:
            raise ValueError("角色必须是 admin、editor 或 viewer。")
        return normalized

    def login(self, password: str, *, username: str = "admin") -> tuple[str, WorkspaceContext]:
        """Authenticate a local member.

        ``username=admin`` remains the temporary compatibility path for the
        pre-v1 password-only client while the public API sends both fields.
        """

        try:
            normalized = self.normalize_username(username)
        except ValueError:
            normalized = ""
        member = self.registry.get_user_by_username(
            normalized,
            include_password=True,
        ) if normalized else None
        verified = False
        if member and member.get("is_active"):
            try:
                verified = self.password_hasher.verify(
                    str(member.get("password_hash") or ""),
                    password,
                )
            except Exception:
                verified = False
        if not verified or member is None:
            raise ValueError("用户名或密码不正确。")

        raw_token = secrets.token_urlsafe(48)
        token_hash = self._token_hash(raw_token)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = (
            datetime.utcnow() + timedelta(seconds=self.session_ttl_seconds)
        ).isoformat(timespec="microseconds")
        self.registry.create_session(
            token_hash=token_hash,
            csrf_token=csrf_token,
            user_id=member["user_id"],
            workspace_id=member["workspace_id"],
            expires_at=expires_at,
        )
        context = WorkspaceContext(
            user_id=member["user_id"],
            username=member["username"],
            display_name=member["display_name"],
            workspace_id=member["workspace_id"],
            role=member["role"],
            must_change_password=bool(member["must_change_password"]),
            csrf_token=csrf_token,
            session_hash=token_hash,
            expires_at=expires_at,
        )
        self._audit(
            "auth.login.succeeded",
            "成员登录成功",
            actor=context,
            target_user_id=context.user_id,
        )
        return raw_token, context

    def resolve_cookie_header(self, cookie_header: str) -> WorkspaceContext | None:
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return None
        morsel = cookie.get(self.cookie_name)
        return self.resolve_token(morsel.value if morsel else "")

    def resolve_token(self, raw_token: str) -> WorkspaceContext | None:
        if not raw_token:
            return None
        token_hash = self._token_hash(raw_token)
        session = self.registry.resolve_session_identity(token_hash)
        if not session:
            return None
        return WorkspaceContext(
            user_id=session["user_id"],
            username=session["username"],
            display_name=session["display_name"],
            workspace_id=session["workspace_id"],
            role=session["role"],
            must_change_password=bool(session["must_change_password"]),
            csrf_token=session["csrf_token"],
            session_hash=token_hash,
            expires_at=session["expires_at"],
        )

    def verify_csrf(self, context: WorkspaceContext, supplied: str) -> bool:
        return bool(supplied) and hmac.compare_digest(supplied, context.csrf_token)

    def logout(self, context: WorkspaceContext | None) -> None:
        if context:
            self.registry.revoke_session(context.session_hash)

    def list_members(self, actor: WorkspaceContext) -> list[dict]:
        self._require_admin(actor)
        return self.registry.list_members(actor.workspace_id)

    def create_member(
        self,
        actor: WorkspaceContext,
        *,
        username: str,
        password: str,
        display_name: str,
        role: str,
    ) -> dict:
        self._require_admin(actor)
        normalized = self.normalize_username(username)
        normalized_role = self.validate_role(role)
        password_hash = self.hash_password(password)
        member = self.registry.create_member(
            username=normalized,
            password_hash=password_hash,
            display_name=display_name,
            role=normalized_role,
            must_change_password=True,
            workspace_id=actor.workspace_id,
        )
        self._audit(
            "auth.member.created",
            "成员账号已创建",
            actor=actor,
            target_user_id=member["user_id"],
            changes={"role": normalized_role, "username": normalized},
        )
        return member

    def update_member(
        self,
        actor: WorkspaceContext,
        user_id: str,
        *,
        display_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> dict:
        self._require_admin(actor)
        normalized_role = self.validate_role(role) if role is not None else None
        member = self.registry.update_member(
            user_id,
            workspace_id=actor.workspace_id,
            display_name=display_name,
            role=normalized_role,
            is_active=is_active,
        )
        if member is None:
            raise LookupError("成员不存在。")
        changes: dict[str, object] = {}
        if display_name is not None:
            changes["display_name_changed"] = True
        if normalized_role is not None:
            changes["role"] = normalized_role
        if is_active is not None:
            changes["is_active"] = is_active
        self._audit(
            "auth.member.updated",
            "成员账号已更新",
            actor=actor,
            target_user_id=user_id,
            changes=changes,
        )
        return member

    def disable_member(self, actor: WorkspaceContext, user_id: str) -> dict:
        return self.update_member(actor, user_id, is_active=False)

    def reset_password(
        self,
        actor: WorkspaceContext,
        user_id: str,
        *,
        temporary_password: str,
    ) -> dict:
        self._require_admin(actor)
        password_hash = self.hash_password(temporary_password)
        member = self.registry.update_member(
            user_id,
            workspace_id=actor.workspace_id,
            password_hash=password_hash,
            must_change_password=True,
        )
        if member is None:
            raise LookupError("成员不存在。")
        self._audit(
            "auth.member.password_reset",
            "成员密码已由管理员重置",
            actor=actor,
            target_user_id=user_id,
        )
        return member

    def change_password(
        self,
        actor: WorkspaceContext,
        *,
        current_password: str,
        new_password: str,
    ) -> None:
        member = self.registry.get_member(
            actor.user_id,
            workspace_id=actor.workspace_id,
            include_password=True,
        )
        if member is None or not member.get("is_active"):
            raise LookupError("成员不存在或已被禁用。")
        try:
            verified = self.password_hasher.verify(
                str(member.get("password_hash") or ""),
                current_password,
            )
        except Exception:
            verified = False
        if not verified:
            raise ValueError("当前密码不正确。")
        if hmac.compare_digest(new_password, current_password):
            raise ValueError("新密码不能与当前密码相同。")
        password_hash = self.hash_password(new_password)
        self.registry.update_member(
            actor.user_id,
            workspace_id=actor.workspace_id,
            password_hash=password_hash,
            must_change_password=False,
        )
        self._audit(
            "auth.password.changed",
            "成员已修改自己的密码",
            actor=actor,
            target_user_id=actor.user_id,
        )

    @staticmethod
    def _require_admin(actor: WorkspaceContext) -> None:
        if actor.role not in {"admin", "owner"}:
            raise PermissionError("需要管理员权限。")

    def _audit(
        self,
        event_type: str,
        message: str,
        *,
        actor: WorkspaceContext,
        target_user_id: str,
        changes: dict | None = None,
    ) -> None:
        # Deliberately record identifiers and policy changes only. Request
        # bodies, passwords, hashes, cookies, CSRF tokens and provider keys are
        # never accepted by this helper.
        self.registry.log_operation(
            event_type,
            message,
            payload={
                "actor_user_id": actor.user_id,
                "actor_role": actor.role,
                "workspace_id": actor.workspace_id,
                "target_user_id": target_user_id,
                "changes": changes or {},
            },
        )

    def _token_hash(self, raw_token: str) -> str:
        return hmac.new(
            self.session_secret,
            raw_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
