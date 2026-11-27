"""Auth staff do console (/web/support/auth/*) e guardas compartilhadas.

OTP WhatsApp dedicado (``staff_members``/``staff_sessions``), login de
desenvolvimento local, sessao e logout. A sessao vive em cookie ``HttpOnly``
restrito a ``Path=/web/support``; o lembrete do dispositivo, a
``/web/support/auth``. ``require_staff_session`` e ``require_csrf_header``
guardam o resto do console (``app/api/routes/web_support.py``), que inclui
este router no mesmo prefixo.

Logs seguem a regra do produto: sem PII, sem token, sem transcript; hashes
sempre truncados.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.api.schemas.web_support import (
    StaffLoginResponse,
    StaffLogoutRequest,
    StaffLogoutResponse,
    StaffOtpConfirmRequest,
    StaffOtpStartRequest,
    StaffOtpStartResponse,
    StaffSessionResponse,
)
from app.core.errors import DatabaseUnavailableError
from app.core.logging import log_event
from app.core.rate_limit import RateLimitExceeded
from app.core.request_context import get_request_id
from app.support.dev_login import DEMO_STAFF_PHONE, dev_login_allowed
from app.support.staff_auth import (
    StaffConsoleAuthService,
    StaffPhoneRequired,
    StaffPrincipal,
    SupportConsoleRuntime,
)
from app.web_auth.service import InvalidOrExpiredCode


router = APIRouter()
# Mesmo nome de logger de antes da divisao: eventos de auth continuam sob
# ``app.api.routes.web_support``.
logger = logging.getLogger("app.api.routes.web_support")

STAFF_SESSION_COOKIE = "sfa_staff_session"
STAFF_HINT_COOKIE = "sfa_staff_hint"
STAFF_SESSION_COOKIE_PATH = "/web/support"
# O lembrete e ainda mais restrito: so viaja para os endpoints de auth.
STAFF_HINT_COOKIE_PATH = "/web/support/auth"

CSRF_HEADER_NAME = "X-Requested-With"
CSRF_HEADER_VALUE = "XMLHttpRequest"


def _ensure_enabled(request: Request) -> None:
    if not request.app.state.settings.enable_support_console:
        raise HTTPException(status_code=404, detail="Not found")


def get_console_runtime(request: Request) -> SupportConsoleRuntime:
    _ensure_enabled(request)
    return request.app.state.support_console_runtime


def _get_service(request: Request) -> StaffConsoleAuthService:
    return get_console_runtime(request).service


@contextmanager
def storage_errors() -> Iterator[None]:
    """Banco fora do ar vira 503 generico, em qualquer rota do console."""

    try:
        yield
    except DatabaseUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="support_inbox_storage_unavailable"
        ) from exc


def too_many_requests(exc: RateLimitExceeded) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="too_many_requests",
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


def _set_session_cookie(response: Response, settings: object, login: object) -> None:
    # O servidor e a fonte de verdade da expiracao; o Max-Age so acompanha.
    max_age = max(
        1,
        int((login.principal.expires_at - datetime.now(UTC)).total_seconds()),
    )
    response.set_cookie(
        key=STAFF_SESSION_COOKIE,
        value=login.session_token,
        max_age=max_age,
        path=STAFF_SESSION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=bool(settings.web_chat_cookie_secure),
    )


def require_staff_session(request: Request) -> StaffPrincipal:
    """Route guard for everything under /web/support except auth/*."""

    runtime = get_console_runtime(request)
    session_token = request.cookies.get(STAFF_SESSION_COOKIE)
    with storage_errors():
        principal = runtime.service.get_session(session_token)
    if principal is None:
        # Detail generico, sem eco de identificadores; o evento nomeado da
        # visibilidade de acesso negado sem vazar quem tentou.
        log_event(
            logger,
            "support_console_auth_denied",
            request_id=get_request_id(request),
            reason="no_valid_session",
        )
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        runtime.reads_limiter.check(session_token or "")
    except RateLimitExceeded as exc:
        raise too_many_requests(exc) from exc
    return principal


def require_csrf_header(request: Request) -> None:
    """Escritas (Fase B) exigem o cabecalho, alem do `SameSite=Lax` do cookie."""

    if request.headers.get(CSRF_HEADER_NAME) != CSRF_HEADER_VALUE:
        raise HTTPException(status_code=403, detail="csrf_header_required")


@router.post("/auth/start", response_model=StaffOtpStartResponse, status_code=202)
def start_staff_otp(
    payload: StaffOtpStartRequest,
    request: Request,
) -> StaffOtpStartResponse:
    service = _get_service(request)
    settings = request.app.state.settings
    with storage_errors():
        try:
            result = service.start(
                phone=payload.phone,
                hint_cookie=request.cookies.get(STAFF_HINT_COOKIE),
                client_host=request.client.host if request.client else "unknown",
            )
        except StaffPhoneRequired as exc:
            raise HTTPException(status_code=422, detail="invalid_phone") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid_phone") from exc
        except RateLimitExceeded as exc:
            raise too_many_requests(exc) from exc

    request_id = get_request_id(request)
    log_event(
        logger,
        "support_console_auth_started",
        request_id=request_id,
        staff_match=result.staff_match,
        phone_hash_prefix=result.phone_hash_prefix,
    )
    if result.delivery_failed:
        # Falha de entrega nunca muda a resposta (side channel); vira log
        # interno e o operador pede outro codigo.
        log_event(
            logger,
            "support_console_auth_delivery_failed",
            request_id=request_id,
            phone_hash_prefix=result.phone_hash_prefix,
        )
    return StaffOtpStartResponse(
        challenge_id=result.challenge_id,
        expires_in_seconds=settings.otp_code_ttl_seconds,
        retry_after_seconds=settings.otp_resend_cooldown_seconds,
    )


@router.post("/auth/confirm", response_model=StaffLoginResponse)
def confirm_staff_otp(
    payload: StaffOtpConfirmRequest,
    request: Request,
    response: Response,
) -> StaffLoginResponse:
    service = _get_service(request)
    settings = request.app.state.settings
    with storage_errors():
        try:
            login = service.confirm(
                challenge_id=payload.challenge_id,
                code=payload.code,
                phone=payload.phone,
                hint_cookie=request.cookies.get(STAFF_HINT_COOKIE),
            )
        except InvalidOrExpiredCode as exc:
            log_event(
                logger,
                "support_console_auth_denied",
                request_id=get_request_id(request),
                reason="invalid_or_expired_code",
            )
            raise HTTPException(status_code=400, detail="invalid_or_expired_code") from exc

    _set_session_cookie(response, settings, login)
    if login.hint_cookie_value:
        response.set_cookie(
            key=STAFF_HINT_COOKIE,
            value=login.hint_cookie_value,
            max_age=settings.support_staff_hint_ttl_days * 24 * 60 * 60,
            path=STAFF_HINT_COOKIE_PATH,
            httponly=True,
            samesite="lax",
            secure=bool(settings.web_chat_cookie_secure),
        )
    log_event(
        logger,
        "support_console_auth_confirmed",
        request_id=get_request_id(request),
        staff_id=login.principal.staff_id,
    )
    return StaffLoginResponse(
        display_name=login.principal.display_name,
        expires_at=login.principal.expires_at,
    )


def _require_dev_login(request: Request) -> None:
    """404 unless every dev-login guard holds (see app/support/dev_login.py)."""

    allowed = dev_login_allowed(
        request.app.state.settings,
        client_host=request.client.host if request.client else None,
        host_header=request.headers.get("host"),
        headers=request.headers,
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/auth/dev-login", status_code=204)
def dev_login_available(request: Request) -> Response:
    """204 when the local demo login is available; 404 otherwise."""

    _require_dev_login(request)
    return Response(status_code=204)


@router.post("/auth/dev-login", response_model=StaffLoginResponse)
def dev_login(request: Request, response: Response) -> StaffLoginResponse:
    """Session for the fictitious seed operator, without OTP (local demo only)."""

    _require_dev_login(request)
    require_csrf_header(request)
    service = _get_service(request)
    settings = request.app.state.settings
    with storage_errors():
        login = service.issue_dev_session(DEMO_STAFF_PHONE)
    if login is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "dev_staff_missing", "hint": "python -m scripts.seed_demo_cases"},
        )

    _set_session_cookie(response, settings, login)
    log_event(
        logger,
        "support_console_dev_login",
        request_id=get_request_id(request),
        staff_id=login.principal.staff_id,
    )
    return StaffLoginResponse(
        display_name=login.principal.display_name,
        expires_at=login.principal.expires_at,
    )


@router.get("/auth/session")
def get_staff_session(request: Request) -> Response:
    service = _get_service(request)
    with storage_errors():
        principal = service.get_session(request.cookies.get(STAFF_SESSION_COOKIE))
        if principal is not None:
            return JSONResponse(
                StaffSessionResponse(
                    display_name=principal.display_name,
                    expires_at=principal.expires_at,
                ).model_dump(mode="json"),
            )
        # 401 com o lembrete do dispositivo (se houver): e o que permite a
        # tela de login mostrar o botao de 1 clique "Entrar como <nome>".
        hint_name = service.get_hint_display_name(
            request.cookies.get(STAFF_HINT_COOKIE),
        )
    return JSONResponse(
        status_code=401,
        content={
            "authenticated": False,
            "hint": {"display_name": hint_name} if hint_name else None,
        },
    )


@router.post("/auth/logout", response_model=StaffLogoutResponse)
def logout_staff_session(
    request: Request,
    response: Response,
    payload: StaffLogoutRequest | None = None,
) -> StaffLogoutResponse:
    service = _get_service(request)
    forget_device = bool(payload and payload.forget_device)
    with storage_errors():
        service.logout(
            session_token=request.cookies.get(STAFF_SESSION_COOKIE),
            forget_hint_cookie=(
                request.cookies.get(STAFF_HINT_COOKIE) if forget_device else None
            ),
        )
    response.delete_cookie(STAFF_SESSION_COOKIE, path=STAFF_SESSION_COOKIE_PATH)
    if forget_device:
        response.delete_cookie(STAFF_HINT_COOKIE, path=STAFF_HINT_COOKIE_PATH)
    return StaffLogoutResponse()
