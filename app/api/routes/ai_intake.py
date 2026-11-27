"""Intake de solucoes de IA dentro do console (/web/support/intake/*).

Vive sob ``/web/support`` de proposito: o cookie da sessao staff tem
``Path=/web/support``, entao a mesma sessao OTP do console vale aqui, sem
segundo login. Rotas so validam, chamam ``AiIntakeService`` e traduzem erros;
a regra fica em ``app/ai_intake/``.

Erros: campo invalido -> 422 com o nome do campo; solucao inexistente -> 404;
regra de fluxo (separacao de funcoes, estado errado, campo exigido pela
decisao) -> 409 com o codigo; banco fora -> 503. Logs sem nome, finalidade ou
nota: so referencia, acao e status.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from app.ai_intake.inventory import inventory_rows, render_ficha, render_inventory_csv
from app.ai_intake.models import (
    DATA_CATEGORIES,
    DATA_SUBJECTS,
    HOSTING_REGIONS,
    LEGAL_BASES,
    REJECTION_REASONS,
    SOLUTION_TYPES,
    SolutionSubmission,
)
from app.ai_intake.service import AiIntakeService, InvalidSubmission, SolutionView
from app.ai_intake.workflow import Actor, IntakeError, SolutionNotFound, TransitionRequest
from app.api.routes.web_support import _require_csrf_header, require_staff_session
from app.api.schemas.ai_intake import (
    CriticalityReasonResponse,
    IntakeOptionsResponse,
    IntakeRuleResponse,
    IntakeSlaResponse,
    SolutionEventResponse,
    SolutionListResponse,
    SolutionResponse,
    SolutionSubmitRequest,
    SolutionTransitionRequest,
)
from app.core.errors import DatabaseUnavailableError
from app.core.logging import log_event
from app.core.request_context import get_request_id
from app.support.staff_auth import StaffPrincipal

router = APIRouter()
logger = logging.getLogger(__name__)


def _service(request: Request) -> AiIntakeService:
    if not request.app.state.settings.enable_ai_intake:
        raise HTTPException(status_code=404, detail="Not found")
    return request.app.state.ai_intake_service


def _actor(principal: StaffPrincipal) -> Actor:
    return Actor(staff_id=principal.staff_id, display_name=principal.display_name)


def _timezone(request: Request) -> str:
    return request.app.state.settings.support_console_timezone


@router.get("/options", response_model=IntakeOptionsResponse)
def intake_options(
    service: AiIntakeService = Depends(_service),
    _: StaffPrincipal = Depends(require_staff_session),
) -> IntakeOptionsResponse:
    policy = service.policy
    return IntakeOptionsResponse(
        solution_types=list(SOLUTION_TYPES),
        hosting_regions=list(HOSTING_REGIONS),
        data_categories=list(DATA_CATEGORIES),
        data_subjects=list(DATA_SUBJECTS),
        legal_bases=list(LEGAL_BASES),
        rejection_reasons=list(REJECTION_REASONS),
        sla_days=dict(policy.sla_days),
        ripd_required_for=list(policy.ripd_required_for),
        basis=policy.basis,
        rules=[
            IntakeRuleResponse(id=rule.id, level=rule.level, reason=rule.reason)
            for rule in policy.rules
        ],
        durable=service.repository.durable,
    )


@router.get("/solutions", response_model=SolutionListResponse)
def list_solutions(
    service: AiIntakeService = Depends(_service),
    principal: StaffPrincipal = Depends(require_staff_session),
) -> SolutionListResponse:
    views = _call(service.queue)
    return SolutionListResponse(
        items=[_response(view, service, principal, with_events=False) for view in views],
        durable=service.repository.durable,
    )


@router.post("/solutions", response_model=SolutionResponse, status_code=201)
def submit_solution(
    payload: SolutionSubmitRequest,
    request: Request,
    service: AiIntakeService = Depends(_service),
    principal: StaffPrincipal = Depends(require_staff_session),
) -> SolutionResponse:
    _require_csrf_header(request)
    submission = SolutionSubmission(
        **payload.model_dump(exclude={"data_categories", "data_subjects"}),
        data_categories=tuple(payload.data_categories),
        data_subjects=tuple(payload.data_subjects),
    )
    view = _call(lambda: service.submit(submission, _actor(principal)))
    log_event(
        logger,
        "ai_intake_submitted",
        request_id=get_request_id(request),
        reference=view.record.reference,
        criticality=view.record.criticality,
    )
    return _response(view, service, principal)


@router.get("/solutions/{solution_id}", response_model=SolutionResponse)
def get_solution(
    solution_id: str,
    service: AiIntakeService = Depends(_service),
    principal: StaffPrincipal = Depends(require_staff_session),
) -> SolutionResponse:
    return _response(_call(lambda: service.get(solution_id)), service, principal)


@router.post("/solutions/{solution_id}/transitions", response_model=SolutionResponse)
def transition_solution(
    solution_id: str,
    payload: SolutionTransitionRequest,
    request: Request,
    service: AiIntakeService = Depends(_service),
    principal: StaffPrincipal = Depends(require_staff_session),
) -> SolutionResponse:
    _require_csrf_header(request)
    transition = TransitionRequest(**payload.model_dump())
    view = _call(lambda: service.transition(solution_id, transition, _actor(principal)))
    log_event(
        logger,
        "ai_intake_transition",
        request_id=get_request_id(request),
        reference=view.record.reference,
        action=payload.action,
        to_status=view.record.status,
    )
    return _response(view, service, principal)


@router.get("/solutions/{solution_id}/ficha.md", response_class=PlainTextResponse)
def solution_ficha(
    solution_id: str,
    request: Request,
    service: AiIntakeService = Depends(_service),
    _: StaffPrincipal = Depends(require_staff_session),
) -> Response:
    view = _call(lambda: service.get(solution_id))
    body = render_ficha(view, service.policy, _timezone(request))
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="ficha-{view.record.reference}.md"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/inventory.csv")
def inventory_csv(
    request: Request,
    service: AiIntakeService = Depends(_service),
    _: StaffPrincipal = Depends(require_staff_session),
) -> Response:
    views = _call(service.queue)
    body = render_inventory_csv(inventory_rows(views, _timezone(request)))
    log_event(
        logger,
        "ai_intake_inventory_exported",
        request_id=get_request_id(request),
        rows=len(views),
    )
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="inventario-solucoes-ia.csv"',
            "Cache-Control": "no-store",
        },
    )


def _call(operation):
    try:
        return operation()
    except InvalidSubmission as exc:
        raise HTTPException(
            status_code=422, detail={"code": "invalid_field", "field": exc.field}
        ) from exc
    except SolutionNotFound as exc:
        raise HTTPException(status_code=404, detail="solution_not_found") from exc
    except IntakeError as exc:
        raise HTTPException(
            status_code=409, detail={"code": exc.code, "field": _field(exc)}
        ) from exc
    except ValueError as exc:
        # Unknown action or rejection reason: a client error, not a rule.
        raise HTTPException(status_code=422, detail={"code": "invalid_value"}) from exc
    except DatabaseUnavailableError as exc:
        raise HTTPException(status_code=503, detail="ai_intake_storage_unavailable") from exc


def _field(exc: IntakeError) -> str | None:
    return exc.detail if exc.detail != exc.code else None


def _response(
    view: SolutionView,
    service: AiIntakeService,
    principal: StaffPrincipal,
    *,
    with_events: bool = True,
) -> SolutionResponse:
    record, submission = view.record, view.record.submission
    return SolutionResponse(
        id=record.id,
        reference=record.reference,
        name=submission.name,
        business_unit=submission.business_unit,
        purpose=submission.purpose,
        owner_name=submission.owner_name,
        owner_role=submission.owner_role,
        solution_type=submission.solution_type,
        vendor=submission.vendor,
        model_provider=submission.model_provider,
        model_name=submission.model_name,
        hosting_region=submission.hosting_region,
        data_categories=list(submission.data_categories),
        data_subjects=list(submission.data_subjects),
        legal_basis=submission.legal_basis,
        automated_decision=submission.automated_decision,
        external_facing=submission.external_facing,
        human_in_loop=submission.human_in_loop,
        criticality=record.criticality,
        criticality_reasons=[
            CriticalityReasonResponse(id=rule_id, text=service.policy.reason_text(rule_id))
            for rule_id in record.criticality_reasons
        ],
        ripd_required=record.ripd_required,
        status=record.status,
        submitted_by_name=record.submitted_by_name,
        submitted_by_me=record.submitted_by == principal.staff_id,
        reviewer_name=record.reviewer_name,
        reviewing_by_me=record.reviewer_staff_id == principal.staff_id,
        submitted_at=record.submitted_at,
        decided_at=record.decided_at,
        decision_note=record.decision_note,
        conditions=record.conditions,
        rejection_reason=record.rejection_reason,
        ripd_reference=record.ripd_reference,
        outcome=view.outcome,
        sla=IntakeSlaResponse(
            deadline_at=view.sla.deadline_at,
            color=view.sla.color,
            paused=view.sla.paused,
            elapsed_ratio=view.sla.elapsed_ratio,
            paused_minutes=int(view.paused_seconds // 60),
            basis=view.sla.basis,
        ),
        events=[
            SolutionEventResponse(
                action=event.action,
                from_status=event.from_status,
                to_status=event.to_status,
                actor_display_name=event.actor_display_name,
                note=event.note,
                created_at=event.created_at,
            )
            for event in record.events
        ]
        if with_events
        else [],
    )
