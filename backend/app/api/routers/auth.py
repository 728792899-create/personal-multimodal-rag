from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.services.auth import AuthService, WorkspaceContext


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


def _session_payload(context: WorkspaceContext | None, *, required: bool = True) -> dict:
    if not context:
        return {
            "required": required,
            "authenticated": False,
            "user_id": "",
            "workspace_id": "",
            "role": "",
            "csrf_token": "",
            "expires_at": "",
        }
    return {
        "required": required,
        "authenticated": True,
        "user_id": context.user_id,
        "workspace_id": context.workspace_id,
        "role": context.role,
        "csrf_token": context.csrf_token,
        "expires_at": context.expires_at,
    }


def build_auth_router(auth_service: AuthService | None) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/login")
    def login(payload: LoginRequest, response: Response):
        if auth_service is None:
            raise HTTPException(status_code=409, detail="Session authentication is disabled")
        try:
            raw_token, context = auth_service.login(payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid administrator credentials") from exc
        response.set_cookie(
            auth_service.cookie_name,
            raw_token,
            max_age=auth_service.session_ttl_seconds,
            httponly=True,
            secure=auth_service.cookie_secure,
            samesite="lax",
            path="/",
        )
        return {"session": _session_payload(context)}

    @router.get("/session")
    def session(request: Request):
        return {
            "session": _session_payload(
                _identity(request),
                required=auth_service is not None,
            )
        }

    @router.post("/logout")
    def logout(request: Request, response: Response):
        if auth_service is None:
            return {"logged_out": True}
        auth_service.logout(_identity(request))
        response.delete_cookie(
            auth_service.cookie_name,
            path="/",
            secure=auth_service.cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return {"logged_out": True}

    return router


def _identity(request: Request) -> WorkspaceContext | None:
    return request.scope.get("state", {}).get("identity")
