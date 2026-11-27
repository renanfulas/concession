"""Deterministic safety notices: a rule's ``notice`` reaches the citizen whatever
produced the answer (LLM, provider fallback, blocked response)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import ProviderError
from app.domain_engine.loader import DomainLoader
from app.domain_engine.models import DomainConfig, DomainHandoffConfig, DomainHandoffRuleConfig
from app.orchestration.chat_flow import ChatFlowService
from app.retrieval.models import RetrievedChunk


NOTICE = "Mantenha distancia e ligue 193."


class _OneChunkRetrieval:
    def retrieve(self, domain: DomainConfig, question: str) -> list[RetrievedChunk]:
        return [RetrievedChunk(source="risco.md", title="Risco", text="Contexto", score=1.0)]


class _FailingLLM:
    def get_provider(self, domain: DomainConfig, api_key: str | None = None):
        raise ProviderError("failed", failure_kind="provider_timeout")


class _FixedAnswerProvider:
    def generate_answer(self, prompt: str) -> str:
        return "Resposta do modelo."


class _WorkingLLM:
    def get_provider(self, domain: DomainConfig, api_key: str | None = None):
        return _FixedAnswerProvider()


def _domain(*, notice: str | None = NOTICE) -> DomainConfig:
    return DomainConfig(
        name="dominio-teste",
        display_name="Dominio teste",
        root_path=Path("."),
        handoff=DomainHandoffConfig(
            confidence_threshold=0.0,
            explicit_human_phrases=["falar com atendente"],
            escalation_rules=[
                DomainHandoffRuleConfig(
                    reason="risco_seguranca",
                    priority="urgent",
                    terms=["fio exposto"],
                    notice=notice,
                ),
                DomainHandoffRuleConfig(reason="limpeza", terms=["sujo"], notice=NOTICE),
            ],
        ),
    )


def _service(llm: object) -> ChatFlowService:
    service = ChatFlowService()
    service.retrieval_service = _OneChunkRetrieval()
    service.llm_service = llm
    return service


def test_notice_survives_provider_failure() -> None:
    response = _service(_FailingLLM()).answer(_domain(), "Tem fio exposto no abrigo")
    assert response["error_code"] == "provider_error"
    assert str(response["answer"]).startswith(NOTICE)


def test_notice_precedes_model_answer() -> None:
    response = _service(_WorkingLLM()).answer(_domain(), "Tem fio exposto no abrigo")
    assert response["answer"] == f"{NOTICE}\n\nResposta do modelo."


def test_notice_survives_blocked_response() -> None:
    response = _service(_WorkingLLM()).answer(
        _domain(), "Tem fio exposto no abrigo, quero falar com atendente"
    )
    assert "explicit_human_request" in response["handoff_reasons"]
    assert str(response["answer"]).startswith(NOTICE)


def test_same_notice_from_two_rules_appears_once() -> None:
    response = _service(_WorkingLLM()).answer(_domain(), "Tem fio exposto e o abrigo esta sujo")
    assert str(response["answer"]).count(NOTICE) == 1


def test_no_notice_without_matching_rule() -> None:
    response = _service(_WorkingLLM()).answer(_domain(), "Qual o horario de atendimento?")
    assert NOTICE not in str(response["answer"])


def test_rule_without_notice_keeps_answer() -> None:
    response = _service(_WorkingLLM()).answer(_domain(notice=None), "Tem fio exposto no abrigo")
    assert response["answer"] == "Resposta do modelo."


@pytest.mark.parametrize(
    ("domain_name", "reason", "expected"),
    [
        ("concessoes-manutencao", "risco_seguranca", "193"),
        ("lgpd-titular", "incidente_dados", "nunca pede senha"),
    ],
)
def test_real_domains_declare_safety_notice(domain_name: str, reason: str, expected: str) -> None:
    domain = DomainLoader(Path("domains")).load(domain_name)
    assert domain is not None
    rule = next(r for r in domain.handoff.escalation_rules if r.reason == reason)
    assert rule.notice and expected in rule.notice
