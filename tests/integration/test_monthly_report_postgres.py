"""Migration 020 against a real PostgreSQL: deadline policy frozen at opening,
late close requiring a reason, and the monthly report query.

Runs only with ``PHASE0_TEST_DATABASE_URL`` (``docker-compose.test.yml``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.operational import ChatAuditInput, OperationalRepository
from app.db.runtime import DatabaseRuntime
from app.support.monthly_report import COLUMNS, build_report_rows, month_bounds
from app.support.repository import SupportCaseRepository
from app.support.transitions import LateReasonRequired, SupportCaseTransitionService

DATABASE_URL = os.getenv("PHASE0_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PHASE0_TEST_DATABASE_URL to run PostgreSQL integration tests",
)
TZ = "America/Sao_Paulo"


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    if not DATABASE_URL:
        return
    env = {**os.environ, "DATABASE_URL": DATABASE_URL}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.migrate", "apply"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, "migrations failed in disposable test database"


@pytest.fixture
def runtime():
    assert DATABASE_URL
    settings = SimpleNamespace(
        persistence_backend="postgres",
        web_auth_storage_backend="disabled",
        enable_outbox_ingress=False,
        session_domain_store_backend="memory",
        database_url=DATABASE_URL,
        database_pool_min_size=1,
        database_pool_max_size=2,
        database_connect_timeout_seconds=5,
        database_query_timeout_seconds=10,
        retrieval_backend="lexical",
        domains_path=Path("domains"),
        persistence_hash_secret="it-persistence-secret",
        support_sla_minutes_urgent=60,
        support_sla_minutes_high=120,
        support_sla_minutes_normal=480,
        support_sla_minutes_low=1440,
    )
    db = DatabaseRuntime(settings)
    db.open()
    with db.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO domains (name, display_name)
                SELECT %s, %s
                WHERE NOT EXISTS (SELECT 1 FROM domains WHERE name = %s)
                """,
                ("concessoes-manutencao", "Manutencao (demo)", "concessoes-manutencao"),
            )
    try:
        yield db
    finally:
        db.close()


def _open_case(runtime: DatabaseRuntime, *, priority: str, reasons: list[str]) -> str:
    # A whole UUID, never a hex slice: about 1 slice in 110 comes out all
    # digits, and safe_feedback_identifier rejects 10 digits in a row as a
    # phone number, so record_chat fell back to persistence_unavailable.
    request_id = str(uuid4())
    result = OperationalRepository(runtime).record_chat(
        ChatAuditInput(
            request_id=request_id,
            domain="concessoes-manutencao",
            session_id=None,
            question="Tem fio exposto no abrigo ABR-1104 (caso ficticio de teste)",
            answer="resposta de teste",
            confidence=0.9,
            escalated=True,
            handoff_reasons=reasons,
            references=[],
            error_code=None,
            channel="web",
            requires_human_queue=True,
            case_priority=priority,
        )
    )
    assert result.persistence_status == "persisted"
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM support_cases WHERE request_id = %s", (request_id,))
            return str(cursor.fetchone()[0])


def _case_columns(runtime: DatabaseRuntime, case_id: str) -> tuple:
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT sla_minutes, sla_basis, late_reason, status FROM support_cases WHERE id = %s",
                (case_id,),
            )
            return cursor.fetchone()


def _shift_opened_at(runtime: DatabaseRuntime, case_id: str, hours: float) -> None:
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE support_cases SET opened_at = now() - %s WHERE id = %s",
                (timedelta(hours=hours), case_id),
            )


def _staff(runtime: DatabaseRuntime) -> str:
    staff_id = str(uuid4())
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO staff_members (id, phone_hash, phone_last4, display_name, status)
                VALUES (%s, %s, '0000', 'Atendente Teste 020', 'active')
                """,
                (staff_id, f"it-020-{staff_id}"),
            )
    return staff_id


def test_record_chat_freezes_the_domain_policy(runtime) -> None:
    case_id = _open_case(runtime, priority="urgent", reasons=["risco_seguranca"])
    sla_minutes, sla_basis, late_reason, status = _case_columns(runtime, case_id)
    assert sla_minutes == 240
    assert "demo" in sla_basis.lower()
    assert late_reason is None
    assert status == "open"


def test_late_close_requires_and_stores_a_reason(runtime) -> None:
    case_id = _open_case(runtime, priority="urgent", reasons=["risco_seguranca"])
    staff_id = _staff(runtime)
    service = SupportCaseTransitionService(runtime)
    service.apply(case_id=case_id, action="claim", actor_staff_id=staff_id, note=None)
    _shift_opened_at(runtime, case_id, hours=5)

    with pytest.raises(LateReasonRequired):
        service.apply(case_id=case_id, action="close", actor_staff_id=staff_id, note=None)
    assert _case_columns(runtime, case_id)[3] == "in_progress"

    result = service.apply(
        case_id=case_id,
        action="close",
        actor_staff_id=staff_id,
        note=None,
        late_reason="aguardando_peca",
    )
    assert result.late_reason == "aguardando_peca"
    assert _case_columns(runtime, case_id)[2:] == ("aguardando_peca", "closed")


def test_database_rejects_a_free_text_late_reason(runtime) -> None:
    import psycopg

    from app.core.errors import DatabaseUnavailableError

    case_id = _open_case(runtime, priority="normal", reasons=["defeito_geral"])
    # The runtime wraps driver errors; the cause must be the CHECK constraint.
    with pytest.raises(DatabaseUnavailableError) as raised:
        with runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE support_cases SET late_reason = 'texto livre' WHERE id = %s",
                    (case_id,),
                )
    assert isinstance(raised.value.__cause__, psycopg.errors.CheckViolation)
    assert "support_cases_late_reason_check" in str(raised.value.__cause__)


def test_monthly_report_reads_the_frozen_policy_and_outcome(runtime) -> None:
    case_id = _open_case(runtime, priority="high", reasons=["tela_inoperante"])
    repository = SupportCaseRepository(runtime)
    now = repository.database_now()
    start, end = month_bounds(now.astimezone().strftime("%Y-%m"), TZ)
    start -= timedelta(days=1)
    end += timedelta(days=1)

    cases, db_now, truncated = repository.list_cases_opened_between(
        start=start, end=end, domain="concessoes-manutencao"
    )
    assert not truncated
    mine = [case for case in cases if case.case_id == case_id]
    assert len(mine) == 1
    assert mine[0].sla_minutes == 1440

    [row] = [
        dict(zip(COLUMNS, values))
        for values in build_report_rows(
            mine, db_now=db_now, settings=runtime.settings, domain_sla={}, timezone_name=TZ
        )
    ]
    assert row["prazo_minutos"] == "1440"
    assert row["resultado"] == "em_aberto_no_prazo"
    assert row["motivos"] == "tela_inoperante"
