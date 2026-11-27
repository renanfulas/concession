"""Unit guards for scripts/seed_demo_cases.py (no database needed).

The PostgreSQL round trip lives in
``tests/integration/test_demo_seed_console_postgres.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.support.sla import GREEN_BELOW
from scripts.seed_demo_cases import (
    DEMO_CASES,
    SEED_DOMAINS,
    SEED_STAFF_PHONE,
    SeedRefused,
    check_environment,
    load_seed_domains,
    main,
    resolve_demo_case,
)


LOCAL_URL = "postgresql://postgres:pw@127.0.0.1:55432/supportfaq_phase0"


@pytest.mark.parametrize("app_env", [None, "", "staging", "production", "prod", "dev"])
def test_refuses_without_explicit_development_or_test_env(app_env) -> None:
    with pytest.raises(SeedRefused):
        check_environment(app_env, LOCAL_URL)


@pytest.mark.parametrize(
    "database_url",
    [
        "",
        "postgresql://postgres:pw@db.example.test:5432/supportfaq_phase0",
        "postgresql://postgres:pw@10.0.0.5:5432/supportfaq_phase0",
        "postgresql://postgres:pw@127.0.0.1,db.example.test:5432/supportfaq_phase0",
        "postgresql:///supportfaq_phase0",
    ],
)
def test_refuses_non_local_database_host(database_url: str) -> None:
    with pytest.raises(SeedRefused):
        check_environment("development", database_url)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "postgres", "postgres_test"])
@pytest.mark.parametrize("app_env", ["development", "test", "TEST"])
def test_accepts_local_dev_and_test(host: str, app_env: str) -> None:
    check_environment(app_env, f"postgresql://postgres:pw@{host}:5432/supportfaq_phase0")


@pytest.mark.parametrize("app_env", [None, "production"])
def test_public_demo_lifts_only_the_app_env_check(app_env) -> None:
    check_environment(app_env, LOCAL_URL, public_demo=True)
    with pytest.raises(SeedRefused):
        check_environment(
            app_env,
            "postgresql://postgres:pw@db.example.test:5432/supportfaq_phase0",
            public_demo=True,
        )


def test_cli_refuses_before_touching_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:secret-pw@db.example.test/x")
    assert main([]) == 2
    assert main(["--reset"]) == 2
    captured = capsys.readouterr()
    # A URL (com senha) nunca e ecoada.
    assert "secret-pw" not in captured.err + captured.out


def test_demo_cases_resolve_declared_priority_through_domain_rules() -> None:
    configs = load_seed_domains(Path("domains"))
    for case in DEMO_CASES:
        reasons, priority = resolve_demo_case(configs[case.domain], case)
        assert priority == case.expected_priority, case.key
        assert reasons, case.key


def test_demo_cases_cover_domains_priorities_and_colors() -> None:
    assert {case.domain for case in DEMO_CASES} == set(SEED_DOMAINS)
    manut = {c.expected_priority for c in DEMO_CASES if c.domain == "concessoes-manutencao"}
    assert manut == {"urgent", "high", "normal", "low"}
    # lgpd-titular nao declara regra `low`: cobre o que as regras produzem.
    lgpd = {c.expected_priority for c in DEMO_CASES if c.domain == "lgpd-titular"}
    assert lgpd == {"urgent", "high", "normal"}
    for domain in SEED_DOMAINS:
        colors = {c.expected_color for c in DEMO_CASES if c.domain == domain}
        assert colors == {"red", "yellow", "green", "paused"}, domain
    for case in DEMO_CASES:
        if case.expected_color == "green":
            assert case.elapsed_ratio < GREEN_BELOW
        elif case.expected_color == "yellow":
            assert GREEN_BELOW <= case.elapsed_ratio <= 1.0
        elif case.expected_color == "red":
            assert case.elapsed_ratio > 1.0
        else:
            assert case.state == "waiting_customer"


def test_demo_content_is_fictitious() -> None:
    assert SEED_STAFF_PHONE.startswith("+55119000000")
    keys = [case.key for case in DEMO_CASES]
    assert len(keys) == len(set(keys))
    for case in DEMO_CASES:
        assert "[demo]" in case.question
        assert "@" not in case.question
    manut_codes = [c for c in DEMO_CASES if c.domain == "concessoes-manutencao"]
    inventory = Path(
        "domains/concessoes-manutencao/knowledge/articles/inventario-ativos-demo.md"
    ).read_text(encoding="utf-8")
    for case in manut_codes:
        code = next(
            token.strip(".,()")
            for token in case.question.split()
            if token[:4] in {"REL-", "ABR-", "PNL-"}
        )
        assert code in inventory, case.key
