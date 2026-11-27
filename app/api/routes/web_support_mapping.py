"""Map console service results (``app.support.console``) to the HTTP contract.

Pure translation, no rule: ``app/support`` never imports ``app.api``, so the
dataclass -> Pydantic step lives on the API side.
"""

from __future__ import annotations

from app.api.routes.support import _context_to_response, _summary_to_response
from app.api.schemas.web_support import (
    ConsoleAssigneeResponse,
    ConsoleCaseDetailResponse,
    ConsoleCaseEventResponse,
    ConsoleCaseSummaryResponse,
    ConsoleSlaResponse,
)
from app.support.console import ConsoleCase, ConsoleCaseDetail
from app.support.sla import SlaAssessment


def sla_to_response(sla: SlaAssessment) -> ConsoleSlaResponse:
    return ConsoleSlaResponse(
        deadline_at=sla.deadline_at,
        elapsed_ratio=sla.elapsed_ratio,
        color=sla.color,
        paused=sla.paused,
        explanation=sla.explanation,
        basis=sla.basis or None,
    )


def assignee_to_response(display_name: str | None) -> ConsoleAssigneeResponse | None:
    if not display_name:
        return None
    return ConsoleAssigneeResponse(display_name=display_name)


def console_case_to_response(case: ConsoleCase) -> ConsoleCaseSummaryResponse:
    summary = case.summary
    return ConsoleCaseSummaryResponse(
        **_summary_to_response(summary).model_dump(),
        sla=sla_to_response(case.sla) if case.sla is not None else None,
        assignee=assignee_to_response(summary.assignee_display_name),
    )


def case_detail_to_response(
    request_id: str | None, detail: ConsoleCaseDetail
) -> ConsoleCaseDetailResponse:
    context = detail.context
    return ConsoleCaseDetailResponse(
        **_context_to_response(request_id, context).model_dump(),
        sla=sla_to_response(detail.sla) if detail.sla is not None else None,
        assignee=assignee_to_response(context.assignee_display_name),
        events=[
            ConsoleCaseEventResponse(
                action=event.action,
                from_status=event.from_status,
                to_status=event.to_status,
                note=event.note,
                actor_kind=event.actor_kind,
                actor_display_name=event.actor_display_name,
                created_at=event.created_at,
            )
            for event in detail.events
        ],
    )
