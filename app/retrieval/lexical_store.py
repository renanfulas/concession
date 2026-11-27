from app.core.text import fold
from app.domain_engine.models import DomainConfig
from app.ingestion.service import IngestionService
from app.retrieval.models import RetrievedChunk
from app.retrieval.vector_store import VectorStore

# Matching is by substring, so short function words ("no", "de", "um") hit
# almost every chunk ("no" is inside "onibus") and flatten the ranking into
# ties broken by file name. They carry no meaning for retrieval.
_STOPWORDS = frozenset(
    fold(word)
    for word in (
        "a o as os um uma uns umas de da do das dos em na no nas nos ao aos "
        "por pela pelo para com sem que se e é ou mas meu minha meus minhas "
        "seu sua seus suas esse essa este esta isso isto aqui ali la lá ja já "
        "tem ter está estao estão foi ser sao são como quando onde qual quais "
        "voce você voces vocês eu me mim nao não sim mais muito"
    ).split()
)
_PUNCTUATION = ".,;:!?()[]{}\"'“”‘’…"


def query_terms_for(query: str) -> set[str]:
    """Folded, punctuation-trimmed query terms without stopwords or 1-2 letter words.

    fold(): the knowledge base is written without accents and citizens type
    proper pt-BR ("relógio"); both sides compare accent- and case-insensitive.
    Falls back to every folded term when nothing else is left.
    """

    folded = [fold(term).strip(_PUNCTUATION) for term in query.split()]
    terms = {term for term in folded if term}
    meaningful = {term for term in terms if len(term) > 2 and term not in _STOPWORDS}
    return meaningful or terms


def _heading(text: str) -> str:
    """The document's ``# `` heading when this chunk carries it (first chunk)."""

    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:]
    return ""


def _same_word(term: str, word: str) -> bool:
    """Prefix match, plus a shared 5-letter stem ("picharam" ~ "pichacao")."""

    if word.startswith(term):
        return True
    return len(term) >= 5 and len(word) >= 5 and term[:5] == word[:5]


class LexicalVectorStore(VectorStore):
    """Temporary retrieval adapter until the official vector store is connected."""

    def __init__(self) -> None:
        self.ingestion_service = IngestionService()

    def search(
        self,
        domain: DomainConfig,
        query: str,
        top_k: int,
    ) -> list[RetrievedChunk]:
        documents = self.ingestion_service.load_domain_documents(domain)
        chunks = self.ingestion_service.chunk_documents(documents)
        # Selection and score use every term, as before: the score feeds the
        # confidence that decides escalation, so it must not move.
        all_terms = {fold(term) for term in query.split() if term.strip()}
        # Meaningful terms only reorder the selected chunks, so the most
        # relevant source comes first instead of a tie broken by file name.
        meaningful = query_terms_for(query)

        ranked: list[tuple[RetrievedChunk, float]] = []
        for chunk in chunks:
            score = self._score_chunk(chunk.text, all_terms)
            if score <= 0:
                continue

            ranked.append(
                (
                    RetrievedChunk(
                        source=chunk.source,
                        title=chunk.title,
                        text=chunk.text,
                        score=score,
                    ),
                    # Title hits count twice: "fio exposto" in the risk FAQ's
                    # title beats a passing mention in the graffiti FAQ.
                    self._word_score(f"{chunk.title}\n{chunk.text}", meaningful)
                    + self._word_score(_heading(chunk.text) or chunk.title, meaningful),
                )
            )

        ranked.sort(
            key=lambda pair: (
                -pair[0].score,
                pair[0].source.replace("\\", "/").lower(),
                pair[0].title.lower(),
                pair[0].text.lower(),
            )
        )
        selected = ranked[:top_k]
        selected.sort(key=lambda pair: (-pair[1], -pair[0].score))
        return [chunk for chunk, _ in selected]

    @staticmethod
    def _word_score(text: str, terms: set[str]) -> float:
        """Share of ``terms`` that start a word of ``text`` ("fio" -> "fios", not "desafio")."""

        if not terms:
            return 0.0
        words = [word.strip(_PUNCTUATION) for word in fold(text).split()]
        matches = sum(1 for term in terms if any(_same_word(term, word) for word in words))
        return matches / len(terms)

    def _score_chunk(self, text: str, query_terms: set[str]) -> float:
        if not query_terms:
            return 0.0

        lowered = fold(text)
        matches = sum(1 for term in query_terms if term in lowered)
        return matches / len(query_terms)
