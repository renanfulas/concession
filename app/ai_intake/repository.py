"""Persistencia do intake: uma interface, duas implementacoes.

``PostgresSolutionRepository`` e a de verdade (migration 021). A
``InMemorySolutionRepository`` serve aos testes e a demo local sem banco; nao e
duravel e diz isso em ``durable``. As duas aplicam a transicao do mesmo jeito:
leem o registro (travado, no PostgreSQL), chamam ``plan_transition`` e gravam
o plano junto com o evento de auditoria.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Callable, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.ai_intake.models import (
    CriticalityAssessment,
    SolutionEvent,
    SolutionRecord,
    SolutionSubmission,
)
from app.ai_intake.workflow import (
    Actor,
    SolutionNotFound,
    TransitionPlan,
    TransitionRequest,
    plan_transition,
)
from app.db.runtime import DatabaseRuntime

LIST_CAP = 500
REFERENCE_TIMEZONE = "America/Sao_Paulo"


class SolutionRepository(Protocol):
    durable: bool

    def create(
        self,
        *,
        submission: SolutionSubmission,
        assessment: CriticalityAssessment,
        sla_minutes: int,
        sla_basis: str,
        actor: Actor,
    ) -> SolutionRecord: ...

    def get(self, solution_id: str) -> tuple[SolutionRecord, datetime]: ...

    def list(self) -> tuple[list[SolutionRecord], datetime]: ...

    def transition(
        self, solution_id: str, request: TransitionRequest, actor: Actor
    ) -> SolutionRecord: ...


# --------------------------------------------------------------------------- #
# Memoria
# --------------------------------------------------------------------------- #


class InMemorySolutionRepository:
    durable = False

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._records: dict[str, SolutionRecord] = {}
        self._sequence = 0
        self._lock = threading.Lock()

    def create(
        self,
        *,
        submission: SolutionSubmission,
        assessment: CriticalityAssessment,
        sla_minutes: int,
        sla_basis: str,
        actor: Actor,
    ) -> SolutionRecord:
        with self._lock:
            now = self._now()
            self._sequence += 1
            year = now.astimezone(ZoneInfo(REFERENCE_TIMEZONE)).year
            record = SolutionRecord(
                id=str(uuid4()),
                reference=f"IA-{year}-{self._sequence:04d}",
                submission=submission,
                criticality=assessment.level,
                criticality_reasons=assessment.reasons,
                ripd_required=assessment.ripd_required,
                status="submitted",
                sla_minutes=sla_minutes,
                sla_basis=sla_basis,
                submitted_by=actor.staff_id,
                submitted_by_name=actor.display_name,
                submitted_at=now,
                updated_at=now,
                events=(
                    SolutionEvent(
                        action="submit",
                        from_status=None,
                        to_status="submitted",
                        actor_staff_id=actor.staff_id,
                        actor_display_name=actor.display_name,
                        note=None,
                        created_at=now,
                    ),
                ),
            )
            self._records[record.id] = record
            return record

    def get(self, solution_id: str) -> tuple[SolutionRecord, datetime]:
        record = self._records.get(solution_id)
        if record is None:
            raise SolutionNotFound()
        return record, self._now()

    def list(self) -> tuple[list[SolutionRecord], datetime]:
        records = sorted(self._records.values(), key=lambda item: item.submitted_at)
        return records[:LIST_CAP], self._now()

    def transition(
        self, solution_id: str, request: TransitionRequest, actor: Actor
    ) -> SolutionRecord:
        with self._lock:
            record = self._records.get(solution_id)
            if record is None:
                raise SolutionNotFound()
            plan = plan_transition(record, request, actor)
            now = self._now()
            reviewer_name = (
                actor.display_name
                if plan.reviewer_staff_id == actor.staff_id
                else record.reviewer_name if plan.reviewer_staff_id else None
            )
            updated = replace(
                record,
                status=plan.to_status,
                reviewer_staff_id=plan.reviewer_staff_id,
                reviewer_name=reviewer_name,
                updated_at=now,
                decided_at=now if plan.decided else record.decided_at,
                decision_note=plan.decision_note or record.decision_note,
                conditions=plan.conditions or record.conditions,
                rejection_reason=plan.rejection_reason or record.rejection_reason,
                ripd_reference=plan.ripd_reference or record.ripd_reference,
                events=(*record.events, _event(plan, request, actor, now)),
            )
            self._records[solution_id] = updated
            return updated


def _event(
    plan: TransitionPlan, request: TransitionRequest, actor: Actor, now: datetime
) -> SolutionEvent:
    return SolutionEvent(
        action=request.action,
        from_status=plan.from_status,
        to_status=plan.to_status,
        actor_staff_id=actor.staff_id,
        actor_display_name=actor.display_name,
        note=plan.note,
        created_at=now,
    )


# --------------------------------------------------------------------------- #
# PostgreSQL
# --------------------------------------------------------------------------- #

_SELECT = """
    SELECT s.id, s.reference, s.name, s.business_unit, s.purpose,
           s.owner_name, s.owner_role, s.solution_type, s.vendor,
           s.model_provider, s.model_name, s.hosting_region,
           s.data_categories, s.data_subjects, s.legal_basis,
           s.automated_decision, s.external_facing, s.human_in_loop,
           s.criticality, s.criticality_reasons, s.ripd_required, s.status,
           s.sla_minutes, s.sla_basis, s.submitted_by, submitter.display_name,
           s.submitted_at, s.updated_at, s.reviewer_staff_id,
           reviewer.display_name, s.decided_at, s.decision_note, s.conditions,
           s.rejection_reason, s.ripd_reference
    FROM ai_solutions s
    JOIN staff_members submitter ON submitter.id = s.submitted_by
    LEFT JOIN staff_members reviewer ON reviewer.id = s.reviewer_staff_id
