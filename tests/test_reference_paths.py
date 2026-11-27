"""`references` never expose the server filesystem and never repeat a source."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import LOCAL_DEV_API_KEY, get_settings
from app.domain_engine.loader import DomainLoader
from app.ingestion.service import IngestionService
from app.main import create_app
from app.orchestration.references import public_reference, public_references
from app.retrieval.lexical_store import LexicalVectorStore

DOMAIN = "concessoes-manutencao"
# Lexical retrieval returns three chunks of the SLA annex for this question.
QUESTION = "Qual o prazo de atendimento do nivel de servico para tela apagada no abrigo?"
ABSOLUTE_DOMAINS_PATH = (Path(__file__).resolve().parents[1] / "domains").resolve()
DRIVE_LETTER = re.compile(r"^[A-Za-z]:")


class _FakeProvider:
    def generate_answer(self, prompt: str) -> str:
        return "Resposta ficticia de teste."


@pytest.fixture
def lexical_env(monkeypatch: pytest.MonkeyPatch):
    # Absolute DOMAINS_PATH reproduces the deployed layout that used to leak.
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENABLE_PUBLIC_CHAT_UI", "true")
    monkeypatch.setenv("RETRIEVAL_BACKEND", "lexical")
    monkeypatch.setenv("PERSISTENCE_BACKEND", "disabled")
    monkeypatch.setenv("DOMAINS_PATH", str(ABSOLUTE_DOMAINS_PATH))
    monkeypatch.setenv("DEFAULT_DOMAIN", DOMAIN)
    monkeypatch.setattr(
        "app.llm.service.LLMService.get_provider",
        lambda self, domain, api_key=None: _FakeProvider(),
    )
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _assert_public(references: list[str]) -> None:
    assert references, "expected at least one reference"
    assert len(references) == len(set(references))
    for reference in references:
        assert "\\" not in reference
        assert not DRIVE_LETTER.match(reference)
        assert not reference.startswith("/")
        assert str(ABSOLUTE_DOMAINS_PATH.as_posix()) not in reference
        assert reference.startswith(f"domains/{DOMAIN}/knowledge/")


def _domain():
    return DomainLoader(get_settings().domains_path).load(DOMAIN)


def test_ingestion_source_is_domain_relative_posix(lexical_env) -> None:
    domain = _domain()
    assert domain.root_path.is_absolute()

    documents = IngestionService().load_domain_documents(domain)

    assert documents
    sources = [document.source for document in documents]
    _assert_public(sources)
    assert f"domains/{DOMAIN}/knowledge/articles/anexo-niveis-de-servico.md" in sources


def test_lexical_retrieval_repeats_source_before_response_dedup(lexical_env) -> None:
    domain = _domain()
    chunks = LexicalVectorStore().search(domain, QUESTION, domain.response.max_context_chunks)

    sources = [chunk.source for chunk in chunks]
    assert len(sources) > len(set(sources)), "precondition: one source, several chunks"


def test_chat_references_are_public_and_unique(lexical_env) -> None:
    client = TestClient(create_app())

    response = client.post(
        "/chat",
        headers={"X-API-Key": LOCAL_DEV_API_KEY},
        json={"domain": DOMAIN, "session_id": "sessao-ficticia-1", "message": QUESTION},
    )

    assert response.status_code == 200
    references = response.json()["references"]
    _assert_public(references)
    assert f"domains/{DOMAIN}/knowledge/articles/anexo-niveis-de-servico.md" in references


def test_web_chat_references_are_public_and_unique(lexical_env) -> None:
    client = TestClient(create_app())

    response = client.post("/web/chat", json={"message": QUESTION})

    assert response.status_code == 200
    references = response.json()["references"]
    _assert_public(references)
    assert f"domains/{DOMAIN}/knowledge/articles/anexo-niveis-de-servico.md" in references


def test_public_references_dedup_preserves_order() -> None:
    assert public_references(
        ["domains/d/knowledge/b.md", "domains/d/knowledge/a.md", "domains/d/knowledge/b.md", ""],
        "d",
    ) == ["domains/d/knowledge/b.md", "domains/d/knowledge/a.md"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # Legacy pgvector/Chroma rows ingested with absolute paths (ficticious paths).
        (r"C:\srv\app\domains\d\knowledge\faqs\x.md", "domains/d/knowledge/faqs/x.md"),
        ("/opt/app/domains/d/knowledge/articles/y.md", "domains/d/knowledge/articles/y.md"),
        ("/opt/app/outro/z.md", "z.md"),
        (r"domains\d\knowledge\faqs\x.md", "domains/d/knowledge/faqs/x.md"),
        # Non-filesystem identifiers stay untouched.
        ("https://github.com/exemplo/repo/blob/main/README.md", "https://github.com/exemplo/repo/blob/main/README.md"),
        ("kb:a", "kb:a"),
        ("source.md", "source.md"),
    ],
)
def test_public_reference_strips_filesystem_layout(source: str, expected: str) -> None:
    assert public_reference(source, "d") == expected
