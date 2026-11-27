"""Lexical retrieval: accents and the order of the selected chunks.

Selection and score stay exactly as before (they feed the confidence that
decides escalation); meaningful words only reorder what was selected, so the
most relevant document comes first instead of a tie broken by file name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.text import fold
from app.domain_engine.loader import DomainLoader
from app.retrieval.lexical_store import LexicalVectorStore, query_terms_for


def _domain(name: str):
    loaded = DomainLoader(Path("domains")).load(name)
    assert loaded is not None
    return loaded


@pytest.mark.parametrize(
    ("domain", "question", "top"),
    [
        ("concessoes-manutencao", "Tem um fio exposto soltando faísca no abrigo ABR-1104", "risco-seguranca.md"),
        ("concessoes-manutencao", "O relógio REL-0423 está com a tela apagada", "tela-apagada.md"),
        ("concessoes-manutencao", "Picharam o relógio da Praça da Sé", "pichacao-limpeza.md"),
        ("lgpd-titular", "Acho que meus dados vazaram", "incidente-vazamento.md"),
        ("lgpd-titular", "Quero excluir meus dados", "excluir-ou-corrigir-dados.md"),
    ],
)
def test_lexical_ranking_puts_the_relevant_document_first(domain: str, question: str, top: str) -> None:
    chunks = LexicalVectorStore().search(_domain(domain), question, top_k=5)
    assert chunks[0].source.endswith(top)


def test_ranking_never_changes_selection_or_scores() -> None:
    """Scores feed the confidence that decides escalation; reordering must not touch them."""
    store = LexicalVectorStore()
    domain = _domain("concessoes-manutencao")
    question = "Tem um fio exposto soltando faísca no abrigo ABR-1104"
    chunks = store.search(domain, question, top_k=5)
    documents = store.ingestion_service.load_domain_documents(domain)
    all_chunks = store.ingestion_service.chunk_documents(documents)
    terms = {fold(term) for term in question.split()}
    expected = sorted(
        (round(store._score_chunk(chunk.text, terms), 6) for chunk in all_chunks),
        reverse=True,
    )[:5]
    assert sorted((round(chunk.score, 6) for chunk in chunks), reverse=True) == expected


def test_stopwords_are_dropped_from_ranking_terms() -> None:
    assert query_terms_for("Tem um fio exposto no abrigo") == {"fio", "exposto", "abrigo"}
    assert query_terms_for("de no um") == {"de", "no", "um"}
