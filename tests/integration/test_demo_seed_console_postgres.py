"""Opt-in PostgreSQL proof: demo seed -> real priority INSERT -> console list.

Runs ``scripts/seed_demo_cases.py`` against a disposable database and reads
the cases back through ``GET /web/support/cases`` with a real staff OTP login
(memory delivery). This is what proves, on a real Postgres, that the priority
resolved from each ``domain.yaml`` rule reaches ``support_cases.priority``
through ``record_chat`` and comes back with the per-domain SLA ``basis``.
Runs only when ``PHASE0_TEST_DATABASE_URL`` points at a disposable database.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.runtime import DatabaseRuntime
from app.domain_engine.loader import DomainLoader
from scripts.seed_demo_cases import (
    DEMO_CASES,
    SEED_CHANNEL,
    SEED_DOMAINS,
    SEED_STAFF_NAME,
    SEED_STAFF_PHONE,
    reset_demo_cases,
    seed_demo_cases,
)


DATABASE_URL = os.getenv("PHASE0_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PHASE0_TEST_DATABASE_URL to run PostgreSQL integration tests",
)

# Test-only literals, never reused outside this disposable database.
IDENTITY_SECRET = "demo-seed-identity-test-secret"
OTP_SECRET = "demo-seed-otp-test-secret"


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    if not DATABASE_URL:
        return
    env = {**os.environ, "DATABASE_URL": DATABASE_URL}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.migrate", "apply"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, "migrations failed in disposable test database"


def _count_seed_rows() -> dict[str, int]:
    assert DATABASE_URL
    runtime = DatabaseRuntime(
        SimpleNamespace(
            persistence_backend="postgres",
            web_auth_storage_backend="disabled",
            enable_outbox_ingress=False,
            session_domain_store_backend="memory",
            database_url=DATABASE_URL,
            database_pool_min_size=1,
            database_pool_max_size=2,
            database_connect_timeout_seconds=5,
            database_query_timeout_seconds=10,
            retrieval_backend="lexical",
        )
    )
    runtime.open()
    try:
        with runtime.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM support_cases WHERE channel = %s",
                    (SEED_CHANNEL,),
                )
                cases = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT count(*) FROM operational_outbox WHERE request_id LIKE 'demo-seed-%'"
                )
                outbox = cursor.fetchone()[0]
                cursor.execute(
                    "SELECT count(*) FROM staff_members WHERE display_name = %s",
                    (SEED_STAFF_NAME,),
                )
                staff = cursor.fetchone()[0]
    finally:
        runtime.close()
    return {"cases": cases, "outbox": outbox, "staff": staff}


def _seed() -> list:
    assert DATABASE_URL
    return seed_demo_cases(
        DATABASE_URL,
        app_env="test",
        identity_hash_secret=IDENTITY_SECRET,
        persistence_hash_secret=os.getenv("PERSISTENCE_HASH_SECRET"),
        domains_path=Path("domains"),
    )


@pytest.fixture
def console_client(monkeypatch: pytest.MonkeyPatch):
    from app.main import create_app

    assert DATABASE_URL
    env = {
        "APP_ENV": "development",
        "API_SECRET_KEY": "local-dev-api-key",
        "DATABASE_URL": DATABASE_URL,
        "PERSISTENCE_BACKEND": "postgres",
        "PERSISTENCE_HASH_SECRET": os.getenv(
            "PERSISTENCE_HASH_SECRET", "demo-seed-persistence-test-secret"
        ),
        "WEB_AUTH_STORAGE_BACKEND": "memory",
        "WEB_AUTH_OTP_DELIVERY_TRANSPORT": "memory",
        "ENABLE_OUTBOX_INGRESS": "false",
        "SESSION_DOMAIN_STORE_BACKEND": "memory",
        "RETRIEVAL_BACKEND": "lexical",
        "ENABLE_SUPPORT_CONSOLE": "true",
        "IDENTITY_HASH_SECRET": IDENTITY_SECRET,
        "OTP_DIGEST_SECRET": OTP_SECRET,
        "SUPPORT_CONSOLE_TIMEZONE": "America/Sao_Paulo",
        "DOMAINS_PATH": "domains",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            yield client, app
    finally:
        get_settings.cache_clear()


def _login(client: TestClient, app) -> str:
    start = client.post("/web/support/auth/start", json={"phone": SEED_STAFF_PHONE})
    assert start.status_code == 202
    code = app.state.support_console_runtime.delivery.requests[-1].code
    confirm = client.post(
        "/web/support/auth/confirm",
        json={
            "challenge_id": start.json()["challenge_id"],
            "code": code,
            "phone": SEED_STAFF_PHONE,
        },
    )
    assert confirm.status_code == 200
    return confirm.json()["display_name"]


def test_seed_is_idempotent_and_reset_removes_only_its_rows() -> None:
    first = _seed()
    second = _seed()
    assert len(first) == len(second) == len(DEMO_CASES)
    counts = _count_seed_rows()
    # Re-rodar substitui, nunca duplica; nada fica no outbox para despacho.
    assert counts == {"cases": len(DEMO_CASES), "outbox": 0, "staff": 1}

    assert DATABASE_URL
    removed = reset_demo_cases(
        DATABASE_URL, app_env="test", identity_hash_secret=IDENTITY_SECRET
    )
    assert removed["cases"] == len(DEMO_CASES)
    assert removed["staff"] == "deleted"
    assert _count_seed_rows() == {"cases": 0, "outbox": 0, "staff": 0}


def test_seed_refuses_staging_env_even_on_local_database() -> None:
    from scripts.seed_demo_cases import SeedRefused

    assert DATABASE_URL
    with pytest.raises(SeedRefused):
        seed_demo_cases(
            DATABASE_URL,
            app_env="staging",
            identity_hash_secret=IDENTITY_SECRET,
        )


def test_console_lists_seeded_cases_with_priority_color_and_basis(console_client) -> None:
    client, app = console_client
    seeded = _seed()
    seeded_ids = {item.case_id for item in seeded}
    expected_by_id = {
        item.case_id: next(c for c in DEMO_CASES if c.key == item.key) for item in seeded
    }

    assert _login(client, app) == SEED_STAFF_NAME

    loader = DomainLoader(Path("domains"))
    for domain in SEED_DOMAINS:
        config = loader.load(domain)
        assert config is not None and config.sla is not None
        response = client.get(
            "/web/support/cases", params={"domain": domain, "limit": 100}
        )
        assert response.status_code == 200
        cases = [c for c in response.json()["cases"] if c["case_id"] in seeded_ids]
        expected = [c for c in DEMO_CASES if c.domain == domain]
        assert len(cases) == len(expected)

        colors = set()
        for case in cases:
            demo = expected_by_id[case["case_id"]]
            assert case["domain"] == domain
            assert case["channel"] == SEED_CHANNEL
            # Prioridade veio da regra do domain.yaml, pelo INSERT do record_chat.
            assert case["priority"] == demo.expected_priority
            assert case["status"] == demo.state
            assert case["reason_codes"]
            assert case["summary"] and "[demo]" in case["summary"]
            sla = case["sla"]
            assert sla["basis"] == config.sla.basis
            color = "paused" if sla["paused"] else sla["color"]
            assert color == demo.expected_color, demo.key
            colors.add(color)
            if demo.state != "open":
                assert case["assignee"] == {"display_name": SEED_STAFF_NAME}
            else:
                assert case["assignee"] is None
        assert colors == {"red", "yellow", "green", "paused"}
        priorities = {case["priority"] for case in cases}
        assert priorities == {c.expected_priority for c in expected}

    # Filtros de cor do console batem com o que o seed prometeu.
    for color in ("red", "yellow", "green", "paused"):
        found: set[str] = set()
        for domain in SEED_DOMAINS:
            response = client.get(
                "/web/support/cases",
                params={"domain": domain, "color": color, "limit": 100},
            )
            assert response.status_code == 200
            found |= {c["case_id"] for c in response.json()["cases"]}
        assert found & seeded_ids == {
            item.case_id for item in seeded if item.color == color
        }, color


@pytest.fixture(autouse=True)
def _reset_after_each_test():
    yield
    if DATABASE_URL:
        reset_demo_cases(
            DATABASE_URL, app_env="test", identity_hash_secret=IDENTITY_SECRET
        )
