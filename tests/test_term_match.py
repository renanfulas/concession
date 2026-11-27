"""Unit contract of the escalation-rule term matcher (app/handoff/term_match.py).

Domain-level consequences (priority, SLA, notice) are pinned in
tests/test_concessoes_domain.py and in the domain evals; this file pins the
matching rules themselves with neutral, fictitious text.
"""

from __future__ import annotations

import pytest

from app.handoff.term_match import matches_rule


@pytest.mark.parametrize(
    ("text", "term"),
    [
        ("Picharam o abrigo", "picha"),  # stem at the start of a word
        ("a lateral ficou danificada", "danificad"),
        ("Tem fios expostos", "fio exposto"),  # plural of every word
        ("Fiação exposta no poste", "fiacao exposta"),  # accents folded
        ("O RELÓGIO ESTÁ APAGADO", "relogio apagado"),  # case folded
    ],
)
def test_term_matches_at_word_start(text: str, term: str) -> None:
    assert matches_rule(text, [term])


@pytest.mark.parametrize(
    ("text", "term"),
    [
        ("Arrisco dizer que esta sujo", "risco"),
        ("Preciso de desbloqueio", "bloqueio"),
        ("O fogao do quiosque", "fogo"),
    ],
)
def test_term_does_not_match_inside_a_word(text: str, term: str) -> None:
    assert not matches_rule(text, [term])


def test_function_words_match_exactly() -> None:
    assert matches_rule("a tela ficou sem imagem", ["sem imagem"])
    assert not matches_rule("faz uma semana imagem ruim", ["sem imagem"])


@pytest.mark.parametrize(
    "text",
    [
        "o relogio esta apagado",
        "o relogio REL-0423 esta apagado",  # an asset code does not count
        "o relogio do abrigo esta apagado",  # nor does a function word
    ],
)
def test_small_gap_between_content_words(text: str) -> None:
    assert matches_rule(text, ["relogio apagado"])


@pytest.mark.parametrize(
    "text",
    [
        "o relogio da praca central ficou apagado",  # three content words between
        "o relogio, que fica na praca, esta apagado",  # punctuation ends the match
        "apagado o relogio",  # order matters
    ],
)
def test_gap_is_bounded(text: str) -> None:
    assert not matches_rule(text, ["relogio apagado"])


def test_words_next_to_a_function_word_stay_adjacent() -> None:
    assert matches_rule("alguem pode se cortar", ["se cortar"])
    assert not matches_rule("se for cortar a arvore", ["se cortar"])


@pytest.mark.parametrize(
    "text",
    [
        "sem risco",
        "nao ha risco",
        "nao tem nenhum risco",
        "sem nenhum risco",
        "nao oferece risco",
        "nenhum risco aparente",
        "risco nenhum",
    ],
)
def test_simple_negation_blocks_the_term(text: str) -> None:
    assert not matches_rule(text, ["risco"])


def test_negation_inside_the_gap_blocks_the_term() -> None:
    assert not matches_rule("o painel nao esta apagado", ["painel apagado"])


@pytest.mark.parametrize(
    "text",
    [
        "nao toque no fio exposto",
        "nao chegue perto, tem fio exposto",
        "nao sei quem fez, mas tem fio exposto",
        "sem luz e com fio exposto",
    ],
)
def test_negation_out_of_reach_does_not_block(text: str) -> None:
    assert matches_rule(text, ["fio exposto"])


def test_any_non_negated_occurrence_matches() -> None:
    assert matches_rule("sem risco aqui, mas ali tem risco", ["risco"])


def test_terms_with_their_own_negation_still_match() -> None:
    assert matches_rule("a tela nao liga", ["nao liga"])


def test_ignore_terms_cut_their_words_out_first() -> None:
    assert not matches_rule("qual o risco de multa", ["risco"], ["risco de multa"])
    assert matches_rule(
        "risco de multa e risco de choque", ["risco"], ["risco de multa"]
    )


def test_ignore_terms_use_the_same_gap() -> None:
    assert not matches_rule(
        "o tecnico ja esta atrasado", ["atrasado"], ["tecnico atrasado"]
    )
    assert matches_rule("o relogio esta atrasado", ["atrasado"], ["tecnico atrasado"])


def test_cut_does_not_join_the_words_around_it() -> None:
    # Without the split, "fio" and "exposto" would sit within the gap.
    assert not matches_rule(
        "fio risco de multa exposto", ["fio exposto"], ["risco de multa"]
    )


def test_blank_terms_are_ignored() -> None:
    assert not matches_rule("qualquer texto", ["", "   "], ["", " "])
