from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.services.auth import AuthService, WorkspaceContext
from app.services.authorization import identity_from_request, require_roles


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class MemberCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(default="", max_length=128)
    role: Literal["admin", "editor", "viewer"] = "viewer"
    temporary_password: str = Field(min_length=12, max_length=1024)


class MemberUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=128)
    role: Literal["admin", "editor", "viewer"] | None = None
    is_active: bool | None = None


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temporary_password: str = Field(min_length=12, max_length=1024)


def _session_payload(context: WorkspaceContext | None, *, required: bool = True) -> dict:
    if not context:
        return {
            "required": required,
            "authenticated": False,
            "user_id": "",
            "username": "",
            "display_name": "",
            "workspace_id": "",
            "role": "",
            "must_change_password": False,
            "csrf_token": "",
            "expires_at": "",
        }
    return {
        "required": required,
        "authenticated": True,
        "user_id": context.user_id,
        "username": context.username,
        "display_name": context.display_name,
        "workspace_id": context.workspace_id,
        "role": context.role,
        "must_change_password": context.must_change_password,
        "csrf_token": context.csrf_token,
        "expires_at": context.expires_at,
    }


def build_auth_router(auth_service: AuthService | None) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post("/login")
    def login(payload: LoginRequest, response: Response):
        service = _require_service(auth_service)
        try:
            raw_token, context = service.login(
                payload.password,
                username=payload.username,
            )
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="用户名或密码不正确。") from exc
        response.set_cookie(
            service.cookie_name,
            raw_token,
            max_age=service.session_ttl_seconds,
            httponly=True,
            secure=service.cookie_secure,
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
        _clear_cookie(response, auth_service)
        return {"logged_out": True}

    @router.post("/password")
    def change_password(
        payload: ChangePasswordRequest,
        request: Request,
        response: Response,
    ):
        service = _require_service(auth_service)
        identity = identity_from_request(request)
        try:
            service.change_password(
                identity,
                current_password=payload.current_password,
                new_password=payload.new_password,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _clear_cookie(response, service)
        return {"changed": True, "reauthentication_required": True}

    admin_dependency = require_roles("admin")

    @router.get("/members")
    def list_members(
        identity: WorkspaceContext = Depends(admin_dependency),
    ):
        service = _require_service(auth_service)
        return {"members": service.list_members(identity)}

    @router.post("/members", status_code=201)
    def create_member(
        payload: MemberCreateRequest,
        identity: WorkspaceContext = Depends(admin_dependency),
    ):
        service = _require_service(auth_service)
        try:
            member = service.create_member(
                identity,
                username=payload.username,
                password=payload.temporary_password,
                display_name=payload.display_name,
                role=payload.role,
            )
        except ValueError as exc:
            status = 409 if "已存在" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        return {"member": member}

    @router.get("/members/{user_id}")
    def get_member(
        user_id: str,
        identity: WorkspaceContext = Depends(admin_dependency),
    ):
        service = _require_service(auth_service)
        member = service.registry.get_member(
            user_id,
            workspace_id=identity.workspace_id,
        )
        if member is None:
            raise HTTPException(status_code=404, detail="成员不存在。")
        return {"member": member}

    @router.patch("/members/{user_id}")
    def update_member(
        user_id: str,
        payload: MemberUpdateRequest,
        response: Response,
        identity: WorkspaceContext = Depends(admin_dependency),
    ):
        service = _require_service(auth_service)
        try:
            member = service.update_member(
                identity,
                user_id,
                display_name=payload.display_name,
                role=payload.role,
                is_active=payload.is_active,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if user_id == identity.user_id and (
            payload.role is not None or payload.is_active is not None
        ):
            _clear_cookie(response, service)
        return {"member": member}

    @router.delete("/members/{user_id}")
    def disable_member(
        user_id: str,
        response: Response,
        identity: WorkspaceContext = Depends(admin_dependency),
    ):
        service = _require_service(auth_service)
        try:
            member = service.disable_member(identity, user_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if user_id == identity.user_id:
            _clear_cookie(response, service)
        return {"member": member, "disabled": True}

    @router.post("/members/{user_id}/reset-password")
    def reset_member_password(
        user_id: str,
        payload: PasswordResetRequest,
        response: Response,
        identity: WorkspaceContext = Depends(admin_dependency),
    ):
        service = _require_service(auth_service)
        try:
            member = service.reset_password(
                identity,
                user_id,
                temporary_password=payload.temporary_password,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if user_id == identity.user_id:
            _clear_cookie(response, service)
        return {"member": member, "sessions_revoked": True}

    return router


def _require_service(auth_service: AuthService | None) -> AuthService:
    if auth_service is None:
        raise HTTPException(status_code=409, detail="当前实例未启用会话认证。")
    return auth_service


def _clear_cookie(response: Response, auth_service: AuthService) -> None:
    response.delete_cookie(
        auth_service.cookie_name,
        path="/",
        secure=auth_service.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _identity(request: Request) -> WorkspaceContext | None:
    return request.scope.get("state", {}).get("identity")
