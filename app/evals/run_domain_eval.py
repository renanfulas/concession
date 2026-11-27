import argparse
import json
from pathlib import Path
import sys

from app.core.config import get_settings
from app.domain_engine.loader import DomainLoader
from app.evals.loader import EvalSuiteLoader
from app.evals.runner import DomainEvalRunner

# Exit codes: 0 all passed, 1 setup error (domain/suite), 2 case failures,
# 3 real mode cannot start (no external provider or key not configured).
EXIT_REAL_MODE_CONFIG = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local domain evals.")
    parser.add_argument(
        "domain",
        nargs="+",
        help=(
            "Domain name, for example suporte-vps-whatsapp. The real mode "
            "accepts several domains in one report."
        ),
    )
    parser.add_argument(
        "--file",
        default="evals/cases.yaml",
        help="Eval file path relative to the domain root.",
    )
    parser.add_argument(
        "--provider-mode",
        choices=("deterministic", "real"),
        default="deterministic",
        help=(
            "deterministic (default, CI gate) keeps the current behavior. "
            "real is opt-in: needs a provider key, fails on provider_error and "
            "applies llm_expectation checks."
        ),
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Repetitions per case (real mode only). Reports pass@all and mean pass rate.",
    )
    parser.add_argument("--report", help="Write the JSON result to this path.")
    return parser


def _load(settings, domain_name: str, file: str):
    domain = DomainLoader(settings.domains_path).load(domain_name)
    if domain is None:
        return None, None, {"error": "domain_not_found", "domain": domain_name}

    suite_path = domain.root_path / Path(file)
    suite = EvalSuiteLoader().load(suite_path)
    if suite is None:
        return None, None, {"error": "eval_suite_not_found_or_invalid", "path": str(suite_path)}

    if suite.domain != domain.name:
        return None, None, {
            "error": "eval_suite_domain_mismatch",
            "domain": domain.name,
            "suite_domain": suite.domain,
        }
    return domain, suite, None


def _write_report(path: str | None, payload: str) -> None:
    if not path:
        return
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(payload + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.provider_mode == "deterministic":
        if args.runs != 1:
            parser.error("--runs only applies to --provider-mode real")
        if len(args.domain) != 1:
            parser.error("deterministic mode takes exactly one domain")
        return _run_deterministic(args)
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    return _run_real(args)


def _run_deterministic(args: argparse.Namespace) -> int:
    settings = get_settings()
    domain, suite, error = _load(settings, args.domain[0], args.file)
    if error is not None:
        print(json.dumps(error))
        return 1

    result = DomainEvalRunner().run(domain=domain, suite=suite)
    payload = result.model_dump_json(indent=2)
    print(payload)
    _write_report(args.report, payload)
    return 0 if result.failed == 0 else 2


def _run_real(args: argparse.Namespace) -> int:
    from app.evals.real_mode import (
        RealEvalRunner,
        RealModeConfigError,
        build_report,
        ensure_provider_key,
        git_state,
    )

    settings = get_settings()
    loaded = []
    for domain_name in args.domain:
        domain, suite, error = _load(settings, domain_name, args.file)
        if error is not None:
            print(json.dumps(error))
            return 1
        try:
            provider = ensure_provider_key(domain, settings)
        except RealModeConfigError as exc:
            print(json.dumps({"error": exc.code, **exc.details}))
            print(exc.message, file=sys.stderr)
            return EXIT_REAL_MODE_CONFIG
        loaded.append((domain, suite, provider))

    domain_runs = []
    for domain, suite, provider in loaded:
        runner = RealEvalRunner()
        results, calls = runner.run_real(domain=domain, suite=suite, runs=args.runs)
        domain_runs.append(
            {"domain": domain, "provider": provider, "results": results, "calls": calls}
        )

    git_commit, git_dirty = git_state()
    report = build_report(
        domain_runs=domain_runs,
        runs=args.runs,
        retrieval_backend=settings.retrieval_backend,
        suite_file=args.file,
        git_commit=git_commit,
        git_dirty=git_dirty,
    )
    # stdout stays ASCII-escaped (Windows consoles); the file keeps UTF-8.
    print(json.dumps(report, indent=2))
    _write_report(args.report, json.dumps(report, indent=2, ensure_ascii=False))
    summary = report["summary"]["pass_at_all"]
    return 0 if summary["passed"] == summary["total"] else 2


if __name__ == "__main__":
    sys.exit(main())
