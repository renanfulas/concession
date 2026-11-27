"""Tela somente leitura do console (/team).

A tela e HTML+JS estatico: estes testes provam que ela so aparece quando a
flag permite, sai com os cabecalhos de seguranca, nao depende de CDN nem de
script inline e so referencia caminhos que a API do console realmente expoe
(nenhum endpoint de escrita de caso).
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.domain_engine.loader import DomainLoader
from app.core.config import get_settings
from app.support.staff_auth import StaffMember
from app.web_auth.service import _hmac_digest


TEAM_DIR = Path(__file__).resolve().parents[1] / "app" / "static" / "team"
IDENTITY_SECRET = "identity-test-secret"
OTP_SECRET = "otp-test-secret"
STAFF_PHONE = "+5511999990001"  # ficticio
CASE_WRITE_SEGMENTS = ("/transition", "/message")


@contextmanager
def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    env: dict[str, str] | None = None,
    console: bool = False,
):
    from app.main import create_app

    monkeypatch.delenv("ENABLE_TEAM_UI", raising=False)
    if console:
        monkeypatch.setenv("ENABLE_SUPPORT_CONSOLE", "true")
        monkeypatch.setenv("IDENTITY_HASH_SECRET", IDENTITY_SECRET)
        monkeypatch.setenv("OTP_DIGEST_SECRET", OTP_SECRET)
    else:
        monkeypatch.setenv("ENABLE_SUPPORT_CONSOLE", "false")
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        app = create_app()
        yield TestClient(app), app
    finally:
        get_settings.cache_clear()


def _read(name: str) -> str:
    return (TEAM_DIR / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Flag
# --------------------------------------------------------------------------- #


def test_team_page_is_served_by_default_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(monkeypatch) as (client, _):
        response = client.get("/team")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Ambiente de demonstração" in response.text
    assert "Fila do time" in response.text


def test_team_assets_are_served_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch) as (client, _):
        script = client.get("/team-assets/app.js")
        styles = client.get("/team-assets/styles.css")

    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert styles.status_code == 200


@pytest.mark.parametrize(
    "env",
    [
        {"ENABLE_TEAM_UI": "false"},
        {"APP_ENV": "production", "API_SECRET_KEY": "production-test-secret"},
        {"APP_ENV": "staging", "API_SECRET_KEY": "staging-test-secret"},
    ],
)
def test_team_page_is_404_when_disabled(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    with _client(monkeypatch, env=env) as (client, _):
        assert client.get("/team").status_code == 404
        assert client.get("/team-assets/app.js").status_code == 404


def test_team_flag_enables_page_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {
        "APP_ENV": "production",
        "API_SECRET_KEY": "production-test-secret",
        "ENABLE_TEAM_UI": "true",
    }
    with _client(monkeypatch, env=env) as (client, _):
        response = client.get("/team")

    assert response.status_code == 200
    assert "Ambiente de demonstração" in response.text


# --------------------------------------------------------------------------- #
# Cabecalhos de seguranca e ausencia de dependencia externa
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", ["/team", "/team/", "/team-assets/app.js"])
def test_team_responses_carry_security_headers(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    with _client(monkeypatch) as (client, _):
        response = client.get(path)

    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "script-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_security_headers_are_scoped_to_team_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(monkeypatch) as (client, _):
        response = client.get("/health")

    assert "content-security-policy" not in response.headers


def test_team_html_has_no_inline_script_or_external_assets() -> None:
    html = _read("index.html")

    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, flags=re.S)
    assert scripts, "a pagina precisa carregar o app.js"
    for attributes, body in scripts:
        assert 'src="/team-assets/' in attributes
        assert body.strip() == ""
    assert not re.search(r"\son[a-z]+\s*=", html, flags=re.I)
    assert "<style" not in html
    assert 'style="' not in html
    for text in (html, _read("app.js"), _read("styles.css")):
        assert "http://" not in text
        assert "https://" not in text
        assert "@import" not in text


def test_team_script_keeps_nothing_sensitive_in_the_browser() -> None:
    script = _read("app.js")

    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "document.cookie" not in script
    assert not re.search(r"console\.(log|info|warn|error|debug)", script)
    assert "innerHTML" not in script


# --------------------------------------------------------------------------- #
# Contrato com a API do console
# --------------------------------------------------------------------------- #


def _script_api_paths() -> set[str]:
    return set(re.findall(r'"(/web/[^"?]+)', _read("app.js")))


def _console_routes(app) -> dict[str, dict]:
    """Caminhos do router do console como o proprio FastAPI os publica."""

    return {
        path: operations
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/web/support")
    }


def test_team_script_only_references_existing_console_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _script_api_paths()
    assert paths, "o app.js deve declarar os caminhos da API"

    with _client(monkeypatch, console=True) as (_, app):
        routes = _console_routes(app)

    for path in paths:
        assert path.startswith("/web/support/"), path
        assert path in routes, f"{path} nao existe no router do console"
    # A tela so le: nenhum GET referenciado exige mais que a sessao staff.
    auth_posts = {
        "/web/support/auth/start",
        "/web/support/auth/confirm",
        "/web/support/auth/logout",
    }
    for path in paths - auth_posts:
        assert "get" in routes[path], path


def test_team_script_uses_only_existing_list_query_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _read("app.js")
    initial = script.split("new URLSearchParams({", 1)[1].split("});", 1)[0]
    used = set(re.findall(r"\b([a-z_]+):", initial))
    used |= set(re.findall(r'params\.set\("([a-z_]+)"', script))
    assert {"view", "sort", "limit", "domain", "color"} <= used

    with _client(monkeypatch, console=True) as (_, app):
        operation = _console_routes(app)["/web/support/cases"]["get"]
    accepted = {
        param["name"] for param in operation["parameters"] if param["in"] == "query"
    }

    assert used <= accepted
    assert 'sort: "attention"' in script


def test_team_script_references_no_case_write_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _read("app.js")
    for segment in CASE_WRITE_SEGMENTS:
        assert segment not in script
    assert "/internal/" not in script
    assert "X-API-Key" not in script

    with _client(monkeypatch, console=True) as (_, app):
        routes = _console_routes(app)
    # O unico POST que a tela usa e o da autenticacao staff ja existente.
    for path in _script_api_paths():
        if "post" in routes[path]:
            assert path.startswith("/web/support/auth/"), path


# --------------------------------------------------------------------------- #
# GET /web/support/domains (rotulos e filtro da tela)
# --------------------------------------------------------------------------- #


def _login(client: TestClient, app) -> None:
    app.state.support_console_runtime.service.staff_store.add_staff(
        StaffMember(
            id=str(uuid4()),
            phone_hash=_hmac_digest(IDENTITY_SECRET, STAFF_PHONE),
            phone_last4=STAFF_PHONE[-4:],
            display_name="Operador Demo",
        )
    )
    start = client.post("/web/support/auth/start", json={"phone": STAFF_PHONE})
    code = app.state.support_console_runtime.delivery.requests[-1].code
    confirm = client.post(
        "/web/support/auth/confirm",
        json={"challenge_id": start.json()["challenge_id"], "code": code},
    )
    assert confirm.status_code == 200


def test_console_domains_requires_staff_session(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, console=True) as (client, _):
        response = client.get("/web/support/domains")

    assert response.status_code == 401


def test_console_domains_lists_display_names(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, console=True) as (client, app):
        _login(client, app)
        response = client.get("/web/support/domains")

    assert response.status_code == 200
    domains = {item["name"]: item["display_name"] for item in response.json()["domains"]}
    loader = DomainLoader(Path("domains"))
    for name in ("concessoes-manutencao", "lgpd-titular"):
        config = loader.load(name)
        assert config is not None
        assert domains[name] == config.display_name


def test_console_domains_is_404_when_console_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(monkeypatch) as (client, _):
        assert client.get("/web/support/domains").status_code == 404


def test_report_form_targets_the_monthly_csv_route(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _read("index.html")
    form = re.search(r'<form\s+id="report-form"(.*?)</form>', html, flags=re.S)
    assert form, "a tela deve ter o formulario do relatorio mensal"
    action = re.search(r'action="([^"]+)"', form.group(1)).group(1)
    assert 'method="get"' in form.group(1)
    assert 'name="month"' in form.group(1)

    with _client(monkeypatch, console=True) as (_, app):
        operation = _console_routes(app)[action]["get"]
    accepted = {param["name"] for param in operation["parameters"] if param["in"] == "query"}
    assert "month" in accepted
