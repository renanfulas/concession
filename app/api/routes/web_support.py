"""Console staff de suporte (/web/support/*): fila, detalhe, transicoes,
resposta ao cliente, relatorio mensal e metricas.

Area interna do time sobre o support inbox existente: nada de canal paralelo
de dados, nada de segredo no browser. Dark por padrao:
``ENABLE_SUPPORT_CONSOLE`` desligada responde ``404`` em toda a superficie,
inclusive auth.

A rota so valida e orquestra. Auth staff e guardas de sessao ficam em
``app/api/routes/web_support_auth.py`` (incluido neste router); SLA, fila,
detalhe, relatorio e metricas, em ``app/support/console.py``; o mapeamento
para o contrato HTTP, em ``app/api/routes/web_support_mapping.py``.

Logs seguem a regra do produto: sem PII, sem token, sem transcript; hashes
sempre truncados.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.api.routes.support import _ALLOWED_STATUSES
from app.api.routes.web_support_auth import (
    get_console_runtime,
    require_csrf_header,
    require_staff_session,
    storage_errors,
    too_many_requests,
)
from app.api.routes.web_support_auth import router as auth_router
from app.api.routes.web_support_mapping import (
    case_detail_to_response,
    console_case_to_response,
)
from app.api.schemas.web_support import (
    ConsoleAssigneeResponse,
    ConsoleCaseDetailResponse,
    ConsoleCaseListResponse,
    ConsoleCaseMessageRequest,
    ConsoleCaseMessageResponse,
    ConsoleDomainListResponse,
    ConsoleDomainResponse,
    ConsoleMetricsResponse,
    StaffTransitionRequest,
    StaffTransitionResponse,
)
from app.core.logging import log_event
from app.core.rate_limit import RateLimitExceeded
from app.core.request_context import get_request_id
from app.integrations.meta_whatsapp.client import MetaWhatsAppClient
from app.support.console import SupportConsoleService, load_domain_configs
from app.support.metrics import WINDOW_DAYS
from app.support.monthly_report import InvalidMonth
from app.support.repository import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.support.sla import COLOR_FILTERS, LATE_REASONS
from app.support.staff_auth import StaffPrincipal
from app.support.transitions import (
    CaseNotFound,
    InvalidTransition,
    LateReasonNotApplicable,
    LateReasonRequired,
    SupportCaseTransitionService,
)
from app.support.whatsapp_bridge import (
    ALLOWED_STAFF_TEMPLATES,
    CaseHasNoBinding,
    SupportWhatsAppBridgeService,
    SupportWhatsAppWindowClosed,
    UnknownStaffTemplate,
)


router = APIRouter()
logger = logging.getLogger(__name__)

_ACTIVE_SORTS = {"attention", "opened_at"}
_VIEWS = {"active", "history"}
_ASSIGNEE_FILTERS = {"me"}

# Auth primeiro: mesma ordem de rotas de antes da divisao.
router.include_router(auth_router)


def _console_service(request: Request) -> SupportConsoleService:
    return SupportConsoleService(
        settings=request.app.state.settings,
        database_runtime=request.app.state.database_runtime,
    )


@router.get("/domains", response_model=ConsoleDomainListResponse)
def list_console_domains(
    request: Request,
    principal: StaffPrincipal = Depends(require_staff_session),
) -> ConsoleDomainListResponse:
    """Nome de exibicao de cada dominio carregado, para rotulos e filtro da fila.

    Somente leitura e sem banco: vem do ``domain.yaml`` de cada dominio.
    """

    configs = load_domain_configs(request.app.state.settings.domains_path)
    return ConsoleDomainListResponse(
        request_id=get_request_id(request),
        domains=[
            ConsoleDomainResponse(name=config.name, display_name=config.display_name)
            for config in configs
        ],
    )


@router.get("/cases", response_model=ConsoleCaseListResponse)
def list_console_cases(
    request: Request,
    view: str = Query(default="active", max_length=20),
    domain: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, max_length=40),
    color: str | None = Query(default=None, max_length=10),
    sort: str = Query(default="attention", max_length=20),
    assignee: str | None = Query(default=None, max_length=10),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    principal: StaffPrincipal = Depends(require_staff_session),
) -> ConsoleCaseListResponse:
    if view not in _VIEWS:
        raise HTTPException(status_code=422, detail="invalid_view")
    if status is not None and status not in _ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail="invalid_status_filter")
    if color is not None and color not in COLOR_FILTERS:
        raise HTTPException(status_code=422, detail="invalid_color_filter")
    if sort not in _ACTIVE_SORTS:
        raise HTTPException(status_code=422, detail="invalid_sort")
    if assignee is not None and assignee not in _ASSIGNEE_FILTERS:
        raise HTTPException(status_code=422, detail="invalid_assignee_filter")
    assignee_staff_id = principal.staff_id if assignee == "me" else None

    service = _console_service(request)
    request_id = get_request_id(request)
    with storage_errors():
        if view == "history":
            page = service.list_history(
                domain=domain,
                status=status,
                limit=limit,
                offset=offset,
                assignee_staff_id=assignee_staff_id,
            )
        else:
            page = service.list_active(
                domain=domain,
                status=status,
                color=color,
                sort=sort,
                limit=limit,
                offset=offset,
                assignee_staff_id=assignee_staff_id,
            )
    if page.truncated:
        log_event(
            logger,
            "support_console_active_cap_reached",
            request_id=request_id,
            cap=service.settings.support_console_active_cases_cap,
        )
    cases = [console_case_to_response(case) for case in page.cases]

    log_event(
        logger,
        "support_console_listed",
        request_id=request_id,
        view=view,
        domain_filter_present=domain is not None,
        status_filter=status,
        color_filter=color,
        sort=sort,
        assignee_filter=assignee,
        result_count=len(cases),
        truncated=page.truncated,
    )
    return ConsoleCaseListResponse(
        request_id=request_id,
        view=view,
        count=len(cases),
        limit=limit,
        offset=offset,
        truncated=page.truncated,
        cases=cases,
    )


@router.get("/cases/{case_id}", response_model=ConsoleCaseDetailResponse)
def get_console_case(
    case_id: str,
    request: Request,
    principal: StaffPrincipal = Depends(require_staff_session),
) -> ConsoleCaseDetailResponse:
    with storage_errors():
        detail = _console_service(request).get_case_detail(case_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="support_case_not_found")

    request_id = get_request_id(request)
    context = detail.context
    log_event(
        logger,
        "support_console_case_viewed",
        request_id=request_id,
        case_id=context.case_id,
        status=context.status,
        turn_count=context.turn_count,
    )
    return case_detail_to_response(request_id, detail)


@router.post(
    "/cases/{case_id}/transition",
    response_model=StaffTransitionResponse,
)
def transition_console_case(
    case_id: str,
    payload: StaffTransitionRequest,
    request: Request,
    principal: StaffPrincipal = Depends(require_staff_session),
) -> StaffTransitionResponse:
    require_csrf_header(request)
    service = SupportCaseTransitionService(request.app.state.database_runtime)
    with storage_errors():
        try:
            result = service.apply(
                case_id=case_id,
                action=payload.action,
                actor_staff_id=principal.staff_id,
                note=payload.note,
                late_reason=payload.late_reason,
            )
        except CaseNotFound as exc:
            raise HTTPException(status_code=404, detail="support_case_not_found") from exc
        except LateReasonRequired as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "late_reason_required", "late_reasons": list(LATE_REASONS)},
            ) from exc
        except LateReasonNotApplicable as exc:
            raise HTTPException(
                status_code=422, detail={"code": "late_reason_not_applicable"}
            ) from exc
        except InvalidTransition as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_transition", "status": exc.status},
            ) from exc

    log_event(
        logger,
        "support_console_transition",
        request_id=get_request_id(request),
        case_id=result.case_id,
        action=payload.action,
        from_status=result.from_status,
        to_status=result.to_status,
        actor_staff_id=principal.staff_id,
        late_reason=result.late_reason,
    )
    return StaffTransitionResponse(
        case_id=result.case_id,
        status=result.to_status,
        late_reason=result.late_reason,
        assignee=(
            ConsoleAssigneeResponse(display_name=result.assignee_display_name)
            if result.assignee_display_name
            else None
        ),
    )


@router.post(
    "/cases/{case_id}/message",
    response_model=ConsoleCaseMessageResponse,
)
def send_console_case_message(
    case_id: str,
    payload: ConsoleCaseMessageRequest,
    request: Request,
    principal: StaffPrincipal = Depends(require_staff_session),
) -> ConsoleCaseMessageResponse:
    """Ponte WhatsApp<->console: o atendente responde o cliente pelo caso.

    Dentro da janela de 24h da Meta, sempre free-form (e gratis). Fora da
    janela, exige ``template`` (um de ``ALLOWED_STAFF_TEMPLATES``); sem um,
    responde 409 com a lista de templates disponiveis para o console
    reenviar a escolha do operador. Dark quando
    ``ENABLE_WHATSAPP_SUPPORT_NUMBER`` esta desligada.
    """

    require_csrf_header(request)
    settings = request.app.state.settings
    if not settings.enable_whatsapp_support_number:
        raise HTTPException(status_code=404, detail="Not found")

    runtime = get_console_runtime(request)
    try:
        runtime.reply_limiter.check(case_id)
    except RateLimitExceeded as exc:
        raise too_many_requests(exc) from exc

    bridge = SupportWhatsAppBridgeService(
        settings=settings,
        database_runtime=request.app.state.database_runtime,
        client=MetaWhatsAppClient(
            access_token=settings.meta_whatsapp_access_token or "",
            phone_number_id=settings.meta_support_phone_number_id or "",
            graph_api_version=settings.meta_whatsapp_graph_api_version,
            timeout_seconds=settings.meta_whatsapp_request_timeout_seconds,
        ),
    )
    with storage_errors():
        try:
            result = bridge.send_agent_reply(
                case_id=case_id,
                staff_id=principal.staff_id,
                text=payload.message,
                template=payload.template,
            )
        except CaseHasNoBinding as exc:
            raise HTTPException(
                status_code=409, detail={"code": "no_whatsapp_binding"}
            ) from exc
        except SupportWhatsAppWindowClosed as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "window_closed",
                    "templates": sorted(ALLOWED_STAFF_TEMPLATES),
                },
            ) from exc
        except UnknownStaffTemplate as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unknown_template",
                    "templates": sorted(ALLOWED_STAFF_TEMPLATES),
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="empty_message") from exc

    log_event(
        logger,
        "support_wa_agent_message",
        request_id=get_request_id(request),
        case_id=case_id,
        staff_id=principal.staff_id,
        delivery=result.delivery,
    )
    return ConsoleCaseMessageResponse(
        message_id=result.message_id, status="queued", delivery=result.delivery
    )


@router.get("/reports/monthly.csv")
def export_monthly_report(
    request: Request,
    month: str = Query(..., max_length=7),
    domain: str | None = Query(default=None, max_length=80),
    principal: StaffPrincipal = Depends(require_staff_session),
) -> Response:
    """Monthly CSV for the auditor: one row per case opened in the month.

    No personal data leaves through this route (see
    ``app/support/monthly_report.py``).
    """

    try:
        with storage_errors():
            report = _console_service(request).monthly_report(month=month, domain=domain)
    except InvalidMonth as exc:
        raise HTTPException(status_code=422, detail="invalid_month") from exc

    log_event(
        logger,
        "support_console_report_exported",
        request_id=get_request_id(request),
        month=month,
        domain_present=domain is not None,
        row_count=report.row_count,
        truncated=report.truncated,
    )
    suffix = f"-{domain}" if domain else ""
    return Response(
        content=report.body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="relatorio-mensal-{month}{suffix}.csv"',
            "Cache-Control": "no-store",
            "X-Report-Truncated": "true" if report.truncated else "false",
        },
    )


@router.get("/metrics", response_model=ConsoleMetricsResponse)
def get_console_metrics(
    request: Request,
    window: str = Query(default="14d", max_length=5),
    domain: str | None = Query(default=None, max_length=80),
    principal: StaffPrincipal = Depends(require_staff_session),
) -> ConsoleMetricsResponse:
    if window not in WINDOW_DAYS:
        raise HTTPException(status_code=422, detail="invalid_window")

    with storage_errors():
        metrics = _console_service(request).metrics(window=window, domain=domain)

    request_id = get_request_id(request)
    log_event(
        logger,
        "support_console_metrics_viewed",
        request_id=request_id,
        window=window,
        domain_present=domain is not None,
    )
    return ConsoleMetricsResponse(
        request_id=request_id,
        window=window,
        domain=domain,
        **metrics,
    )
