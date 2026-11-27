import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.evals.llm_metrics import parse_duration


class EvalExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    should_escalate: bool
    required_terms: list[str] = Field(default_factory=list)
    # Terms that must NOT appear in the answer. This is how a case proves the
    # negative side of quality gates -- e.g. that a recalled customer summary
    # does not pollute the next answer (injection canary, stale-topic drift).
    forbidden_terms: list[str] = Field(default_factory=list)
    expected_references: list[str] = Field(default_factory=list)
    allowed_handoff_reasons: list[str] = Field(default_factory=list)
    # Reasons that MUST be present. This is how a case proves classification
    # (e.g. "fio exposto" must raise ``risco_seguranca``, which opens an urgent
    # case), not only that nothing unexpected was raised.
    required_handoff_reasons: list[str] = Field(default_factory=list)

    @field_validator(
        "required_terms",
        "forbidden_terms",
        "expected_references",
        "allowed_handoff_reasons",
        "required_handoff_reasons",
    )
    @classmethod
    def normalize_list(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class LLMCitationExpectation(BaseModel):
    """A citation the generated answer must carry, tied to its source.

    ``pattern`` is a regex matched (case-insensitive) against the folded answer,
    so write it without accents. ``source`` is a substring that must be found in
    one of the retrieved references: the answer cannot cite an item the
    retrieval never brought back.
    """

    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=200)

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid citation regex: {exc}") from exc
        return value

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source cannot be blank")
        return normalized


class LLMExpectation(BaseModel):
    """Checks applied only by the opt-in real-LLM mode (``--provider-mode real``).

    The deterministic mode ignores this block, so adding it never changes the
    CI gate. All checks are deterministic string/regex checks on the answer.
    """

    model_config = ConfigDict(extra="forbid")

    # Each group passes if ANY of its (folded) terms appears in the answer.
    any_of: list[list[str]] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    # Every duration found in the answer ("24 horas", "4h", "15 dias") must be
    # in this set; anything else is treated as a hallucinated deadline.
    allowed_durations: list[str] = Field(default_factory=list)
    expected_citation: list[LLMCitationExpectation] = Field(default_factory=list)
    # Overrides ``expectation.should_escalate`` in real mode only, for cases
    # whose deterministic escalation came solely from ``provider_error``.
    should_escalate: bool | None = None

    @field_validator("any_of")
    @classmethod
    def normalize_groups(cls, groups: list[list[str]]) -> list[list[str]]:
        normalized = []
        for group in groups:
            terms = [term.strip() for term in group if term.strip()]
            if not terms:
                raise ValueError("any_of groups cannot be empty")
            normalized.append(terms)
        return normalized

    @field_validator("forbidden_terms")
    @classmethod
    def normalize_terms(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]

    @field_validator("allowed_durations")
    @classmethod
    def validate_durations(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        for value in normalized:
            if parse_duration(value) is None:
                raise ValueError(f"unrecognized duration: {value}")
        return normalized


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=4000)
    category: str = Field(min_length=1, max_length=80)
    # Optional seeded customer summary (tiering Fase 4). When present, the
    # runner injects it as the recalled summary for this single case, so the
    # suite can validate that recall improves -- and never pollutes -- the next
    # answer without needing a warehouse row. Mirror the real recall shape:
    # "Problema: ... | Solucao: ... | Status: ...".
    customer_summary: str | None = Field(default=None, max_length=2000)
    expectation: EvalExpectation
    llm_expectation: LLMExpectation | None = None

    @field_validator("id", "question", "category")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field cannot be blank")
        return normalized


class EvalSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=80)
    cases: list[EvalCase] = Field(min_length=1)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("domain cannot be blank")
        return normalized


class EvalCaseResult(BaseModel):
    case_id: str
    passed: bool
    failures: list[str] = Field(default_factory=list)
    escalated: bool
    confidence: float
    handoff_reasons: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class RealEvalCaseResult(EvalCaseResult):
    """One case in one run of the real-LLM mode. Never used by the CI gate."""

    run: int
    answer: str
    error_code: str | None = None
    provider_failure_kind: str | None = None
    llm_called: bool = False
    # Applicable metric -> passed in this run.
    metrics: dict[str, bool] = Field(default_factory=dict)


class EvalRunResult(BaseModel):
    domain: str
    total: int
    passed: int
    failed: int
    results: list[EvalCaseResult]