"""


class PostgresSolutionRepository:
    durable = True

    def __init__(self, runtime: DatabaseRuntime) -> None:
        self.runtime = runtime

    def create(
        self,
        *,
        submission: SolutionSubmission,
        assessment: CriticalityAssessment,
        sla_minutes: int,
        sla_basis: str,
        actor: Actor,
    ) -> SolutionRecord:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ai_solutions (
                        reference, name, business_unit, purpose, owner_name,
                        owner_role, solution_type, vendor, model_provider,
                        model_name, hosting_region, data_categories, data_subjects,
                        legal_basis, automated_decision, external_facing,
                        human_in_loop, criticality, criticality_reasons,
                        ripd_required, sla_minutes, sla_basis, submitted_by
                    ) VALUES (
                        'IA-' || to_char(now() AT TIME ZONE %s, 'YYYY') || '-'
                            || lpad(nextval('ai_solution_reference_seq')::text, 4, '0'),
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        REFERENCE_TIMEZONE,
                        submission.name,
                        submission.business_unit,
                        submission.purpose,
                        submission.owner_name,
                        submission.owner_role,
                        submission.solution_type,
                        submission.vendor,
                        submission.model_provider,
                        submission.model_name,
                        submission.hosting_region,
                        list(submission.data_categories),
                        list(submission.data_subjects),
                        submission.legal_basis,
                        submission.automated_decision,
                        submission.external_facing,
                        submission.human_in_loop,
                        assessment.level,
                        list(assessment.reasons),
                        assessment.ripd_required,
                        sla_minutes,
                        sla_basis,
                        actor.staff_id,
                    ),
                )
                solution_id = str(cursor.fetchone()[0])
                cursor.execute(
                    """
                    INSERT INTO ai_solution_events
                        (solution_id, actor_staff_id, action, from_status, to_status)
                    VALUES (%s, %s, 'submit', NULL, 'submitted')
                    """,
                    (solution_id, actor.staff_id),
                )
                record, _ = self._load(cursor, solution_id, lock=False)
                return record

    def get(self, solution_id: str) -> tuple[SolutionRecord, datetime]:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                return self._load(cursor, solution_id, lock=False)

    def list(self) -> tuple[list[SolutionRecord], datetime]:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT now()")
                db_now = cursor.fetchone()[0]
                cursor.execute(_SELECT + " ORDER BY s.submitted_at LIMIT %s", (LIST_CAP,))
                rows = cursor.fetchall()
                events = self._events(cursor, [str(row[0]) for row in rows])
                return [_record(row, events.get(str(row[0]), ())) for row in rows], db_now

    def transition(
        self, solution_id: str, request: TransitionRequest, actor: Actor
    ) -> SolutionRecord:
        with self.runtime.transaction() as connection:
            with connection.cursor() as cursor:
                record, _ = self._load(cursor, solution_id, lock=True)
                plan = plan_transition(record, request, actor)
                cursor.execute(
                    """
                    UPDATE ai_solutions
                    SET status = %s,
                        reviewer_staff_id = %s,
                        updated_at = now(),
                        decided_at = CASE WHEN %s THEN now() ELSE decided_at END,
                        decision_note = COALESCE(%s, decision_note),
                        conditions = COALESCE(%s, conditions),
                        rejection_reason = COALESCE(%s, rejection_reason),
                        ripd_reference = COALESCE(%s, ripd_reference)
                    WHERE id = %s AND status = %s
                    """,
                    (
                        plan.to_status,
                        plan.reviewer_staff_id,
                        plan.decided,
                        plan.decision_note,
                        plan.conditions,
                        plan.rejection_reason,
                        plan.ripd_reference,
                        solution_id,
                        plan.from_status,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO ai_solution_events (
                        solution_id, actor_staff_id, action, from_status,
                        to_status, note_sanitized
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        solution_id,
                        actor.staff_id,
                        request.action,
                        plan.from_status,
                        plan.to_status,
                        plan.note,
                    ),
                )
                updated, _ = self._load(cursor, solution_id, lock=False)
                return updated

    def _load(
        self, cursor: Any, solution_id: str, *, lock: bool
    ) -> tuple[SolutionRecord, datetime]:
        cursor.execute("SELECT now()")
        db_now = cursor.fetchone()[0]
        # FOR UPDATE OF s: lock the solution row only, not the staff rows joined.
        suffix = " WHERE s.id = %s" + (" FOR UPDATE OF s" if lock else "")
        cursor.execute(_SELECT + suffix, (solution_id,))
        row = cursor.fetchone()
        if row is None:
            raise SolutionNotFound()
        events = self._events(cursor, [solution_id])
        return _record(row, events.get(solution_id, ())), db_now

    @staticmethod
    def _events(cursor: Any, solution_ids: list[str]) -> dict[str, tuple[SolutionEvent, ...]]:
        if not solution_ids:
            return {}
        cursor.execute(
            """
            SELECT e.solution_id, e.action, e.from_status, e.to_status,
                   e.actor_staff_id, m.display_name, e.note_sanitized, e.created_at
            FROM ai_solution_events e
            JOIN staff_members m ON m.id = e.actor_staff_id
            WHERE e.solution_id = ANY(%s::uuid[])
            ORDER BY e.created_at, e.id
            """,
            (solution_ids,),
        )
        grouped: dict[str, list[SolutionEvent]] = {}
        for row in cursor.fetchall():
            grouped.setdefault(str(row[0]), []).append(
                SolutionEvent(
                    action=str(row[1]),
                    from_status=str(row[2]) if row[2] else None,
                    to_status=str(row[3]),
                    actor_staff_id=str(row[4]),
                    actor_display_name=str(row[5]),
                    note=row[6],
                    created_at=row[7],
                )
            )
        return {key: tuple(value) for key, value in grouped.items()}


def _record(row: tuple, events: tuple[SolutionEvent, ...]) -> SolutionRecord:
    submission = SolutionSubmission(
        name=row[2],
        business_unit=row[3],
        purpose=row[4],
        owner_name=row[5],
        owner_role=row[6],
        solution_type=row[7],
        vendor=row[8],
        model_provider=row[9],
        model_name=row[10],
        hosting_region=row[11],
        data_categories=tuple(row[12] or ()),
        data_subjects=tuple(row[13] or ()),
        legal_basis=row[14],
        automated_decision=bool(row[15]),
        external_facing=bool(row[16]),
        human_in_loop=bool(row[17]),
    )
    return SolutionRecord(
        id=str(row[0]),
        reference=str(row[1]),
        submission=submission,
        criticality=str(row[18]),
        criticality_reasons=tuple(row[19] or ()),
        ripd_required=bool(row[20]),
        status=str(row[21]),
        sla_minutes=int(row[22]),
        sla_basis=str(row[23]),
        submitted_by=str(row[24]),
        submitted_by_name=str(row[25]),
        submitted_at=row[26],
        updated_at=row[27],
        reviewer_staff_id=str(row[28]) if row[28] else None,
        reviewer_name=str(row[29]) if row[29] else None,
        decided_at=row[30],
        decision_note=row[31],
        conditions=row[32],
        rejection_reason=row[33],
        ripd_reference=row[34],
        events=events,
    )
