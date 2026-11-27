"""Demo publica: login do operador ficticio atras de proxy, sem envio externo.

``ENABLE_PUBLIC_DEMO_LOGIN`` tira as guardas de loopback do login de
desenvolvimento. A contrapartida e a recusa no boot: sem PostgreSQL dedicado,
sem console ou com qualquer canal de saida ligado, a aplicacao nao sobe.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.support.dev_login import PROXY_HEADERS, dev_login_allowed

BASE_ENV = {
    "APP_ENV": "production",
    "API_SECRET_KEY": "public-demo-test-key",
    "ENABLE_PUBLIC_DEMO_LOGIN": "true",
    "ENABLE_SUPPORT_CONSOLE": "true",
    "PERSISTENCE_BACKEND": "postgres",
    "DATABASE_URL": "postgresql://demo:pw@127.0.0.1:5432/concession_demo",
    "PERSISTENCE_HASH_SECRET": "persistence-test-secret",
    "IDENTITY_HASH_SECRET": "identity-test-secret",
    "OTP_DIGEST_SECRET": "otp-test-secret",
}


@contextmanager
def _env(**overrides: str):
    saved = dict(os.environ)
    for name in list(os.environ):
        if name.startswith(("ENABLE_", "VERIFIED_", "WEB_AUTH_", "META_", "HERMES_", "PERSISTENCE_")):
            os.environ.pop(name)
    os.environ.update({**BASE_ENV, **overrides})
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_isolated_public_demo_boots_in_production() -> None:
    with _env():
        settings = Settings(_env_file=None)
    assert settings.enable_public_demo_login is True
    assert settings.enable_team_dev_login is False


def test_flag_is_off_by_default() -> None:
    with _env(ENABLE_PUBLIC_DEMO_LOGIN="false"):
        assert Settings(_env_file=None).enable_public_demo_login is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"PERSISTENCE_BACKEND": "disabled"},
        {"ENABLE_SUPPORT_CONSOLE": "false"},
    ],
)
def test_refuses_without_dedicated_database_and_console(overrides: dict[str, str]) -> None:
    with _env(**overrides):
        with pytest.raises(ValueError, match="ENABLE_PUBLIC_DEMO_LOGIN requires"):
            Settings(_env_file=None)


@pytest.mark.parametrize(
    ("overrides", "named"),
    [
        ({"ENABLE_META_WHATSAPP_CHAT": "true", "META_WHATSAPP_ACCESS_TOKEN": "t",
          "META_WHATSAPP_PHONE_NUMBER_ID": "1"}, "ENABLE_META_WHATSAPP_CHAT"),
        ({"ENABLE_HERMES_CHAT": "true", "HERMES_BASE_URL": "http://127.0.0.1:3000",
          "HERMES_WEBHOOK_SECRET": "s"}, "ENABLE_HERMES_CHAT"),
        ({"ENABLE_SUPPORT_TEAM_WHATSAPP_NOTIFY": "true"}, "ENABLE_SUPPORT_TEAM_WHATSAPP_NOTIFY"),
        ({"ENABLE_CONVERSATION_ARCHIVE": "true"}, "ENABLE_CONVERSATION_ARCHIVE"),
        ({"VERIFIED_HANDOFF_WEBHOOK_URL": "https://hooks.example.test/h"},
         "VERIFIED_HANDOFF_WEBHOOK_URL"),
        ({"WEB_AUTH_OTP_DELIVERY_TRANSPORT": "hermes", "HERMES_BASE_URL": "http://127.0.0.1:3000",
          "HERMES_WEBHOOK_SECRET": "s"}, "WEB_AUTH_OTP_DELIVERY_TRANSPORT"),
    ],
)
def test_refuses_any_outbound_channel(overrides: dict[str, str], named: str) -> None:
    with _env(**overrides):
        with pytest.raises(ValueError, match=named):
            Settings(_env_file=None)


PUBLIC = SimpleNamespace(enable_public_demo_login=True, enable_team_dev_login=False,
                         app_env="production")


@pytest.mark.parametrize("header", PROXY_HEADERS)
def test_login_is_allowed_behind_the_reverse_proxy(header: str) -> None:
    assert dev_login_allowed(
        PUBLIC,
        client_host="127.0.0.1",
        host_header="concession.example.test",
        headers={header: "203.0.113.7"},
    )


def test_login_is_allowed_from_any_peer_and_host() -> None:
    assert dev_login_allowed(
        PUBLIC, client_host="203.0.113.7", host_header="concession.example.test", headers={}
    )


def test_without_the_flag_the_dev_guards_still_apply() -> None:
    settings = SimpleNamespace(enable_public_demo_login=False, enable_team_dev_login=True,
                               app_env="development")
    assert not dev_login_allowed(
        settings,
        client_host="127.0.0.1",
        host_header="concession.example.test",
        headers={"x-forwarded-for": "203.0.113.7"},
    )
