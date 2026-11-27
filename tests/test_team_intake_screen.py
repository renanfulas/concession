"""Static intake screen (/team/intake): served behind the same flags and
security headers as /team, no inline code, nothing kept in the browser, and
only API paths the intake router really publishes."""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings

STATIC = Path("app/static/team")


@contextmanager
def _client(monkeypatch: pytest.MonkeyPatch, *, intake: bool = True):
    from app.main import create_app

    monkeypatch.setenv("ENABLE_SUPPORT_CONSOLE", "true")
    monkeypatch.setenv("ENABLE_AI_INTAKE", "true" if intake else "false")
    monkeypatch.setenv("IDENTITY_HASH_SECRET", "identity-test-secret")
    monkeypatch.setenv("OTP_DIGEST_SECRET", "otp-test-secret")
    get_settings.cache_clear()
    try:
        app = create_app()
        yield TestClient(app), app
    finally:
        get_settings.cache_clear()


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_intake_page_is_served_with_the_team_security_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(monkeypatch) as (client, _):
        page = client.get("/team/intake")
        script = client.get("/team-assets/intake.js")

    assert page.status_code == 200
    assert "Intake de soluções de IA" in page.text
    assert script.status_code == 200
    for response in (page, script):
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"


def test_intake_page_is_404_when_the_flag_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, intake=False) as (client, _):
        assert client.get("/team/intake").status_code == 404


def test_intake_page_has_no_inline_code_or_external_assets() -> None:
    html = _read("intake.html")

    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, flags=re.S)
    assert scripts
    for attributes, body in scripts:
        assert 'src="/team-assets/' in attributes
        assert body.strip() == ""
    assert not re.search(r"\son[a-z]+\s*=", html, flags=re.I)
    assert "<style" not in html
    assert 'style="' not in html
    for text in (html, _read("intake.js"), _read("intake.css")):
        assert "http://" not in text
        assert "https://" not in text
        assert "@import" not in text


def test_intake_script_keeps_nothing_sensitive_in_the_browser() -> None:
    script = _read("intake.js")

    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "document.cookie" not in script
    assert "innerHTML" not in script
    assert not re.search(r"console\.(log|info|warn|error|debug)", script)


def test_every_api_path_in_the_script_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    script = _read("intake.js") + _read("intake.html")
    paths = set(re.findall(r'"(/web/[^"?$]+)', script))
    assert "/web/support/intake/solutions" in paths

    with _client(monkeypatch) as (_, app):
        published = set(app.openapi()["paths"])

    for path in paths:
        assert path in published, path
    assert "/web/support/intake/solutions/{solution_id}/transitions" in published
    assert "/web/support/intake/solutions/{solution_id}/ficha.md" in published
