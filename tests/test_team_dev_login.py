"""Login de desenvolvimento da /team (Fase 1, item 4).

Aprovado com duas condicoes: APP_ENV=development explicito e recusa de
headers de proxy enquanto o Host e validado. Cada guarda tem um teste.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.support.dev_login import (
    DEMO_STAFF_PHONE,
    PROXY_HEADERS,
    dev_login_allowed,
    host_name,
)
from app.support.staff_auth import StaffMember
from app.web_auth.service import _hmac_digest

IDENTITY_SECRET = "identity-test-secret"
OTP_SECRET = "otp-test-secret"
CSRF = {"X-Requested-With": "XMLHttpRequest"}
ALLOWED = SimpleNamespace(enable_team_dev_login=True, app_env="development")


# --------------------------------------------------------------------------- #
# Boot: APP_ENV=development explicito
# --------------------------------------------------------------------------- #


@contextmanager
def _env(**values: str):
    saved = dict(os.environ)
    os.environ.pop("APP_ENV", None)
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_flag_without_explicit_app_env_refuses_to_boot() -> None:
    with _env(ENABLE_TEAM_DEV_LOGIN="true"):
        with pytest.raises(ValueError, match="explicit APP_ENV=development"):
            Settings(_env_file=None)


@pytest.mark.parametrize("app_env", ["local", "dev", "staging", "test"])
def test_flag_outside_development_refuses_to_boot(app_env: str) -> None:
    with _env(ENABLE_TEAM_DEV_LOGIN="true", APP_ENV=app_env, API_SECRET_KEY="x"):
        with pytest.raises(ValueError):
            Settings(_env_file=None)


def test_flag_with_explicit_development_boots() -> None:
    with _env(ENABLE_TEAM_DEV_LOGIN="true", APP_ENV="development"):
        assert Settings(_env_file=None).enable_team_dev_login is True


def test_flag_is_off_by_default() -> None:
    with _env(APP_ENV="development"):
        assert Settings(_env_file=None).enable_team_dev_login is False


# --------------------------------------------------------------------------- #
# Guardas por pedido
# --------------------------------------------------------------------------- #


def _allowed(*, settings=ALLOWED, client="127.0.0.1", host="127.0.0.1:8077", headers=None) -> bool:
    return dev_login_allowed(settings, client_host=client, host_header=host, headers=headers or {})


def test_loopback_peer_and_host_without_proxy_headers_is_allowed() -> None:
    assert _allowed()
    assert _allowed(client="::1", host="[::1]:8077")
    assert _allowed(host="localhost")


def test_flag_off_or_other_env_is_refused() -> None:
    assert not _allowed(settings=SimpleNamespace(enable_team_dev_login=False, app_env="development"))
    assert not _allowed(settings=SimpleNamespace(enable_team_dev_login=True, app_env="staging"))


@pytest.mark.parametrize("client", ["10.0.0.5", "192.168.1.20", "203.0.113.7", "testclient", None])
def test_non_loopback_peer_is_refused(client) -> None:
    assert not _allowed(client=client)


@pytest.mark.parametrize(
    "host",
    ["concession.example.test", "192.168.1.20:8077", "127.0.0.1.nip.io", "", None, "::1"],
)
def test_non_loopback_host_is_refused(host) -> None:
    assert not _allowed(host=host)


@pytest.mark.parametrize("header", PROXY_HEADERS)
def test_any_proxy_header_is_refused(header: str) -> None:
    assert not _allowed(headers={header: "203.0.113.7"})
    assert not _allowed(headers={header.upper(): "203.0.113.7"})


def test_host_name_parsing() -> None:
    assert host_name("LOCALHOST:8077") == "localhost"
    assert host_name("[::1]:8077") == "::1"
    assert host_name("127.0.0.1") == "127.0.0.1"
    assert host_name("::1") is None


def test_demo_phone_matches_the_seed_operator() -> None:
    from scripts.seed_demo_cases import SEED_STAFF_PHONE

    assert DEMO_STAFF_PHONE == SEED_STAFF_PHONE


# --------------------------------------------------------------------------- #
# Rotas
# --------------------------------------------------------------------------- #


@contextmanager
def _client(monkeypatch: pytest.MonkeyPatch, *, enabled: bool = True, client=("127.0.0.1", 50000)):
    from app.main import create_app

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENABLE_SUPPORT_CONSOLE", "true")
    monkeypatch.setenv("ENABLE_TEAM_DEV_LOGIN", "true" if enabled else "false")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", IDENTITY_SECRET)
    monkeypatch.setenv("OTP_DIGEST_SECRET", OTP_SECRET)
    monkeypatch.setenv("SUPPORT_CONSOLE_TIMEZONE", "America/Sao_Paulo")
    get_settings.cache_clear()
    try:
        app = create_app()
        yield TestClient(app, base_url="http://127.0.0.1:8077", client=client), app
    finally:
        get_settings.cache_clear()


def _seed_demo_staff(app) -> None:
    app.state.support_console_runtime.service.staff_store.add_staff(
        StaffMember(
            id=str(uuid4()),
            phone_hash=_hmac_digest(IDENTITY_SECRET, DEMO_STAFF_PHONE),
            phone_last4=DEMO_STAFF_PHONE[-4:],
            display_name="Atendente Demo 1",
        )
    )


def test_probe_returns_204_only_when_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch) as (client, _app):
        assert client.get("/web/support/auth/dev-login").status_code == 204
    with _client(monkeypatch, enabled=False) as (client, _app):
        assert client.get("/web/support/auth/dev-login").status_code == 404


def test_probe_is_404_behind_a_proxy_or_from_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch) as (client, _app):
        assert (
            client.get(
                "/web/support/auth/dev-login", headers={"X-Forwarded-For": "203.0.113.7"}
            ).status_code
            == 404
        )
        assert (
            client.get(
                "/web/support/auth/dev-login", headers={"Host": "concession.example.test"}
            ).status_code
            == 404
        )
    with _client(monkeypatch, client=("10.0.0.5", 50000)) as (client, _app):
        assert client.get("/web/support/auth/dev-login").status_code == 404


def test_login_requires_the_csrf_header(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch) as (client, app):
        _seed_demo_staff(app)
        assert client.post("/web/support/auth/dev-login").status_code == 403


def test_login_without_seeded_operator_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch) as (client, _app):
        response = client.post("/web/support/auth/dev-login", headers=CSRF)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dev_staff_missing"


def test_login_issues_a_normal_staff_session(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch) as (client, app):
        _seed_demo_staff(app)
        response = client.post("/web/support/auth/dev-login", headers=CSRF)
        assert response.status_code == 200
        assert response.json()["display_name"] == "Atendente Demo 1"
        cookie = response.headers["set-cookie"]
        assert "sfa_staff_session=" in cookie
        assert "HttpOnly" in cookie and "Path=/web/support" in cookie
        assert "sfa_staff_hint" not in cookie
        session = client.get("/web/support/auth/session")
    assert session.status_code == 200
    assert session.json()["display_name"] == "Atendente Demo 1"


def test_login_is_404_when_disabled_even_with_seeded_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(monkeypatch, enabled=False) as (client, app):
        _seed_demo_staff(app)
        assert client.post("/web/support/auth/dev-login", headers=CSRF).status_code == 404


# --------------------------------------------------------------------------- #
# Tela
# --------------------------------------------------------------------------- #


def test_team_button_is_hidden_until_the_server_says_204() -> None:
    html = Path("app/static/team/index.html").read_text(encoding="utf-8")
    box = re.search(r'<div id="dev-login-box"([^>]*)>', html)
    assert box and "hidden" in box.group(1)
    script = Path("app/static/team/app.js").read_text(encoding="utf-8")
    assert 'devLogin: "/web/support/auth/dev-login"' in script
    assert 'el("dev-login-box").hidden = false' in script
