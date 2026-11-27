"""HTTP contract of the AI solution intake (/web/support/intake/*).

Runs against the in-memory seams ``create_app`` builds without PostgreSQL:
staff OTP login with memory delivery and the in-memory intake repository.
Two staff members, two cookie jars: the submitter and the reviewer.
"""

from __future__ import annotations

import csv
import io
import logging
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.support.staff_auth import StaffMember
from app.web_auth.service import _hmac_digest

IDENTITY_SECRET = "identity-test-secret"
OTP_SECRET = "otp-test-secret"
SUBMITTER_PHONE = "+5511999990001"
REVIEWER_PHONE = "+5511999990002"
CSRF = {"X-Requested-With": "XMLHttpRequest"}

SUBMISSION = {
    "name": "Contagem de audiencia por camera em painel digital",
    "business_unit": "Midia digital",
    "purpose": "Estimar quantas pessoas passam pelo painel, sem identificar ninguem.",
    "owner_name": "Gestora Demo",
    "owner_role": "Gerente de produto",
    "solution_type": "fornecedor",
    "vendor": "Fornecedor Exemplo (demo)",
    "model_provider": "visao computacional embarcada",
    "hosting_region": "uniao_europeia",
    "data_categories": ["biometrico_imagem"],
    "data_subjects": ["cidadao"],
    "legal_basis": "legitimo_interesse",
    "automated_decision": False,
    "external_facing": False,
    "human_in_loop": True,
}


@contextmanager
def _app(monkeypatch: pytest.MonkeyPatch, *, console: bool = True, intake: bool = True):
    from app.main import create_app

    monkeypatch.setenv("ENABLE_SUPPORT_CONSOLE", "true" if console else "false")
    monkeypatch.setenv("ENABLE_AI_INTAKE", "true" if intake else "false")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", IDENTITY_SECRET)
    monkeypatch.setenv("OTP_DIGEST_SECRET", OTP_SECRET)
    get_settings.cache_clear()
    try:
        yield create_app()
    finally:
        get_settings.cache_clear()


def _staff_client(app, phone: str, display_name: str) -> TestClient:
    app.state.support_console_runtime.service.staff_store.add_staff(
        StaffMember(
            id=str(uuid4()),
            phone_hash=_hmac_digest(IDENTITY_SECRET, phone),
            phone_last4=phone[-4:],
            display_name=display_name,
        )
    )
    client = TestClient(app)
    start = client.post("/web/support/auth/start", json={"phone": phone})
    code = app.state.support_console_runtime.delivery.requests[-1].code
    confirm = client.post(
        "/web/support/auth/confirm",
        json={"challenge_id": start.json()["challenge_id"], "code": code, "phone": phone},
    )
    assert confirm.status_code == 200
    return client


@contextmanager
def _pair(monkeypatch: pytest.MonkeyPatch):
    with _app(monkeypatch) as app:
        yield (
            _staff_client(app, SUBMITTER_PHONE, "Pessoa da BU (demo)"),
            _staff_client(app, REVIEWER_PHONE, "Revisor de IA (demo)"),
        )


def _submit(client: TestClient, **overrides) -> dict:
    response = client.post(
        "/web/support/intake/solutions", json={**SUBMISSION, **overrides}, headers=CSRF
    )
    assert response.status_code == 201, response.text
    return response.json()


def _transition(client: TestClient, solution_id: str, **payload):
    return client.post(
        f"/web/support/intake/solutions/{solution_id}/transitions",
        json=payload,
        headers=CSRF,
    )


# --------------------------------------------------------------------------- #
# Superficie e acesso
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("console", "intake"), [(False, True), (True, False)])
def test_intake_is_404_unless_console_and_flag_are_on(
    monkeypatch: pytest.MonkeyPatch, console: bool, intake: bool
) -> None:
    with _app(monkeypatch, console=console, intake=intake) as app:
        client = TestClient(app)
        assert client.get("/web/support/intake/solutions").status_code == 404
        assert client.get("/web/support/intake/options").status_code == 404


def test_intake_needs_a_staff_session(monkeypatch: pytest.MonkeyPatch) -> None:
    with _app(monkeypatch) as app:
        client = TestClient(app)
        assert client.get("/web/support/intake/solutions").status_code == 401
        assert client.get("/web/support/intake/inventory.csv").status_code == 401


def test_writes_need_the_csrf_header(monkeypatch: pytest.MonkeyPatch) -> None:
    with _pair(monkeypatch) as (submitter, _):
        response = submitter.post("/web/support/intake/solutions", json=SUBMISSION)
        assert response.status_code == 403
        assert response.json()["detail"] == "csrf_header_required"


def test_options_expose_closed_lists_and_the_demo_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    with _pair(monkeypatch) as (submitter, _):
        body = submitter.get("/web/support/intake/options").json()

    assert "biometrico_imagem" in body["data_categories"]
    assert body["sla_days"] == {"baixa": 5, "media": 10, "alta": 15}
    assert "demo" in body["basis"].lower()
    assert body["durable"] is False
    assert {rule["id"] for rule in body["rules"]} >= {"dado_sensivel_ou_imagem"}


