"""Fluxo de analise do intake: quem pode fazer o que, em qual estado.

``plan_transition`` e uma funcao pura: recebe o registro lido (ja travado com
``FOR UPDATE`` no PostgreSQL) e devolve o que gravar, ou levanta um erro de
negocio. Assim a regra fica testavel sem banco e o repositorio so aplica.

Regras de governanca:
- quem submeteu nao assume nem decide a propria solucao (separacao de funcoes);
- so o revisor que assumiu decide;
- toda decisao tem nota; rejeicao tem motivo de lista fechada; aprovar uma
  solucao que exige RIPD pede a referencia do RIPD;
- ``needs_info`` pausa o prazo (os eventos guardam quando pausou e retomou).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.ai_intake.models import REJECTION_REASONS, SolutionEvent, SolutionRecord
from app.core.errors import TransactionBusinessError

NOTE_MAX_LENGTH = 1000

ACTIONS = (
    "claim",
    "release",
    "request_info",
    "resume",
    "approve",
    "approve_with_conditions",
    "reject",
    "withdraw",
)
DECISION_ACTIONS = frozenset({"approve", "approve_with_conditions", "reject"})

# (from_status, action) -> to_status
TRANSITION_MATRIX: dict[tuple[str, str], str] = {
    ("submitted", "claim"): "in_review",
    ("in_review", "release"): "submitted",
    ("in_review", "request_info"): "needs_info",
    ("needs_info", "resume"): "in_review",
    ("in_review", "approve"): "approved",
    ("in_review", "approve_with_conditions"): "approved_conditional",
    ("in_review", "reject"): "rejected",
    ("submitted", "withdraw"): "withdrawn",
    ("needs_info", "withdraw"): "withdrawn",
}


class IntakeError(TransactionBusinessError):
    """Business rejection; ``code`` is what the API returns."""

    code = "intake_error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.code)
        self.detail = detail or self.code


class SolutionNotFound(IntakeError):
    code = "solution_not_found"


class InvalidTransition(IntakeError):
    code = "invalid_transition"


class SelfReviewForbidden(IntakeError):
    code = "self_review_forbidden"


class NotTheReviewer(IntakeError):
    code = "not_the_reviewer"


class NotTheSubmitter(IntakeError):
    code = "not_the_submitter"


class MissingRequiredField(IntakeError):
    code = "missing_required_field"


@dataclass(frozen=True)
class Actor:
    staff_id: str
    display_name: str


@dataclass(frozen=True)
class TransitionRequest:
    action: str
    note: str | None = None
    conditions: str | None = None
    rejection_reason: str | None = None
    ripd_reference: str | None = None


@dataclass(frozen=True)
class TransitionPlan:
    from_status: str
    to_status: str
    reviewer_staff_id: str | None
    decided: bool
    note: str | None
    decision_note: str | None = None
    conditions: str | None = None
    rejection_reason: str | None = None
    ripd_reference: str | None = None


def plan_transition(
    record: SolutionRecord, request: TransitionRequest, actor: Actor
) -> TransitionPlan:
    if request.action not in ACTIONS:
        raise ValueError(f"unknown intake action: {request.action}")
    if request.rejection_reason is not None and request.rejection_reason not in REJECTION_REASONS:
        raise ValueError(f"unknown rejection_reason: {request.rejection_reason}")

    to_status = TRANSITION_MATRIX.get((record.status, request.action))
    if to_status is None:
        raise InvalidTransition(record.status)

    is_submitter = actor.staff_id == record.submitted_by
    is_reviewer = record.reviewer_staff_id == actor.staff_id
    note = _clean(request.note)

    if request.action == "claim":
        if is_submitter:
            raise SelfReviewForbidden()
        return TransitionPlan(record.status, to_status, actor.staff_id, False, note)

    if request.action == "withdraw":
        if not is_submitter:
            raise NotTheSubmitter()
        return TransitionPlan(
            record.status, to_status, record.reviewer_staff_id, True, note
        )

    if request.action == "resume":
        # The submitter answers the question, or the reviewer resumes after a call.
        if not (is_submitter or is_reviewer):
            raise NotTheReviewer()
        return TransitionPlan(
            record.status, to_status, record.reviewer_staff_id, False, note
        )

    # release, request_info and the decisions belong to the reviewer only.
    if not is_reviewer:
        raise NotTheReviewer()
    if request.action == "release":
        return TransitionPlan(record.status, to_status, None, False, note)
    if request.action == "request_info":
        if note is None:
            raise MissingRequiredField("note")
        return TransitionPlan(record.status, to_status, actor.staff_id, False, note)

    # Decisions.
    if note is None:
        raise MissingRequiredField("note")
    conditions = _clean(request.conditions)
    ripd_reference = _clean(request.ripd_reference)
    if request.action == "reject":
        if request.rejection_reason is None:
            raise MissingRequiredField("rejection_reason")
        return TransitionPlan(
            record.status,
            to_status,
            actor.staff_id,
            True,
            note,
            decision_note=note,
            rejection_reason=request.rejection_reason,
        )
    if request.action == "approve_with_conditions" and conditions is None:
        raise MissingRequiredField("conditions")
    if record.ripd_required and ripd_reference is None:
        raise MissingRequiredField("ripd_reference")
    return TransitionPlan(
        record.status,
        to_status,
        actor.staff_id,
        True,
        note,
        decision_note=note,
        conditions=conditions if request.action == "approve_with_conditions" else None,
        ripd_reference=ripd_reference,
    )


def paused_seconds(events: tuple[SolutionEvent, ...], now: datetime) -> float:
    """Total time spent in ``needs_info``, from the audit trail."""

    total = 0.0
    paused_since: datetime | None = None
    for event in sorted(events, key=lambda item: item.created_at):
        if event.to_status == "needs_info" and paused_since is None:
            paused_since = event.created_at
        elif event.from_status == "needs_info" and paused_since is not None:
            total += (event.created_at - paused_since).total_seconds()
            paused_since = None
    if paused_since is not None:
        total += max(0.0, (now - paused_since).total_seconds())
    return total


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text[:NOTE_MAX_LENGTH]
