from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.cookies import SimpleCookie


@dataclass(frozen=True)
class WorkspaceContext:
    user_id: str
    workspace_id: str
    role: str
    csrf_token: str
    session_hash: str
    expires_at: str


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
        except ImportError as exc:
            raise RuntimeError("启用会话认证需要安装 argon2-cffi。") from exc
        if not password_hash.startswith("$argon2"):
            raise ValueError("ADMIN_PASSWORD_HASH 必须配置为 Argon2id 哈希。")
        self.registry = registry
        self.password_hash = password_hash
        self.session_secret = (session_secret or secrets.token_hex(32)).encode("utf-8")
        self.session_ttl_seconds = max(300, int(session_ttl_seconds))
        self.cookie_secure = bool(cookie_secure)
        self.password_hasher = PasswordHasher()

    @staticmethod
    def hash_password(password: str) -> str:
        if len(password) < 12:
            raise ValueError("管理员密码至少需要 12 个字符。")
        try:
            from argon2 import PasswordHasher
        except ImportError as exc:
            raise RuntimeError("生成管理员密码哈希需要安装 argon2-cffi。") from exc
        return PasswordHasher().hash(password)

    def login(self, password: str) -> tuple[str, WorkspaceContext]:
        try:
            verified = self.password_hasher.verify(self.password_hash, password)
        except Exception:
            verified = False
        if not verified:
            raise ValueError("管理员密码不正确。")
        raw_token = secrets.token_urlsafe(48)
        token_hash = self._token_hash(raw_token)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = (
            datetime.utcnow() + timedelta(seconds=self.session_ttl_seconds)
        ).isoformat(timespec="microseconds")
        self.registry.create_session(
            token_hash=token_hash,
            csrf_token=csrf_token,
            user_id="owner",
            workspace_id="default",
            expires_at=expires_at,
        )
        return raw_token, WorkspaceContext(
            user_id="owner",
            workspace_id="default",
            role="owner",
            csrf_token=csrf_token,
            session_hash=token_hash,
            expires_at=expires_at,
        )

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
        session = self.registry.get_session(token_hash)
        if not session:
            return None
        return WorkspaceContext(
            user_id=session["user_id"],
            workspace_id=session["workspace_id"],
            role="owner",
            csrf_token=session["csrf_token"],
            session_hash=token_hash,
            expires_at=session["expires_at"],
        )

    def verify_csrf(self, context: WorkspaceContext, supplied: str) -> bool:
        return bool(supplied) and hmac.compare_digest(supplied, context.csrf_token)

    def logout(self, context: WorkspaceContext | None) -> None:
        if context:
            self.registry.revoke_session(context.session_hash)

    def _token_hash(self, raw_token: str) -> str:
        return hmac.new(self.session_secret, raw_token.encode("utf-8"), hashlib.sha256).hexdigest()