# --------------------------------------------------------------------------- #
# Fluxo completo
# --------------------------------------------------------------------------- #


def test_full_review_flow_with_separation_of_duties(monkeypatch: pytest.MonkeyPatch) -> None:
    with _pair(monkeypatch) as (submitter, reviewer):
        created = _submit(submitter)
        solution_id = created["id"]

        assert created["criticality"] == "alta"
        assert created["ripd_required"] is True
        assert created["submitted_by_me"] is True
        assert {reason["id"] for reason in created["criticality_reasons"]} == {
            "dado_sensivel_ou_imagem",
            "transferencia_internacional",
            "dado_pessoal",
        }
        assert created["sla"]["color"] == "green"

        self_claim = _transition(submitter, solution_id, action="claim")
        assert self_claim.status_code == 409
        assert self_claim.json()["detail"]["code"] == "self_review_forbidden"

        assert _transition(reviewer, solution_id, action="claim").status_code == 200

        no_ripd = _transition(reviewer, solution_id, action="approve", note="Ok")
        assert no_ripd.status_code == 409
        assert no_ripd.json()["detail"] == {
            "code": "missing_required_field",
            "field": "ripd_reference",
        }

        approved = _transition(
            reviewer,
            solution_id,
            action="approve_with_conditions",
            note="Aprovado com contagem anonima na borda",
            conditions="Descartar imagem no equipamento",
            ripd_reference="RIPD-2026-03 (demo)",
        )
        assert approved.status_code == 200
        body = approved.json()
        assert body["status"] == "approved_conditional"
        assert body["reviewing_by_me"] is True
        assert body["outcome"] == "decidido_no_prazo"
        assert [event["action"] for event in body["events"]] == [
            "submit",
            "claim",
            "approve_with_conditions",
        ]

        queue = submitter.get("/web/support/intake/solutions").json()
        assert [item["id"] for item in queue["items"]] == [solution_id]
        assert queue["items"][0]["events"] == []


def test_invalid_field_and_unknown_solution(monkeypatch: pytest.MonkeyPatch) -> None:
    with _pair(monkeypatch) as (submitter, reviewer):
        invalid = submitter.post(
            "/web/support/intake/solutions",
            json={**SUBMISSION, "data_categories": ["nenhum", "pessoal"]},
            headers=CSRF,
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"] == {"code": "invalid_field", "field": "data_categories"}

        extra = submitter.post(
            "/web/support/intake/solutions", json={**SUBMISSION, "cpf": "x"}, headers=CSRF
        )
        assert extra.status_code == 422

        assert submitter.get(f"/web/support/intake/solutions/{uuid4()}").status_code == 404
        unknown_action = _transition(reviewer, _submit(submitter)["id"], action="delete")
        assert unknown_action.status_code == 422


# --------------------------------------------------------------------------- #
# Inventario e ficha
# --------------------------------------------------------------------------- #


def test_inventory_csv_is_excel_ready_and_neutralizes_formulas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _pair(monkeypatch) as (submitter, _):
        _submit(submitter, name="=HYPERLINK(\"http://exemplo.invalid\")")
        _submit(
            submitter,
            name="Previsao de falha de paineis",
            data_categories=["nenhum"],
            data_subjects=[],
            legal_basis="nao_se_aplica",
            hosting_region="brasil",
        )
        response = submitter.get("/web/support/intake/inventory.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["cache-control"] == "no-store"
    text = response.text
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))
    header, first, second = rows[0], rows[1], rows[2]
    assert header[:4] == ["referencia", "nome", "unidade", "responsavel"]
    assert first[1].startswith("'=")
    assert first[header.index("criticidade")] == "alta"
    assert second[header.index("criticidade")] == "baixa"
    assert second[header.index("resultado")] == "em_analise_no_prazo"


def test_ficha_follows_the_system_card_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    with _pair(monkeypatch) as (submitter, _):
        created = _submit(submitter)
        response = submitter.get(f"/web/support/intake/solutions/{created['id']}/ficha.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    body = response.text
    assert body.startswith(f"# Ficha da solucao {created['reference']}")
    for section in ("## Dados tratados e base legal", "## Criticidade", "## Prazo da analise", "## Trilha de auditoria"):
        assert section in body
    assert "LGPD art. 11" in body


def test_logs_carry_no_name_purpose_or_note(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with _pair(monkeypatch) as (submitter, reviewer):
        with caplog.at_level(logging.INFO):
            created = _submit(submitter)
            _transition(reviewer, created["id"], action="claim")
            _transition(reviewer, created["id"], action="request_info", note="Nota sigilosa XYZ")

    intake_logs = [r.getMessage() for r in caplog.records if "ai_intake_" in r.getMessage()]
    assert len(intake_logs) == 3
    for message in intake_logs:
        assert SUBMISSION["name"] not in message
        assert SUBMISSION["purpose"] not in message
        assert "Gestora Demo" not in message
        assert "Nota sigilosa" not in message
