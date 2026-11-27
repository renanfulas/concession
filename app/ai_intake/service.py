"""Servico do intake: submissao, fila com prazo e transicoes.

Junta as pecas que ja existem no nucleo: mascaramento antes de persistir
(``sanitize_for_persistence``), motor de SLA e ordem de atencao do console
(``app/support/sla.py``) e a politica deterministica de criticidade.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from app.ai_intake.models import (
    DATA_CATEGORIES,
    DATA_SUBJECTS,
    FINAL_STATUSES,
    HOSTING_REGIONS,
    LEGAL_BASES,
    SOLUTION_TYPES,
    SolutionRecord,
    SolutionSubmission,
)
from app.ai_intake.policy import LEVEL_TO_PRIORITY, IntakePolicy
from app.ai_intake.repository import SolutionRepository
from app.ai_intake.workflow import Actor, TransitionRequest, paused_seconds
from app.core.persistence_sanitize import sanitize_for_persistence
from app.support.sla import SlaAssessment, attention_sort_key, compute_sla, frozen_case_sla

TEXT_LIMITS = {
    "name": 120,
    "business_unit": 80,
    "purpose": 2000,
    "owner_name": 120,
    "owner_role": 120,
    "vendor": 120,
    "model_provider": 80,
    "model_name": 80,
}
REQUIRED_TEXT = ("name", "business_unit", "purpose", "owner_name", "owner_role")
# The SLA engine pauses on this status; needs_info maps onto it.
_ENGINE_PAUSED_STATUS = "waiting_customer"


class InvalidSubmission(ValueError):
    """A submission the API must answer with 422; ``field`` names the culprit."""

    def __init__(self, field: str) -> None:
        super().__init__(f"invalid field: {field}")
        self.field = field


@dataclass(frozen=True)
class SolutionView:
    record: SolutionRecord
    sla: SlaAssessment
    paused_seconds: float
    outcome: str


class AiIntakeService:
    def __init__(self, policy: IntakePolicy, repository: SolutionRepository) -> None:
        self.policy = policy
        self.repository = repository

    def submit(self, submission: SolutionSubmission, actor: Actor) -> SolutionView:
        clean = _validated(submission)
        assessment = self.policy.assess(clean)
        record = self.repository.create(
            submission=clean,
            assessment=assessment,
            sla_minutes=self.policy.sla_minutes(assessment.level),
            sla_basis=self.policy.basis,
            actor=actor,
        )
        return self._view(record, record.submitted_at)

    def get(self, solution_id: str) -> SolutionView:
        record, db_now = self.repository.get(solution_id)
        return self._view(record, db_now)

    def queue(self) -> list[SolutionView]:
        """Open requests by deadline pressure first, decided ones after, newest first."""

        records, db_now = self.repository.list()
        views = [self._view(record, db_now) for record in records]
        open_views = [view for view in views if view.record.status not in FINAL_STATUSES]
        done = [view for view in views if view.record.status in FINAL_STATUSES]
        open_views.sort(
            key=lambda view: attention_sort_key(
                priority=LEVEL_TO_PRIORITY[view.record.criticality],
                opened_at=view.record.submitted_at,
                sla=view.sla,
                case_id=view.record.id,
            )
        )
        done.sort(key=lambda view: view.record.decided_at or view.record.updated_at, reverse=True)
        return [*open_views, *done]

    def transition(
        self, solution_id: str, request: TransitionRequest, actor: Actor
    ) -> SolutionView:
        clean = replace(
            request,
            note=sanitize_for_persistence(request.note),
            conditions=sanitize_for_persistence(request.conditions),
            ripd_reference=sanitize_for_persistence(request.ripd_reference),
        )
        record = self.repository.transition(solution_id, clean, actor)
        return self._view(record, record.updated_at)

    def _view(self, record: SolutionRecord, db_now: datetime) -> SolutionView:
        priority = LEVEL_TO_PRIORITY[record.criticality]
        # A decided request is assessed at the moment of the decision.
        now = record.decided_at if record.decided_at is not None else db_now
        paused = paused_seconds(record.events, now)
        status = _ENGINE_PAUSED_STATUS if record.status == "needs_info" else record.status
        sla = compute_sla(
            priority,
            record.submitted_at,
            status,
            now,
            None,
            waiting_seconds=paused,
            domain_sla=frozen_case_sla(priority, record.sla_minutes, record.sla_basis, None),
        )
        return SolutionView(
            record=record, sla=sla, paused_seconds=paused, outcome=_outcome(record, sla)
        )


def _outcome(record: SolutionRecord, sla: SlaAssessment) -> str:
    late = sla.elapsed_ratio > 1.0
    if record.status == "withdrawn":
        return "retirado"
    if record.status in FINAL_STATUSES:
        return "decidido_fora_do_prazo" if late else "decidido_no_prazo"
    return "em_analise_atrasado" if late else "em_analise_no_prazo"


def _validated(submission: SolutionSubmission) -> SolutionSubmission:
    values: dict[str, object] = {}
    for field, limit in TEXT_LIMITS.items():
        raw = getattr(submission, field)
        text = " ".join(str(raw).split()) if raw is not None else ""
        if not text:
            if field in REQUIRED_TEXT:
                raise InvalidSubmission(field)
            values[field] = None
            continue
        if len(text) > limit:
            raise InvalidSubmission(field)
        values[field] = sanitize_for_persistence(text)

    _closed("solution_type", submission.solution_type, SOLUTION_TYPES)
    _closed("hosting_region", submission.hosting_region, HOSTING_REGIONS)
    _closed("legal_basis", submission.legal_basis, LEGAL_BASES)
    categories = tuple(dict.fromkeys(submission.data_categories))
    if not categories or any(item not in DATA_CATEGORIES for item in categories):
        raise InvalidSubmission("data_categories")
    if "nenhum" in categories and len(categories) > 1:
        # "no personal data" next to a personal category is a contradiction.
        raise InvalidSubmission("data_categories")
    subjects = tuple(dict.fromkeys(submission.data_subjects))
    if any(item not in DATA_SUBJECTS for item in subjects):
        raise InvalidSubmission("data_subjects")
    if categories != ("nenhum",) and submission.legal_basis == "nao_se_aplica":
        # Personal data always needs a legal basis, even "a_definir".
        raise InvalidSubmission("legal_basis")

    return replace(
        submission,
        data_categories=categories,
        data_subjects=subjects,
        **values,
    )


def _closed(field: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise InvalidSubmission(field)


def create_ai_intake_service(settings, database_runtime=None) -> AiIntakeService:
    """PostgreSQL when persistence is on (migration 021); memory otherwise.

    Same rule as the console runtime (``create_support_console_runtime``), so
    the staff ids the intake references always live in the same store.
    """

    from app.ai_intake.policy import load_policy
    from app.ai_intake.repository import (
        InMemorySolutionRepository,
        PostgresSolutionRepository,
    )

    use_postgres = (
        settings.persistence_backend == "postgres" and database_runtime is not None
    )
    repository = (
        PostgresSolutionRepository(database_runtime)
        if use_postgres
        else InMemorySolutionRepository()
    )
    return AiIntakeService(load_policy(settings.ai_intake_policy_path), repository)
