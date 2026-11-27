"""Migration 021 against a real PostgreSQL: the intake flow through
``PostgresSolutionRepository``, the CHECK constraints and the demo seed.

Runs only with ``PHASE0_TEST_DATABASE_URL`` (``docker-compose.test.yml``).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai_intake.models import SolutionSubmission
from app.ai_intake.policy import load_policy
from app.ai_intake.repository import PostgresSolutionRepository
from app.ai_intake.service import AiIntakeService
from app.ai_intake.workflow import (
    Actor,
    InvalidTransition,
    MissingRequiredField,
    SelfReviewForbidden,
    TransitionRequest,
)
from app.core.errors import DatabaseUnavailableError
from app.db.runtime import DatabaseRuntime

DATABASE_URL = os.getenv("PHASE0_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PHASE0_TEST_DATABASE_URL to run PostgreSQL integration tests",
)

SUBMISSION = SolutionSubmission(
    name="Contagem de audiencia por camera (teste ficticio)",
    business_unit="Midia digital",
    purpose="Estimar fluxo de pessoas sem identificar ninguem; contato teste@exemplo.com",
    owner_name="Gestora Demo",
    owner_role="Gerente de produto",
    solution_type="fornecedor",
    hosting_region="uniao_europeia",
    data_categories=("biometrico_imagem",),
    data_subjects=("cidadao",),
    legal_basis="legitimo_interesse",
    automated_decision=False,
    external_facing=False,
    human_in_loop=True,
)


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
    )
    db = DatabaseRuntime(settings)
    db.open()
    try:
        yield db
    finally:
        db.close()


def _staff(runtime: DatabaseRuntime, name: str) -> Actor:
    staff_id = str(uuid4())
    with runtime.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO staff_members (id, phone_hash, phone_last4, display_name, status)
                VALUES (%s, %s, '0000', %s, 'active')
                """,
                (staff_id, f"it-intake-{staff_id}", name),
            )
    return Actor(staff_id, name)


def test_full_flow_against_postgres(runtime: DatabaseRuntime) -> None:
    service = AiIntakeService(load_policy(), PostgresSolutionRepository(runtime))
    submitter = _staff(runtime, "Pessoa da BU (teste)")
    reviewer = _staff(runtime, "Revisor (teste)")

    created = service.submit(SUBMISSION, submitter)
    record = created.record
    assert re.fullmatch(r"IA-\d{4}-\d{4,}", record.reference)
    assert record.criticality == "alta"
    assert record.ripd_required is True
    assert record.sla_minutes == 15 * 24 * 60
    assert "teste@exemplo.com" not in record.submission.purpose
    assert record.submitted_by_name == "Pessoa da BU (teste)"

    with pytest.raises(SelfReviewForbidden):
        service.transition(record.id, TransitionRequest("claim"), submitter)
    service.transition(record.id, TransitionRequest("claim"), reviewer)
    with pytest.raises(InvalidTransition):
        service.transition(record.id, TransitionRequest("claim"), _staff(runtime, "Outro (teste)"))

    service.transition(record.id, TransitionRequest("request_info", note="Falta o RIPD"), reviewer)
    service.transition(record.id, TransitionRequest("resume"), submitter)
    with pytest.raises(MissingRequiredField):
        service.transition(record.id, TransitionRequest("approve", note="Ok"), reviewer)

    approved = service.transition(
        record.id,
        TransitionRequest("approve", note="Ok com RIPD", ripd_reference="RIPD-TESTE-1"),
        reviewer,
    )
    assert approved.record.status == "approved"
    assert approved.record.decided_at is not None
    assert approved.record.reviewer_name == "Revisor (teste)"
    assert [event.action for event in approved.record.events] == [
        "submit",
        "claim",
        "request_info",
        "resume",
        "approve",
    ]
    assert approved.record.events[2].note == "Falta o RIPD"

    listed = {view.record.id: view for view in service.queue()}
    assert listed[record.id].record.events[-1].action == "approve"


def test_policy_change_never_rewrites_a_stored_request(runtime: DatabaseRuntime) -> None:
    repository = PostgresSolutionRepository(runtime)
    submitter = _staff(runtime, "Pessoa da BU (teste)")
    view = AiIntakeService(load_policy(), repository).submit(SUBMISSION, submitter)

    stricter = load_policy().model_copy(update={"sla_days": {"baixa": 1, "media": 1, "alta": 1}})
    again = AiIntakeService(stricter, repository).get(view.record.id)

    assert again.record.sla_minutes == 15 * 24 * 60
    assert again.sla.deadline_at == view.sla.deadline_at


def test_check_constraints_refuse_values_outside_the_closed_lists(
    runtime: DatabaseRuntime,
) -> None:
    repository = PostgresSolutionRepository(runtime)
    submitter = _staff(runtime, "Pessoa da BU (teste)")
    assessment = load_policy().assess(SUBMISSION)

    # Bypass the service validation on purpose: the database is the last line.
    with pytest.raises(DatabaseUnavailableError):
        repository.create(
            submission=replace(SUBMISSION, data_categories=("dna",)),
            assessment=assessment,
            sla_minutes=60,
            sla_basis="teste",
            actor=submitter,
        )


def test_demo_seed_creates_and_resets_only_its_rows(runtime: DatabaseRuntime) -> None:
    from scripts import seed_demo_ai_solutions as seed

    secret = "it-intake-identity-secret"
    rows = seed.seed(DATABASE_URL, secret)
    assert len(rows) == len(seed.DEMO_SOLUTIONS)
    assert {row["criticality"] for row in rows} == {"baixa", "media", "alta"}
    colors = {row["color"] for row in rows if row["status"] not in {"rejected"}}
    assert {"red", "yellow", "pausado"} <= colors

    # Idempotent: a second run replaces the seed rows, never duplicates them.
    assert len(seed.seed(DATABASE_URL, secret)) == len(seed.DEMO_SOLUTIONS)
    assert seed.reset(runtime, secret) == len(seed.DEMO_SOLUTIONS)
    assert seed.reset(runtime, secret) == 0
