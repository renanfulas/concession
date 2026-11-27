"""Opt-in real-LLM eval mode (``--provider-mode real``). Not a CI gate.

The deterministic mode runs without an LLM key: every non-blocked case ends in
``provider_error`` and the answer is the domain's fallback text. That is fine
for the gate (it proves retrieval, classification and escalation), but it would
make a real-LLM run look perfect with an invalid key. This mode therefore:

- fails any case where the provider failed (``provider_error`` or any other
  ``error_code``), so a bad key cannot pass;
- applies the case's base ``expectation`` (escalation, references, handoff
  reasons, forbidden terms), skipping base ``required_terms`` only when the
  model actually generated the answer, since those terms were calibrated
  against the fallback text;
- applies the optional ``llm_expectation`` block (``any_of``,
  ``forbidden_terms``, ``allowed_durations``, ``expected_citation``);
- repeats the suite ``runs`` times and reports pass@all and mean pass rate.

All checks are deterministic string/regex checks on the answer. Answers are
sanitized and truncated before they reach the report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any

from app.core.errors import ProviderError
from app.core.persistence_sanitize import sanitize_for_persistence
from app.domain_engine.models import DomainConfig
from app.evals.llm_metrics import evaluate_llm_expectation
from app.evals.models import EvalCase, EvalSuite, RealEvalCaseResult
from app.evals.runner import DomainEvalRunner, evaluate_expectation
from app.llm.base import BaseLLMProvider
from app.orchestration.chat_flow import ChatFlowService

ANSWER_MAX_CHARS = 600
REPORT_VERSION = 1

# Domain provider -> settings attribute and env var that hold its key.
PROVIDER_KEYS = {
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
}

# Prefix of a base-expectation failure -> metric name in the report.
_BASE_FAILURE_METRICS = {
    "unexpected_escalation": "escalation",
    "missing_required_term": "required_terms",
    "forbidden_term_present": "forbidden_terms",
    "missing_reference": "references",
    "unexpected_handoff_reason": "handoff_reasons",
    "missing_handoff_reason": "handoff_reasons",
}


class RealModeConfigError(Exception):
    """Real mode cannot start (no external provider or no key configured)."""

    def __init__(self, code: str, message: str, **details: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def ensure_provider_key(domain: DomainConfig, settings: Any) -> str:
    """Return the domain's provider name, or raise if real mode cannot run.

    Checks only that a key is present in settings; the value is never read
    out, printed or logged.
    """
    provider = domain.llm.provider.lower().strip()
    if provider not in PROVIDER_KEYS:
        raise RealModeConfigError(
            "real_mode_requires_external_provider",
            f"O dominio {domain.name} usa o provider '{provider}'; o modo real "
            "exige openai ou anthropic no bloco llm do domain.yaml.",
            domain=domain.name,
            provider=provider,
        )
    attribute, env_var = PROVIDER_KEYS[provider]
    if not getattr(settings, attribute, None):
        raise RealModeConfigError(
            "provider_key_missing",
            f"Modo real exige {env_var} configurada (ambiente ou .env) para o "
            f"dominio {domain.name}. Nada foi executado.",
            domain=domain.name,
            provider=provider,
            env_var=env_var,
        )
    return provider


@dataclass
class _CallRecord:
    ok: bool
    failure_kind: str | None = None
    model: str | None = None
    usage: dict[str, int] | None = None
    temperature: float | None = None


@dataclass
class ProviderCallRecorder:
    """Collects provider outcomes per case, without prompt or answer text."""

    calls: list[_CallRecord] = field(default_factory=list)

    def reset(self) -> None:
        self.calls = []


class _RecordingProvider(BaseLLMProvider):
    def __init__(self, inner: BaseLLMProvider, recorder: ProviderCallRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def generate_answer(self, prompt: str) -> str:
        temperature = getattr(self._inner, "temperature", None)
        try:
            answer = self._inner.generate_answer(prompt)
        except ProviderError as exc:
            self._recorder.calls.append(
                _CallRecord(ok=False, failure_kind=exc.failure_kind, temperature=temperature)
            )
            raise
        metadata = getattr(self._inner, "last_call_metadata", None) or {}
        usage = metadata.get("usage") if isinstance(metadata, dict) else None
        model = metadata.get("model") if isinstance(metadata, dict) else None
        self._recorder.calls.append(
            _CallRecord(
                ok=True,
                model=model if isinstance(model, str) else None,
                usage=dict(usage) if isinstance(usage, dict) else None,
                temperature=temperature,
            )
        )
        return answer


class _RecordingLLMService:
    """Duck-types ``LLMService.get_provider`` and records every outcome."""

    def __init__(self, inner: Any, recorder: ProviderCallRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def get_provider(self, domain: DomainConfig, api_key: str | None = None) -> BaseLLMProvider:
        try:
            provider = self._inner.get_provider(domain, api_key=api_key)
        except ProviderError as exc:
            self._recorder.calls.append(_CallRecord(ok=False, failure_kind=exc.failure_kind))
            raise
        return _RecordingProvider(provider, self._recorder)


def _sanitize_answer(answer: str) -> str:
    sanitized = sanitize_for_persistence(answer) or ""
    if len(sanitized) > ANSWER_MAX_CHARS:
        return sanitized[:ANSWER_MAX_CHARS] + "...[truncated]"
    return sanitized


def _base_metric(failure: str) -> str:
    return _BASE_FAILURE_METRICS.get(failure.split(":", 1)[0], "base_other")


class RealEvalRunner(DomainEvalRunner):
    """Runs a suite against the configured real provider and scores it."""

    def __init__(self, chat_flow: ChatFlowService | None = None) -> None:
        super().__init__(chat_flow=chat_flow)
        self.recorder = ProviderCallRecorder()
        self.chat_flow.llm_service = _RecordingLLMService(
            self.chat_flow.llm_service, self.recorder
        )

    def run_real(
        self,
        domain: DomainConfig,
        suite: EvalSuite,
        *,
        runs: int = 1,
    ) -> tuple[list[RealEvalCaseResult], list[_CallRecord]]:
        results: list[RealEvalCaseResult] = []
        calls: list[_CallRecord] = []
        for run in range(1, runs + 1):
            for case in suite.cases:
                self.recorder.reset()
                results.append(self._run_real_case(domain=domain, case=case, run=run))
                calls.extend(self.recorder.calls)
        return results, calls

    def _run_real_case(self, *, domain: DomainConfig, case: EvalCase, run: int) -> RealEvalCaseResult:
        try:
            response = self._answer_case(domain=domain, case=case)
        except Exception as exc:  # noqa: BLE001 - one broken case must not stop the run.
            failure = f"runner_exception:{exc.__class__.__name__}"
            return RealEvalCaseResult(
                case_id=case.id,
                passed=False,
                failures=[failure],
                escalated=False,
                confidence=0.0,
                run=run,
                answer="",
                metrics={"no_error": False},
            )

        answer = str(response["answer"])
        references = [str(reference) for reference in response["references"]]
        handoff_reasons = [str(reason) for reason in response["handoff_reasons"]]
        error_code = response.get("error_code")
        provider_failure_kind = response.get("provider_failure_kind")
        provider_failures = [call for call in self.recorder.calls if not call.ok]
        llm_called = any(call.ok for call in self.recorder.calls) and not provider_failures

        metric_failures: dict[str, list[str]] = {}

        no_error: list[str] = []
        for call in provider_failures:
            no_error.append(f"provider_failure:{call.failure_kind or 'unknown'}")
        if error_code:
            no_error.append(f"error_code:{error_code}")
        if "provider_error" in handoff_reasons and not error_code:
            no_error.append("error_code:provider_error")
        metric_failures["no_error"] = no_error

        expectation = case.expectation
        llm_expectation = case.llm_expectation
        if llm_expectation is not None and llm_expectation.should_escalate is not None:
            expectation = expectation.model_copy(
                update={"should_escalate": llm_expectation.should_escalate}
            )

        check_required_terms = not llm_called
        metric_failures["escalation"] = []
        if expectation.expected_references:
            metric_failures["references"] = []
        if expectation.allowed_handoff_reasons or expectation.required_handoff_reasons:
            metric_failures["handoff_reasons"] = []
        if expectation.required_terms and check_required_terms:
            metric_failures["required_terms"] = []
        if expectation.forbidden_terms:
            metric_failures["forbidden_terms"] = []
        for failure in evaluate_expectation(
            expectation, response, check_required_terms=check_required_terms
        ):
            metric_failures.setdefault(_base_metric(failure), []).append(failure)

        if llm_expectation is not None:
            metric_failures["llm_answered"] = [] if llm_called else ["llm_not_called"]
            metric_failures.update(
                evaluate_llm_expectation(llm_expectation, answer=answer, references=references)
            )

        failures = [failure for items in metric_failures.values() for failure in items]
        return RealEvalCaseResult(
            case_id=case.id,
            passed=not failures,
            failures=failures,
            escalated=bool(response["escalated"]),
            confidence=float(response["confidence"]),
            handoff_reasons=handoff_reasons,
            references=references,
            run=run,
            answer=_sanitize_answer(answer),
            error_code=str(error_code) if error_code else None,
            provider_failure_kind=str(provider_failure_kind) if provider_failure_kind else None,
            llm_called=llm_called,
            metrics={name: not items for name, items in metric_failures.items()},
        )


def _rate(passed: int, total: int) -> float | None:
    return round(passed / total, 4) if total else None


def summarize_domain(results: list[RealEvalCaseResult], runs: int) -> dict[str, Any]:
    """Aggregate per-run results into pass@all and mean pass rate."""
    case_ids: list[str] = []
    by_case: dict[str, list[RealEvalCaseResult]] = {}
    for result in results:
        if result.case_id not in by_case:
            case_ids.append(result.case_id)
        by_case.setdefault(result.case_id, []).append(result)

    pass_at_all = [case_id for case_id in case_ids if all(r.passed for r in by_case[case_id])]
    run_passes = sum(1 for result in results if result.passed)

    metric_names: list[str] = []
    for result in results:
        for name in result.metrics:
            if name not in metric_names:
                metric_names.append(name)
    metrics: dict[str, Any] = {}
    for name in metric_names:
        applicable = [r for r in results if name in r.metrics]
        passed = sum(1 for r in applicable if r.metrics[name])
        cases_with_metric = [c for c in case_ids if any(name in r.metrics for r in by_case[c])]
        cases_all = [
            c
            for c in cases_with_metric
            if all(r.metrics.get(name, True) for r in by_case[c])
        ]
        metrics[name] = {
            "passed": passed,
            "total": len(applicable),
            "mean_pass_rate": _rate(passed, len(applicable)),
            "pass_at_all": {"passed": len(cases_all), "total": len(cases_with_metric)},
        }

    return {
        "cases": len(case_ids),
        "runs": runs,
        "pass_at_all": {
            "passed": len(pass_at_all),
            "total": len(case_ids),
            "rate": _rate(len(pass_at_all), len(case_ids)),
        },
        "mean_pass_rate": _rate(run_passes, len(results)),
        "metrics": metrics,
        "failed_case_ids": [c for c in case_ids if c not in pass_at_all],
        "case_results": [
            {
                "case_id": case_id,
                "passed_runs": sum(1 for r in by_case[case_id] if r.passed),
                "runs": len(by_case[case_id]),
                "pass_at_all": case_id in pass_at_all,
                "results": [r.model_dump() for r in by_case[case_id]],
            }
            for case_id in case_ids
        ],
    }


def summarize_usage(calls: list[_CallRecord]) -> dict[str, Any] | None:
    """Sum token usage when the provider exposed it; None otherwise."""
    with_usage = [call.usage for call in calls if call.ok and call.usage]
    if not with_usage:
        return None
    totals: dict[str, int] = {}
    for usage in with_usage:
        for key, value in usage.items():
            totals[key] = totals.get(key, 0) + int(value)
    return {
        **totals,
        "calls_with_usage": len(with_usage),
        "llm_calls_ok": sum(1 for call in calls if call.ok),
    }


def git_state(cwd: Path | None = None) -> tuple[str | None, bool | None]:
    """Return (HEAD sha, dirty) or (None, None) when git is unavailable."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None, None
    return (sha or None), bool(status.strip())


