"""What the citizen sees about the case opened by a chat turn.

The web chat shows a "chamado registrado" card with a short protocol, the
priority, the deadline and its basis, and lists the documents consulted by
their human title instead of the file path. All of it comes from the same
domain rules the console uses; the LLM never decides any of it.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.support.case_policy import case_sla_policy
from app.support.sla import PRIORITY_LABEL_PT_BR

PRIORITY_TITLE = {key: value.capitalize() for key, value in PRIORITY_LABEL_PT_BR.items()}
GLOBAL_BASIS = "Prazo padrão do atendimento"
SOURCE_KIND = {"faqs": "Pergunta frequente", "articles": "Documento"}
_HEX = re.compile(r"[^0-9a-fA-F]")

# Handoff statuses from app.db.operational (kept as strings to avoid a cycle).
_QUEUED = "handoff_queued"
_PENDING_CONSENT = "handoff_pending_consent"


def short_protocol(request_id: str) -> str:
    """``2a7399df-eb6b-...`` -> ``2A73-99DF``: easy to read out on the phone."""

    digits = _HEX.sub("", request_id or "").upper()[:8]
    if len(digits) < 8:
        return (request_id or "").upper()[:9]
    return f"{digits[:4]}-{digits[4:]}"


def deadline_label(minutes: int) -> str:
    if minutes < 60:
        return f"até {minutes} minutos"
    hours = minutes / 60
    if minutes % (24 * 60) == 0 and minutes >= 2 * 24 * 60:
        days = minutes // (24 * 60)
        return f"até {days} dias"
    if hours == int(hours):
        whole = int(hours)
        return f"até {whole} hora" if whole == 1 else f"até {whole} horas"
    return f"até {hours:.1f} horas".replace(".", ",")


def public_case_summary(
    *,
    domain: Any,
    priority: str,
    handoff_status: str,
    request_id: str,
    settings: Any,
) -> dict[str, str] | None:
    """Card data for a turn that opened a case; ``None`` when no case was queued."""

    if handoff_status not in {_QUEUED, _PENDING_CONSENT}:
        return None
    minutes, basis = case_sla_policy(settings, domain.name, priority)
    return {
        "protocol": short_protocol(request_id),
        "status": "registrado" if handoff_status == _QUEUED else "aguardando_confirmacao",
        "priority": priority,
        "priority_label": PRIORITY_TITLE.get(priority, priority),
        "deadline_label": deadline_label(minutes) if minutes else "",
        "basis": basis or GLOBAL_BASIS,
        "channel_label": str(getattr(domain, "display_name", "") or domain.name),
    }


MAX_PUBLIC_SOURCES = 3


def public_sources(references: list[str], domains_path: Any) -> list[dict[str, str]]:
    """Human titles of the top knowledge files behind an answer, in order, once each."""

    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for reference in references:
        title, kind = _describe(str(reference), str(Path(domains_path).resolve()))
        if title and title not in seen:
            seen.add(title)
            sources.append({"title": title, "kind": kind})
        if len(sources) == MAX_PUBLIC_SOURCES:
            break
    return sources


@lru_cache(maxsize=256)
def _describe(reference: str, domains_root: str) -> tuple[str, str]:
    parts = Path(reference).parts
    kind = next((SOURCE_KIND[part] for part in parts if part in SOURCE_KIND), "Documento")
    relative = Path(*parts[1:]) if parts and parts[0] == "domains" else Path(reference)
    root = Path(domains_root)
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != ".md" or not path.is_file():
        return _title_from_name(path.stem), kind
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("# "):
                    return line[2:].strip(), kind
    except OSError:
        pass
    return _title_from_name(path.stem), kind


def _title_from_name(stem: str) -> str:
    words = stem.replace("_", "-").split("-")
    return " ".join(words).strip().capitalize()


TEAM_QUEUE_PATH = "/team/"


def whatsapp_contact_available(settings) -> bool:
    """The chat offers the WhatsApp return only when its routes exist."""

    return bool(getattr(settings, "enable_web_whatsapp_auth", False))


def public_demo_team_url(settings, *, case_opened: bool) -> str | None:
    """In the public demo, point the visitor to the queue that shows their case."""

    if not case_opened:
        return None
    if not getattr(settings, "enable_public_demo_login", False):
        return None
    if not getattr(settings, "enable_team_ui", False):
        return None
    return TEAM_QUEUE_PATH
