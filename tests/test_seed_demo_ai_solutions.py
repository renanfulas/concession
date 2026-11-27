"""Demo seed of the AI intake, without a database: the fictitious solutions go
through the same service in memory, cover every criticality level and the main
states of the flow, and the script refuses to run outside a local dev/test DB."""

from __future__ import annotations

from app.ai_intake.policy import load_policy
from app.ai_intake.repository import InMemorySolutionRepository
from app.ai_intake.service import AiIntakeService
from app.ai_intake.workflow import Actor
from scripts import seed_demo_ai_solutions as seed


def test_demo_solutions_cover_levels_and_states() -> None:
    service = AiIntakeService(load_policy(), InMemorySolutionRepository())
    submitter = Actor("submitter", seed.SUBMITTER_NAME)
    operator = Actor("operator", "Atendente Demo 1")

    outcome = {}
    for demo in seed.DEMO_SOLUTIONS:
        view = service.submit(demo.submission, submitter)
        for step in demo.steps:
            view = service.transition(view.record.id, step, operator)
        outcome[demo.key] = (view.record.criticality, view.record.status)

    assert outcome == {
        "contagem-audiencia": ("alta", "submitted"),
        "assistente-manutencao": ("media", "in_review"),
        "resumo-contratos": ("alta", "needs_info"),
        "previsao-falhas": ("baixa", "submitted"),
        "triagem-curriculos": ("alta", "rejected"),
    }


def test_demo_data_is_fictitious() -> None:
    assert seed.SUBMITTER_PHONE.startswith("+55119000000")
    for demo in seed.DEMO_SOLUTIONS:
        text = " ".join(
            str(value) for value in vars(demo.submission).values() if isinstance(value, str)
        )
        assert "@" not in text
        assert "Demo" in demo.submission.owner_name


def test_seed_refuses_without_explicit_dev_env(monkeypatch, capsys) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@localhost/db")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", "x")

    assert seed.main([]) == 2
    error = capsys.readouterr().err
    assert "APP_ENV" in error
    assert "secret" not in error


def test_seed_refuses_a_remote_database(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.example.invalid/db")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", "x")

    assert seed.main([]) == 2