def build_report(
    *,
    domain_runs: list[dict[str, Any]],
    runs: int,
    retrieval_backend: str,
    suite_file: str,
    git_commit: str | None,
    git_dirty: bool | None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Build the JSON report.

    ``domain_runs`` items: ``{"domain": DomainConfig, "provider": str,
    "results": [...], "calls": [...]}``.
    """
    from app.llm.wrapper import DEFAULT_TEMPERATURE

    all_calls = [call for item in domain_runs for call in item["calls"]]
    reported_models = sorted({call.model for call in all_calls if call.ok and call.model})
    configured_models = sorted({item["domain"].llm.model for item in domain_runs})
    temperatures = sorted(
        {call.temperature for call in all_calls if call.temperature is not None}
    )

    domains: dict[str, Any] = {}
    total_cases = 0
    total_pass_at_all = 0
    total_results = 0
    total_run_passes = 0
    for item in domain_runs:
        domain: DomainConfig = item["domain"]
        summary = summarize_domain(item["results"], runs)
        summary = {
            "provider": item["provider"],
            "model_configured": domain.llm.model,
            "models_reported": sorted(
                {call.model for call in item["calls"] if call.ok and call.model}
            ),
            **summary,
        }
        domains[domain.name] = summary
        total_cases += summary["cases"]
        total_pass_at_all += summary["pass_at_all"]["passed"]
        total_results += len(item["results"])
        total_run_passes += sum(1 for r in item["results"] if r.passed)

    return {
        "report_version": REPORT_VERSION,
        "provider_mode": "real",
        "timestamp_utc": (timestamp or datetime.now(timezone.utc)).isoformat(),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "providers": sorted({item["provider"] for item in domain_runs}),
        "model": ", ".join(reported_models or configured_models),
        "model_source": "provider" if reported_models else "config",
        "models_reported": reported_models,
        "models_configured": configured_models,
        "temperature": temperatures[0] if len(temperatures) == 1 else (temperatures or DEFAULT_TEMPERATURE),
        "temperature_source": "provider_wrapper" if temperatures else "wrapper_default",
        "runs": runs,
        "retrieval_backend": retrieval_backend,
        "suite_file": suite_file,
        "summary": {
            "cases": total_cases,
            "pass_at_all": {
                "passed": total_pass_at_all,
                "total": total_cases,
                "rate": _rate(total_pass_at_all, total_cases),
            },
            "mean_pass_rate": _rate(total_run_passes, total_results),
            "failed_case_ids": {
                name: summary["failed_case_ids"]
                for name, summary in domains.items()
                if summary["failed_case_ids"]
            },
        },
        "domains": domains,
        "usage": summarize_usage(all_calls),
        "cost_usd": None,
        "cost_note": (
            "O provider nao informa custo. Calcule a partir de usage com a "
            "tabela de precos vigente do provider; este relatorio nao estima."
        ),
    }
