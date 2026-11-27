"""Deterministic matching of ``escalation_rules[].terms`` against citizen text.

The rules decide the case priority, the SLA deadline and the fixed safety notice,
so the matcher stays deterministic and small (no LLM, no stemming library):

* **Word starts.** Text and terms are folded (accent- and case-insensitive) and
  split into words. A term word matches a text word that *starts* with it, so
  stems keep working (``picha`` -> pichacao, ``danificad`` -> danificada) and
  plurals match (``fio exposto`` -> fios expostos), but a term no longer matches
  in the middle of a word (``bloqueio`` does not match "desbloqueio").
  Function words (``de``, ``sem``, ``nao``...) must match exactly.
* **Small gap.** Between two content words of a multi-word term up to
  :data:`MAX_GAP` other content words may appear, plus function words and
  asset codes ("relogio REL-0423 esta apagado" and "painel do abrigo esta apagado" match
  ``relogio apagado`` / ``painel apagado``). Words next to a function word stay adjacent
  (``se cortar``, ``nao liga``). A match never crosses punctuation.
* **Simple negation.** An occurrence does not count when a negation comes right
  before it (``sem risco``, ``nao ha risco``, ``sem nenhum risco``), inside its
  gap ("a tela nao esta apagada") or right after it (``risco nenhum``). Another,
  non-negated occurrence or another term of the same rule still matches
  ("fio exposto, sem risco?" stays urgent).
* **ignore_terms** are matched the same way (without the negation check) and
  their words are cut out of the text before the rule's terms are checked, for
  senses negation cannot express (``risco de multa``, ``tecnico atrasado``).

A missed match is still safe: the turn falls back to ``low_confidence`` and goes
to a person.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence

from app.core.text import fold

# Content words that may sit between two content words of a multi-word term.
# Function words and asset codes (any word with a digit, "ABR-2210") in the gap
# do not count ("painel do abrigo ABR-2210 esta apagado"), but the gap never
# exceeds MAX_GAP_WORDS words in total.
MAX_GAP = 2
MAX_GAP_WORDS = 4

# A word is a run of letters/digits; hyphens join parts of one word so an asset
# code such as "REL-0423" counts as a single word inside a gap.
_WORD = re.compile(r"[^\W_]+(?:-[^\W_]+)*")
# A match (and a negation) never reaches across these.
_CLAUSE_BREAK = re.compile(r"[.,;:!?()\[\]{}\n\r]+")

# Matched exactly, never as a prefix ("sem" must not match "semana"), and never
# separated by a gap from the next word of the term.
FUNCTION_WORDS = frozenset(
    (
        "a o as os e ou de da do das dos em no na nos nas ao aos com sem se "
        "um uma que ha por pra para nao me te"
    ).split()
)

NEGATIONS = frozenset({"nao", "sem", "nem", "nenhum", "nenhuma", "nunca", "jamais"})
# Words allowed between a negation and the term ("nao ha risco",
# "sem nenhum risco", "nao oferece risco"). Kept short on purpose: anything else
# ends the negation's reach, so "nao toque no fio exposto" stays a match.
# No verbs of seeing ("vi", "vejo"): "nunca vi fio exposto assim" is emphasis,
# the wire is there. Leaving them out makes "nao vejo risco" match too, which
# errs on the safe side (urgent case, a person checks).
NEGATION_FILLERS = frozenset(
    (
        "ha tem teve tinha houve existe existia esta estava ficou e era foi "
        "oferece ofereceu apresenta nenhum nenhuma qualquer mais um uma"
    ).split()
)
MAX_NEGATION_FILLERS = 2
# Negation written after the term: "risco nenhum".
TRAILING_NEGATIONS = frozenset({"nenhum", "nenhuma"})


def clauses(text: str) -> list[list[str]]:
    """Folded words of ``text``, grouped by clause (split on punctuation)."""
    return [
        words
        for chunk in _CLAUSE_BREAK.split(fold(text))
        if (words := _WORD.findall(chunk))
    ]


def term_words(term: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(fold(term)))


def _word_matches(term_word: str, word: str) -> bool:
    if term_word in FUNCTION_WORDS:
        return word == term_word
    if word.startswith(term_word):
        return True
    # "abrigo-0423" or "anti-vandalismo": any hyphen part may start the match.
    return "-" in word and any(part.startswith(term_word) for part in word.split("-"))


def _is_gap_filler(word: str) -> bool:
    """Gap words that do not count against MAX_GAP: function words and codes."""
    return word in FUNCTION_WORDS or any(ch.isdigit() for ch in word)


def _occurrences(words: Sequence[str], term: Sequence[str]) -> Iterator[list[int]]:
    """Every list of word positions where ``term`` occurs in one clause."""

    def extend(k: int, positions: list[int]) -> Iterator[list[int]]:
        if k == len(term):
            yield positions
            return
        last = positions[-1]
        adjacent = term[k - 1] in FUNCTION_WORDS or term[k] in FUNCTION_WORDS
        skipped_content = 0
        for nxt in range(last + 1, len(words)):
            if _word_matches(term[k], words[nxt]):
                yield from extend(k + 1, [*positions, nxt])
            if adjacent or nxt - last > MAX_GAP_WORDS:
                break
            if not _is_gap_filler(words[nxt]):
                skipped_content += 1
                if skipped_content > MAX_GAP:
                    break

    for start, word in enumerate(words):
        if _word_matches(term[0], word):
            yield from extend(1, [start])


def _is_negated(words: Sequence[str], positions: Sequence[int]) -> bool:
    first, last = positions[0], positions[-1]
    matched = set(positions)
    # Negation inside the gap: "a tela nao esta apagada".
    if any(words[i] in NEGATIONS for i in range(first, last + 1) if i not in matched):
        return True
    # Negation right after the term: "risco nenhum".
    if last + 1 < len(words) and words[last + 1] in TRAILING_NEGATIONS:
        return True
    # Negation before the term, optionally through a few fillers.
    fillers = 0
    i = first - 1
    while i >= 0:
        word = words[i]
        if word in NEGATIONS:
            return True
        if word not in NEGATION_FILLERS or fillers == MAX_NEGATION_FILLERS:
            return False
        fillers += 1
        i -= 1
    return False


def _without_spans(
    text_clauses: list[list[str]], ignore_terms: Iterable[str]
) -> list[list[str]]:
    """Cut every occurrence of an ignore term out, splitting its clause there."""
    result = text_clauses
    for phrase in ignore_terms:
        term = term_words(phrase)
        if not term:
            continue
        next_result: list[list[str]] = []
        for words in result:
            removed: set[int] = set()
            for positions in _occurrences(words, term):
                removed.update(range(positions[0], positions[-1] + 1))
            piece: list[str] = []
            for i, word in enumerate(words):
                if i in removed:
                    if piece:
                        next_result.append(piece)
                    piece = []
                else:
                    piece.append(word)
            if piece:
                next_result.append(piece)
        result = next_result
    return result


def matches_rule(
    text: str, terms: Iterable[str], ignore_terms: Iterable[str] = ()
) -> bool:
    """True when some term of the rule occurs in ``text`` without negation."""
    text_clauses = _without_spans(clauses(text), ignore_terms)
    for raw_term in terms:
        term = term_words(raw_term)
        if not term:
            continue
        for words in text_clauses:
            if any(
                not _is_negated(words, positions)
                for positions in _occurrences(words, term)
            ):
                return True
    return False
