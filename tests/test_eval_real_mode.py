"""Opt-in real-LLM eval mode, exercised only with fake providers.

No test here talks to a real provider: ``app.llm.service.LLMWrapper`` is
replaced by fakes, and any key used is a fictitious placeholder.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.errors import ProviderError
from app.core.text import fold
from app.domain_engine.loader import DomainLoader
from app.evals import run_domain_eval
from app.evals.llm_metrics import evaluate_llm_expectation, extract_durations, parse_duration
from app.evals.loader import EvalSuiteLoader
from app.evals.models import EvalCaseResult, EvalSuite, LLMExpectation
from app.evals.real_mode import RealEvalRunner, summarize_domain
from app.evals.runner import DomainEvalRunner

FAKE_KEY = "sk-test-fake-placeholder-0000000000000000"

GOOD_TELA = (
    "Registrei o defeito do relogio. Pelo item 3.2 do Anexo de Niveis de "
    "Servico (demo), o prazo e de 24 horas para voltar a funcionar."
)
TELA_MARKER = "Teodoro Sampaio esta com a tela apagada"
HALLUCINATED_TELA = (
    "Registrei o defeito do relogio. Pelo item 3.2 do Anexo de Niveis de "
    "Servico (demo), o prazo e de 2 horas para voltar a funcionar."
)


def _lexical_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.retrieval.service.get_settings",
        lambda: type("Settings", (), {"retrieval_backend": "lexical"})(),
    )


def _install_wrapper(monkeypatch: pytest.MonkeyPatch, answers: dict[str, list[str]]) -> list[str]:
    """Fake provider: answers by a question substring, cycling per call."""
    prompts: list[str] = []
    counters: dict[str, int] = {}

    class FakeWrapper:
        def __init__(self, provider: str, model: str, api_key: str | None = None) -> None:
            _ = (provider, api_key)
            self.model = model
            self.temperature = 0.0
            self.last_call_metadata: dict | None = None

        def generate_answer(self, prompt: str) -> str:
            prompts.append(prompt)
            for marker, options in answers.items():
                if marker in prompt:
                    index = counters.get(marker, 0)
                    counters[marker] = index + 1
                    self.last_call_metadata = {
                        "model": "fake-model-2026-01-01",
                        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                    }
                    return options[index % len(options)]
            self.last_call_metadata = {"model": "fake-model-2026-01-01"}
            return "Resposta generica de teste."

    monkeypatch.setattr("app.llm.service.LLMWrapper", FakeWrapper)
    return prompts


def _install_failing_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingWrapper:
        def __init__(self, provider: str, model: str, api_key: str | None = None) -> None:
            _ = (provider, model, api_key)

        def generate_answer(self, prompt: str) -> str:
            _ = prompt
            raise ProviderError("provider unavailable", failure_kind="provider_request_error")

    monkeypatch.setattr("app.llm.service.LLMWrapper", FailingWrapper)


def _domain(name: str):
    domain = DomainLoader(Path("domains")).load(name)
    assert domain is not None
    return domain


def _suite(domain, file: str = "evals/cases.yaml") -> EvalSuite:
    suite = EvalSuiteLoader().load(domain.root_path / file)
    assert suite is not None
    return suite


def _single_case_suite(domain, case_id: str) -> EvalSuite:
    suite = _suite(domain)
    case = next(case for case in suite.cases if case.id == case_id)
    return EvalSuite(domain=suite.domain, cases=[case])


def _fake_settings(*, key: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        domains_path=Path("domains"),
        openai_api_key=key,
        anthropic_api_key=None,
        retrieval_backend="lexical",
    )


# --- pure metrics -----------------------------------------------------------


def test_extract_durations_normalizes_units_and_ignores_rates() -> None:
    text = "Prazo de 24 horas (24h), valido 24 horas por dia, 7 dias por semana; limpeza em 5 dias corridos e 30 min."
    assert extract_durations(text) == [(24, "horas"), (24, "horas"), (5, "dias"), (30, "minutos")]
    assert parse_duration("24h") == parse_duration("24 horas") == (24, "horas")
    assert parse_duration("item 3.2") is None


def test_any_of_passes_when_any_term_of_each_group_appears() -> None:
    expectation = LLMExpectation(any_of=[["24 horas", "24h"], ["3.2"]])
    ok = evaluate_llm_expectation(expectation, answer="Prazo: 24h (item 3.2).", references=[])
    missing = evaluate_llm_expectation(expectation, answer="Prazo: 24h.", references=[])

    assert ok == {"any_of": []}
    assert missing == {"any_of": ["missing_any_of:3.2"]}


def test_forbidden_terms_are_accent_and_case_insensitive() -> None:
    expectation = LLMExpectation(forbidden_terms=["foram excluidos"])
    result = evaluate_llm_expectation(
        expectation, answer="Seus dados FORAM EXCLUÍDOS.", references=[]
    )
    assert result == {"llm_forbidden_terms": ["forbidden_term_present:foram excluidos"]}


def test_allowed_durations_flag_hallucinated_deadline() -> None:
    expectation = LLMExpectation(allowed_durations=["24 horas"])
    good = evaluate_llm_expectation(expectation, answer="Em ate 24h.", references=[])
    bad = evaluate_llm_expectation(
        expectation, answer="Em ate 2 horas, ou 2 horas no maximo.", references=[]
    )

    assert good == {"allowed_durations": []}
    assert bad == {"allowed_durations": ["disallowed_duration:2 horas"]}


def test_expected_citation_needs_text_and_retrieved_source() -> None:
    expectation = LLMExpectation(
        expected_citation=[{"pattern": r"art\.?\s*19", "source": "prazos-de-resposta.md"}]
    )
    ok = evaluate_llm_expectation(
        expectation,
        answer="Pelo Art. 19 da LGPD, 15 dias.",
        references=["knowledge/articles/prazos-de-resposta.md"],
    )
    not_retrieved = evaluate_llm_expectation(
        expectation, answer="Pelo art. 19 da LGPD.", references=["outro.md"]
    )
    not_cited = evaluate_llm_expectation(
        expectation, answer="Em 15 dias.", references=["prazos-de-resposta.md"]
    )

    assert ok == {"expected_citation": []}
    assert not_retrieved == {
        "expected_citation": ["citation_source_not_retrieved:prazos-de-resposta.md"]
    }
    assert not_cited == {"expected_citation": [r"missing_citation:art\.?\s*19"]}


def test_llm_expectation_rejects_invalid_duration_and_regex() -> None:
    with pytest.raises(ValidationError):
        LLMExpectation(allowed_durations=["vinte e quatro horas"])
    with pytest.raises(ValidationError):
        LLMExpectation(expected_citation=[{"pattern": "item (3", "source": "a.md"}])


def test_case_files_with_llm_expectation_still_load() -> None:
    for name in ("concessoes-manutencao", "lgpd-titular"):
        suite = _suite(_domain(name))
        assert any(case.llm_expectation is not None for case in suite.cases)


# --- runner -----------------------------------------------------------------


def test_provider_error_fails_in_real_mode_but_passes_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _lexical_retrieval(monkeypatch)
    _install_failing_wrapper(monkeypatch)
    domain = _domain("concessoes-manutencao")
    suite = _single_case_suite(domain, "tela-apagada-relogio-pinheiros")

    deterministic = DomainEvalRunner().run(domain=domain, suite=suite)
    results, _ = RealEvalRunner().run_real(domain=domain, suite=suite)

    assert deterministic.passed == 1
    [result] = results
    assert not result.passed
    assert result.error_code == "provider_error"
    assert result.metrics["no_error"] is False
    assert "provider_failure:provider_request_error" in result.failures
    assert "llm_not_called" in result.failures
    # The fallback text is recorded, so a reviewer sees why it failed.
    assert "atendimento humano" in fold(result.answer)


def test_good_answer_passes_and_skips_fallback_required_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _lexical_retrieval(monkeypatch)
    _install_wrapper(monkeypatch, {TELA_MARKER: [GOOD_TELA]})
    domain = _domain("concessoes-manutencao")
    suite = _single_case_suite(domain, "tela-apagada-relogio-pinheiros")

    [result] = RealEvalRunner().run_real(domain=domain, suite=suite)[0]

    assert result.passed, result.failures
    assert result.llm_called
    assert "required_terms" not in result.metrics
    assert result.metrics["any_of"] and result.metrics["allowed_durations"]
    assert result.metrics["expected_citation"]


def test_hallucinated_two_hours_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _lexical_retrieval(monkeypatch)
    _install_wrapper(monkeypatch, {TELA_MARKER: [HALLUCINATED_TELA]})
    domain = _domain("concessoes-manutencao")
    suite = _single_case_suite(domain, "tela-apagada-relogio-pinheiros")

    [result] = RealEvalRunner().run_real(domain=domain, suite=suite)[0]

    assert not result.passed
    assert result.metrics["allowed_durations"] is False
    assert "disallowed_duration:2 horas" in result.failures
    assert "missing_any_of:24 horas|24h" in result.failures


def test_should_escalate_override_applies_only_in_real_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _lexical_retrieval(monkeypatch)
    _install_wrapper(
        monkeypatch,
        {"filmando": ["Nenhuma imagem e guardada; a contagem e agregada (demo)."]},
    )
    domain = _domain("lgpd-titular")
    suite = _single_case_suite(domain, "paineis-filmam")

    [result] = RealEvalRunner().run_real(domain=domain, suite=suite)[0]

    assert result.passed, result.failures
    assert result.escalated is False
    assert suite.cases[0].expectation.should_escalate is True


def test_runs_aggregate_pass_at_all_and_mean_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    _lexical_retrieval(monkeypatch)
    _install_wrapper(monkeypatch, {TELA_MARKER: [GOOD_TELA, HALLUCINATED_TELA, GOOD_TELA]})
    domain = _domain("concessoes-manutencao")
    suite = _single_case_suite(domain, "tela-apagada-relogio-pinheiros")

    results, calls = RealEvalRunner().run_real(domain=domain, suite=suite, runs=3)
    summary = summarize_domain(results, runs=3)

    assert [r.run for r in results] == [1, 2, 3]
    assert [r.passed for r in results] == [True, False, True]
    assert summary["pass_at_all"] == {"passed": 0, "total": 1, "rate": 0.0}
    assert summary["mean_pass_rate"] == pytest.approx(0.6667)
    assert summary["failed_case_ids"] == ["tela-apagada-relogio-pinheiros"]
    durations = summary["metrics"]["allowed_durations"]
    assert (durations["passed"], durations["total"]) == (2, 3)
    assert durations["pass_at_all"] == {"passed": 0, "total": 1}
    assert summary["metrics"]["no_error"]["pass_at_all"] == {"passed": 1, "total": 1}
    assert len([call for call in calls if call.ok]) == 3


# --- CLI --------------------------------------------------------------------


def test_real_mode_aborts_without_key_and_never_calls_provider(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("provider must not be built without a key")

    monkeypatch.setattr("app.llm.service.LLMWrapper", explode)
    monkeypatch.setattr(run_domain_eval, "get_settings", lambda: _fake_settings(key=None))

    code = run_domain_eval.main(["lgpd-titular", "--provider-mode", "real"])
    captured = capsys.readouterr()

    assert code == run_domain_eval.EXIT_REAL_MODE_CONFIG
    payload = json.loads(captured.out)
    assert payload["error"] == "provider_key_missing"
    assert payload["env_var"] == "OPENAI_API_KEY"
    assert "OPENAI_API_KEY" in captured.err


def test_runs_flag_is_rejected_in_deterministic_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run_domain_eval.main(["lgpd-titular", "--runs", "3"])
    assert excinfo.value.code == 2
    _ = capsys.readouterr()


def test_real_mode_report_records_metadata_and_never_the_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _lexical_retrieval(monkeypatch)
    _install_wrapper(
        monkeypatch,
        {
            # Fictitious e-mail: the recorded answer must be sanitized.
            TELA_MARKER: [GOOD_TELA + " Duvidas: fulano.teste@example.com"],
        },
    )
    monkeypatch.setattr(run_domain_eval, "get_settings", lambda: _fake_settings(key=FAKE_KEY))
    report_path = tmp_path / "reports" / "real.json"

    code = run_domain_eval.main(
        [
            "concessoes-manutencao",
            "lgpd-titular",
            "--provider-mode",
            "real",
            "--runs",
            "2",
            "--report",
            str(report_path),
        ]
    )
    stdout = capsys.readouterr().out
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)

    # Generic fake answers do not satisfy every llm_expectation, so some fail.
    assert code == 2
    assert FAKE_KEY not in stdout and FAKE_KEY not in report_text
    assert report["provider_mode"] == "real"
    assert report["model"] == "fake-model-2026-01-01"
    assert report["model_source"] == "provider"
    assert report["models_configured"] == ["gpt-4o-mini"]
    assert report["temperature"] == 0.0
    assert report["runs"] == 2
    assert report["retrieval_backend"] == "lexical"
    assert report["timestamp_utc"].endswith("+00:00")
    assert report["git_commit"] is None or len(report["git_commit"]) == 40
    assert report["cost_usd"] is None
    assert report["usage"]["calls_with_usage"] == 2
    assert report["usage"]["total_tokens"] == 240
    assert set(report["domains"]) == {"concessoes-manutencao", "lgpd-titular"}

    manutencao = report["domains"]["concessoes-manutencao"]
    assert manutencao["pass_at_all"]["total"] == len(_suite(_domain("concessoes-manutencao")).cases)
    assert "tela-apagada-relogio-pinheiros" not in manutencao["failed_case_ids"]
    assert "risco-fio-exposto-abrigo" in manutencao["failed_case_ids"]
    assert report["summary"]["failed_case_ids"]["concessoes-manutencao"] == manutencao["failed_case_ids"]
    assert "any_of" in manutencao["metrics"]
    tela = next(
        item for item in manutencao["case_results"] if item["case_id"] == "tela-apagada-relogio-pinheiros"
    )
    assert tela["passed_runs"] == 2 and tela["pass_at_all"] is True
    answer = tela["results"][0]["answer"]
    assert "example.com" not in answer and "[REDACTED_EMAIL]" in answer
    assert tela["results"][0]["error_code"] is None


# --- deterministic mode stays byte-for-byte compatible ----------------------


def _legacy_run_case(runner: DomainEvalRunner, domain, case) -> EvalCaseResult:
    """Verbatim copy of the pre-real-mode ``DomainEvalRunner._run_case``."""
    response = runner._answer_case(domain=domain, case=case)
    answer = fold(str(response["answer"]))
    references = [str(reference) for reference in response["references"]]
    handoff_reasons = [str(reason) for reason in response["handoff_reasons"]]
    failures: list[str] = []

    if bool(response["escalated"]) != case.expectation.should_escalate:
        failures.append("unexpected_escalation")
    for term in case.expectation.required_terms:
        if fold(term) not in answer:
            failures.append(f"missing_required_term:{term}")
    for term in case.expectation.forbidden_terms:
        if fold(term) in answer:
            failures.append(f"forbidden_term_present:{term}")
    for expected_reference in case.expectation.expected_references:
        if not any(expected_reference in reference for reference in references):
            failures.append(f"missing_reference:{expected_reference}")
    if case.expectation.allowed_handoff_reasons:
        for reason in handoff_reasons:
            if reason not in case.expectation.allowed_handoff_reasons:
                failures.append(f"unexpected_handoff_reason:{reason}")
    for reason in case.expectation.required_handoff_reasons:
        if reason not in handoff_reasons:
            failures.append(f"missing_handoff_reason:{reason}")

    return EvalCaseResult(
        case_id=case.id,
        passed=not failures,
        failures=failures,
        escalated=bool(response["escalated"]),
        confidence=float(response["confidence"]),
        handoff_reasons=handoff_reasons,
        references=references,
    )


@pytest.mark.parametrize("domain_name", ["concessoes-manutencao", "lgpd-titular"])
@pytest.mark.parametrize(
    "file",
    [
        "evals/cases.yaml",
        "evals/confinement/out_of_scope.yaml",
        "evals/confinement/redefinition.yaml",
        "evals/confinement/secrets.yaml",
    ],
)
def test_deterministic_runner_matches_legacy_logic(
    monkeypatch: pytest.MonkeyPatch, domain_name: str, file: str
) -> None:
    _lexical_retrieval(monkeypatch)
    _install_failing_wrapper(monkeypatch)
    domain = _domain(domain_name)
    suite = _suite(domain, file)
    runner = DomainEvalRunner()

    current = runner.run(domain=domain, suite=suite)
    legacy = [_legacy_run_case(runner, domain, case) for case in suite.cases]

    assert [r.model_dump() for r in current.results] == [r.model_dump() for r in legacy]
    assert current.failed == 0


def test_deterministic_cli_output_has_no_real_mode_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _lexical_retrieval(monkeypatch)
    _install_failing_wrapper(monkeypatch)
    monkeypatch.setattr(run_domain_eval, "get_settings", lambda: _fake_settings(key=None))
    report_path = tmp_path / "det.json"

    code = run_domain_eval.main(["concessoes-manutencao", "--report", str(report_path)])
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)

    assert code == 0
    assert set(payload) == {"domain", "total", "passed", "failed", "results"}
    assert set(payload["results"][0]) == {
        "case_id",
        "passed",
        "failures",
        "escalated",
        "confidence",
        "handoff_reasons",
        "references",
    }
    assert report_path.read_text(encoding="utf-8") == stdout.replace("\r\n", "\n")
