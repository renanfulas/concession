"""Intake de solucoes de IA: politica, fluxo, prazo e contrato com o banco.

Tudo aqui roda sem banco, contra o repositorio em memoria; o mesmo fluxo
contra PostgreSQL real fica em ``tests/integration/test_ai_intake_postgres.py``.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai_intake import models
from app.ai_intake.models import SolutionSubmission
from app.ai_intake.policy import IntakePolicy, load_policy
from app.ai_intake.repository import InMemorySolutionRepository
from app.ai_intake.service import AiIntakeService, InvalidSubmission
from app.ai_intake.workflow import (
    Actor,
    InvalidTransition,
    MissingRequiredField,
    NotTheReviewer,
    NotTheSubmitter,
    SelfReviewForbidden,
    TransitionRequest,
)
from app.db.schema_contract import CONTRACT_MIGRATION, REQUIRED_COLUMNS

MIGRATION = Path("migrations") / "021_ai_solution_intake.sql"
START = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
SUBMITTER = Actor("00000000-0000-0000-0000-00000000000a", "Pessoa da BU (demo)")
REVIEWER = Actor("00000000-0000-0000-0000-00000000000b", "Revisor de IA (demo)")
OTHER = Actor("00000000-0000-0000-0000-00000000000c", "Outra pessoa (demo)")

BASE = SolutionSubmission(
    name="Previsao de falha de paineis",
    business_unit="Operacoes",
    purpose="Prever falha de painel digital a partir da telemetria do equipamento.",
    owner_name="Gestor Demo",
    owner_role="Gerente de operacoes",
    solution_type="interno",
    hosting_region="brasil",
    data_categories=("nenhum",),
    legal_basis="nao_se_aplica",
    automated_decision=False,
    external_facing=False,
    human_in_loop=True,
)


@pytest.fixture
def clock() -> list[datetime]:
    return [START]


@pytest.fixture
def service(clock: list[datetime]) -> AiIntakeService:
    return AiIntakeService(load_policy(), InMemorySolutionRepository(now=lambda: clock[0]))


def _personal(**overrides) -> SolutionSubmission:
    values = {"data_categories": ("pessoal",), "legal_basis": "legitimo_interesse"}
    values.update(overrides)
    return replace(BASE, **values)


# --------------------------------------------------------------------------- #
# Politica de criticidade
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("submission", "level", "reasons"),
    [
        (BASE, "baixa", ()),
        (_personal(), "media", ("dado_pessoal",)),
        (
            _personal(external_facing=True),
            "media",
            ("dado_pessoal_uso_externo", "dado_pessoal"),
        ),
        (
            replace(BASE, external_facing=True, human_in_loop=False),
            "media",
            ("uso_externo_sem_revisao_humana",),
        ),
        (
            _personal(data_categories=("biometrico_imagem",)),
            "alta",
            ("dado_sensivel_ou_imagem", "dado_pessoal"),
        ),
        (
            _personal(automated_decision=True),
            "alta",
            ("decisao_automatizada", "dado_pessoal"),
        ),
        (
            _personal(hosting_region="estados_unidos"),
            "alta",
            ("transferencia_internacional", "dado_pessoal"),
        ),
        # Sem dado pessoal, decisao automatizada e hospedagem fora nao pesam.
        (
            replace(BASE, automated_decision=True, hosting_region="estados_unidos"),
            "baixa",
            (),
        ),
    ],
)
def test_policy_classifies_by_rule(
    submission: SolutionSubmission, level: str, reasons: tuple[str, ...]
) -> None:
    assessment = load_policy().assess(submission)

    assert assessment.level == level
    assert assessment.reasons == reasons
    assert assessment.ripd_required is (level == "alta")


def test_demo_policy_is_marked_and_has_increasing_deadlines() -> None:
    policy = load_policy()

    assert "demo" in policy.basis.lower()
    assert policy.sla_minutes("baixa") < policy.sla_minutes("media") < policy.sla_minutes("alta")


@pytest.mark.parametrize(
    "broken",
    [
        {"rules": [{"id": "x", "level": "critica", "reason": "r", "when": {"external_facing": True}}]},
        {"rules": [{"id": "x", "level": "alta", "reason": "r", "when": {"data_categories_any": ["dna"]}}]},
        {"rules": [{"id": "x", "level": "alta", "reason": "r", "when": {}}]},
        {"sla_days": {"baixa": 5, "media": 10}},
        {"ripd_required_for": ["maxima"]},
        {"surprise": True},
    ],
)
def test_policy_rejects_invalid_config(broken: dict) -> None:
    raw = {"version": 1, "basis": "demo", "sla_days": {"baixa": 5, "media": 10, "alta": 15}}
    raw.update(broken)

    with pytest.raises(ValidationError):
        IntakePolicy.model_validate(raw)


# --------------------------------------------------------------------------- #
# Contrato com o banco
# --------------------------------------------------------------------------- #


def _sql_list(constraint: str) -> set[str]:
    sql = MIGRATION.read_text(encoding="utf-8")
    start = sql.index(f"CONSTRAINT {constraint}")
    end = sql.index("CONSTRAINT", start + 1) if "CONSTRAINT" in sql[start + 1 :] else len(sql)
    return set(re.findall(r"'([a-z_]+)'", sql[start:end]))


@pytest.mark.parametrize(
    ("constraint", "values"),
    [
        ("ai_solutions_solution_type_check", models.SOLUTION_TYPES),
        ("ai_solutions_hosting_region_check", models.HOSTING_REGIONS),
        ("ai_solutions_data_categories_check", models.DATA_CATEGORIES),
        ("ai_solutions_data_subjects_check", models.DATA_SUBJECTS),
        ("ai_solutions_legal_basis_check", models.LEGAL_BASES),
        ("ai_solutions_criticality_check", models.CRITICALITY_LEVELS),
        ("ai_solutions_status_check", models.STATUSES),
        ("ai_solutions_rejection_reason_check", models.REJECTION_REASONS),
    ],
)
def test_migration_checks_match_the_closed_lists(constraint: str, values: tuple[str, ...]) -> None:
    assert _sql_list(constraint) == set(values)


def test_migration_021_is_the_schema_contract() -> None:
    assert CONTRACT_MIGRATION == MIGRATION.name
    assert {"reference", "criticality", "sla_minutes", "sla_basis"} <= REQUIRED_COLUMNS["ai_solutions"]
    sql = MIGRATION.read_text(encoding="utf-8")
    # Nenhuma coluna de contato: so nome e papel do responsavel.
    assert not re.search(r"^\s+(owner_)?(email|phone|telefone|cpf)\b", sql, re.MULTILINE)


# --------------------------------------------------------------------------- #
# Submissao
# --------------------------------------------------------------------------- #


def test_submission_freezes_policy_and_masks_free_text(service: AiIntakeService) -> None:
    view = service.submit(
        _personal(purpose="Triagem de pedidos; duvidas com fulano@exemplo.com"), SUBMITTER
    )
    record = view.record

    assert re.fullmatch(r"IA-2026-\d{4}", record.reference)
    assert record.status == "submitted"
    assert record.criticality == "media"
    assert record.sla_minutes == 10 * 24 * 60
    assert "demo" in record.sla_basis.lower()
    assert "fulano@exemplo.com" not in record.submission.purpose
    assert view.sla.deadline_at == START + timedelta(days=10)
    assert [event.action for event in record.events] == ["submit"]


def test_changing_the_policy_never_rewrites_an_open_request(clock: list[datetime]) -> None:
    repository = InMemorySolutionRepository(now=lambda: clock[0])
    original = AiIntakeService(load_policy(), repository)
    view = original.submit(_personal(), SUBMITTER)

    stricter = load_policy().model_copy(update={"sla_days": {"baixa": 1, "media": 2, "alta": 3}})
    later = AiIntakeService(stricter, repository)

    assert later.get(view.record.id).sla.deadline_at == START + timedelta(days=10)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"name": "   "}, "name"),
        ({"purpose": "x" * 2001}, "purpose"),
        ({"solution_type": "planilha"}, "solution_type"),
        ({"data_categories": ()}, "data_categories"),
        ({"data_categories": ("nenhum", "pessoal")}, "data_categories"),
        ({"data_subjects": ("robo",)}, "data_subjects"),
        ({"data_categories": ("pessoal",), "legal_basis": "nao_se_aplica"}, "legal_basis"),
    ],
)
def test_invalid_submission_names_the_field(
    service: AiIntakeService, overrides: dict, field: str
) -> None:
    with pytest.raises(InvalidSubmission) as excinfo:
        service.submit(replace(BASE, **overrides), SUBMITTER)

    assert excinfo.value.field == field


# --------------------------------------------------------------------------- #
# Fluxo e separacao de funcoes
# --------------------------------------------------------------------------- #


def _claimed(service: AiIntakeService, submission: SolutionSubmission = BASE) -> str:
    solution_id = service.submit(submission, SUBMITTER).record.id
    service.transition(solution_id, TransitionRequest("claim"), REVIEWER)
    return solution_id


def test_submitter_cannot_review_their_own_solution(service: AiIntakeService) -> None:
    solution_id = service.submit(BASE, SUBMITTER).record.id

    with pytest.raises(SelfReviewForbidden):
        service.transition(solution_id, TransitionRequest("claim"), SUBMITTER)


def test_only_the_reviewer_decides(service: AiIntakeService) -> None:
    solution_id = _claimed(service)

    with pytest.raises(NotTheReviewer):
        service.transition(solution_id, TransitionRequest("approve", note="ok"), OTHER)
    with pytest.raises(NotTheReviewer):
        service.transition(solution_id, TransitionRequest("approve", note="ok"), SUBMITTER)


def test_decisions_need_note_reason_and_conditions(service: AiIntakeService) -> None:
    solution_id = _claimed(service)

    with pytest.raises(MissingRequiredField, match="note"):
        service.transition(solution_id, TransitionRequest("approve"), REVIEWER)
    with pytest.raises(MissingRequiredField, match="rejection_reason"):
        service.transition(solution_id, TransitionRequest("reject", note="nao"), REVIEWER)
    with pytest.raises(MissingRequiredField, match="conditions"):
        service.transition(
            solution_id, TransitionRequest("approve_with_conditions", note="ok"), REVIEWER
        )

    view = service.transition(
        solution_id,
        TransitionRequest("reject", note="Ja existe solucao igual", rejection_reason="duplica_solucao_existente"),
        REVIEWER,
    )
    assert view.record.status == "rejected"
    assert view.record.rejection_reason == "duplica_solucao_existente"
    assert view.record.decided_at == START


def test_high_criticality_approval_requires_the_ripd(service: AiIntakeService) -> None:
    solution_id = _claimed(service, _personal(data_categories=("biometrico_imagem",)))

    with pytest.raises(MissingRequiredField, match="ripd_reference"):
        service.transition(solution_id, TransitionRequest("approve", note="ok"), REVIEWER)

    view = service.transition(
        solution_id,
        TransitionRequest(
            "approve_with_conditions",
            note="Aprovado com anonimizacao na borda",
            conditions="Descartar imagem no equipamento; guardar so contagem",
            ripd_reference="RIPD-2026-03 (demo)",
        ),
        REVIEWER,
    )
    assert view.record.status == "approved_conditional"
    assert view.record.ripd_reference == "RIPD-2026-03 (demo)"


def test_only_the_submitter_withdraws_and_finals_are_final(service: AiIntakeService) -> None:
    solution_id = service.submit(BASE, SUBMITTER).record.id

    with pytest.raises(NotTheSubmitter):
        service.transition(solution_id, TransitionRequest("withdraw"), REVIEWER)

    service.transition(solution_id, TransitionRequest("withdraw", note="Projeto cancelado"), SUBMITTER)
    with pytest.raises(InvalidTransition):
        service.transition(solution_id, TransitionRequest("claim"), REVIEWER)


def test_request_info_pauses_the_deadline(service: AiIntakeService, clock: list[datetime]) -> None:
    solution_id = _claimed(service, _personal())

    clock[0] = START + timedelta(days=2)
    with pytest.raises(MissingRequiredField, match="note"):
        service.transition(solution_id, TransitionRequest("request_info"), REVIEWER)
    paused = service.transition(
        solution_id, TransitionRequest("request_info", note="Qual a base legal?"), REVIEWER
    )
    assert paused.record.status == "needs_info"
    assert paused.sla.paused is True

    clock[0] = START + timedelta(days=5)
    resumed = service.transition(solution_id, TransitionRequest("resume"), SUBMITTER)

    assert resumed.paused_seconds == timedelta(days=3).total_seconds()
    assert resumed.sla.deadline_at == START + timedelta(days=13)
    assert [event.action for event in resumed.record.events] == [
        "submit",
        "claim",
        "request_info",
        "resume",
    ]


def test_queue_puts_pressure_first_and_decisions_last(
    service: AiIntakeService, clock: list[datetime]
) -> None:
    decided = _claimed(service)
    service.transition(decided, TransitionRequest("approve", note="Sem dado pessoal"), REVIEWER)
    late_low = service.submit(BASE, SUBMITTER).record.id
    clock[0] = START + timedelta(days=6)
    fresh_high = service.submit(_personal(data_categories=("crianca",)), SUBMITTER).record.id

    queue = service.queue()

    assert [view.record.id for view in queue] == [late_low, fresh_high, decided]
    assert queue[0].sla.color == "red"
    assert queue[0].outcome == "em_analise_atrasado"
    assert queue[2].outcome == "decidido_no_prazo"
