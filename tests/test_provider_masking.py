"""Personal data typed by the citizen never reaches the embedding query or the
LLM prompt; local detection (card, secrets) still sees the raw text.

All values are fictitious: placeholder phone, example.test e-mail, the classic
test card 4111..., and a CPF built from a sequential base.
"""

from __future__ import annotations

from pathlib import Path

from app.domain_engine.models import DomainConfig, DomainHandoffConfig
from app.orchestration.chat_flow import ChatFlowService
from app.retrieval.models import RetrievedChunk


PHONE = "(11) 98765-4321"
EMAIL = "cidadao@example.test"
CPF = "123.456.789-09"
CARD = "4111 1111 1111 1111"


class _CapturingRetrieval:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(self, domain: DomainConfig, question: str) -> list[RetrievedChunk]:
        self.queries.append(question)
        return [RetrievedChunk(source="fonte.md", title="Fonte", text="Contexto", score=1.0)]


class _CapturingProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_answer(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "Resposta."


class _CapturingLLM:
    def __init__(self) -> None:
        self.provider = _CapturingProvider()

    def get_provider(self, domain: DomainConfig, api_key: str | None = None):
        return self.provider


def _domain() -> DomainConfig:
    return DomainConfig(
        name="dominio-teste",
        display_name="Dominio teste",
        root_path=Path("."),
        handoff=DomainHandoffConfig(confidence_threshold=0.0),
    )


def _service() -> tuple[ChatFlowService, _CapturingRetrieval, _CapturingLLM]:
    service = ChatFlowService()
    retrieval, llm = _CapturingRetrieval(), _CapturingLLM()
    service.retrieval_service = retrieval
    service.llm_service = llm
    return service, retrieval, llm


def _prompt_text(prompt: object) -> str:
    return str(prompt)


def test_phone_email_and_cpf_never_reach_retrieval_or_prompt() -> None:
    service, retrieval, llm = _service()
    question = f"Meu telefone e {PHONE}, e-mail {EMAIL} e CPF {CPF}; o relogio apagou."
    response = service.answer(_domain(), question)

    assert response["answer"] == "Resposta."
    sent = retrieval.queries + [_prompt_text(p) for p in llm.provider.prompts]
    assert sent, "a pergunta deve ter chegado ao retrieval e ao provider"
    for text in sent:
        assert "98765" not in text
        assert EMAIL not in text
        assert "456.789" not in text
        assert "relogio apagou" in text  # the useful content is kept


def test_card_is_still_detected_on_the_raw_text() -> None:
    service, retrieval, llm = _service()
    response = service.answer(_domain(), f"pode cobrar no cartao {CARD}")

    assert "card_data" in response["handoff_reasons"]
    assert llm.provider.prompts == []  # blocked before any provider call
    for query in retrieval.queries:
        assert "4111" not in query


def test_question_without_personal_data_is_unchanged() -> None:
    service, retrieval, _ = _service()
    service.answer(_domain(), "Qual o prazo para trocar a tela?")
    assert retrieval.queries == ["Qual o prazo para trocar a tela?"]
