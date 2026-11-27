"""Login de desenvolvimento da tela /team (Fase 1, item 4).

Emite a sessao staff do operador ficticio do seed (``Atendente Demo 1``) sem
OTP, so para a demo local. Tres camadas, todas obrigatorias:

1. boot: ``ENABLE_TEAM_DEV_LOGIN=true`` so sobe com ``APP_ENV=development``
   explicito (``app/core/config.py``);
2. rede: peer TCP de loopback **e** ``Host`` de loopback, para que um tunel ou
   bind em ``0.0.0.0`` nao exponha o atalho;
3. proxy: qualquer header de proxy recusa o pedido. O uvicorn confia em
   ``X-Forwarded-For`` vindo de 127.0.0.1 por padrao, entao um proxy reverso
   local faria o peer parecer loopback; a presenca do header e o sinal.

Qualquer falha responde 404, igual a uma rota que nao existe.

Excecao: ``ENABLE_PUBLIC_DEMO_LOGIN=true`` libera o mesmo atalho para qualquer
visitante de uma demo publica. A flag so sobe com banco dedicado e todo envio
externo desligado (``Settings._require_public_demo_isolation``), entao a sessao
so ve casos ficticios e nada do que o visitante fizer sai do servidor.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Mesma faixa ficticia do seed (scripts/seed_demo_cases.py, SEED_STAFF_PHONE).
DEMO_STAFF_PHONE = "+5511900000001"

LOOPBACK_PEERS = frozenset({"127.0.0.1", "::1"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
PROXY_HEADERS = (
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-port",
    "x-forwarded-prefix",
    "x-real-ip",
    "x-original-forwarded-for",
    "via",
)


def dev_login_allowed(
    settings: Any,
    *,
    client_host: str | None,
    host_header: str | None,
    headers: Mapping[str, str],
) -> bool:
    if getattr(settings, "enable_public_demo_login", False):
        return True
    if not getattr(settings, "enable_team_dev_login", False):
        return False
    if str(getattr(settings, "app_env", "")).lower() != "development":
        return False
    if client_host not in LOOPBACK_PEERS:
        return False
    if host_name(host_header) not in LOOPBACK_HOSTS:
        return False
    lowered = {key.lower() for key in headers.keys()}
    return not any(name in lowered for name in PROXY_HEADERS)


def host_name(host_header: str | None) -> str | None:
    """Hostname of a ``Host`` header, without port; ``[::1]:8077`` -> ``::1``."""

    if not host_header:
        return None
    value = host_header.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else None
    if value.count(":") == 1:
        value = value.split(":", 1)[0]
    elif value.count(":") > 1:
        # Bare IPv6 without brackets is not a valid Host header.
        return None
    return value or None
