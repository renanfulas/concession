"""What the citizen sees about the case: the card and the sources.

The web chat shows the case the rules opened (short protocol, priority,
deadline and its basis) and the documents consulted by title. Nothing here
comes from the LLM, and no internal code (request_id, error_code, file path)
reaches the citizen's screen.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain_engine.loader import DomainLoader
from app.support.public_case import (
    MAX_PUBLIC_SOURCES,
    deadline_label,
    public_case_summary,
    public_demo_team_url,
    public_sources,
    short_protocol,
    whatsapp_contact_available,
)

SETTINGS = SimpleNamespace(
    domains_path=Path("domains"),
    support_sla_minutes_urgent=60,
    support_sla_minutes_high=120,
    support_sla_minutes_normal=480,
    support_sla_minutes_low=1440,
)
STATIC = Path("app/static/chat")


def _domain(name: str):
    loaded = DomainLoader(Path("domains")).load(name)
    assert loaded is not None
    return loaded


def test_short_protocol_is_easy_to_read_out() -> None:
    assert short_protocol("2a7399df-eb6b-4eca-bea0-1aaf54c58303") == "2A73-99DF"
    assert short_protocol("web-chat-ok-1") == "WEB-CHAT-"


@pytest.mark.parametrize(
    ("minutes", "label"),
    [
        (30, "até 30 minutos"),
        (60, "até 1 hora"),
        (240, "até 4 horas"),
        (1440, "até 24 horas"),
        (2880, "até 2 dias"),
        (7200, "até 5 dias"),
        (21600, "até 15 dias"),
        (90, "até 1,5 horas"),
    ],
)
def test_deadline_label(minutes: int, label: str) -> None:
    assert deadline_label(minutes) == label


def test_case_card_uses_the_domain_rules() -> None:
    card = public_case_summary(
        domain=_domain("concessoes-manutencao"),
        priority="urgent",
        handoff_status="handoff_queued",
        request_id="7da0-38c9-0000",
        settings=SETTINGS,
    )
    assert card == {
        "protocol": "7DA0-38C9",
        "status": "registrado",
        "priority": "urgent",
        "priority_label": "Urgente",
        "deadline_label": "até 4 horas",
        "basis": "Anexo de Níveis de Serviço (demo), item 3: prazos fictícios para demonstração",
        "channel_label": "Manutenção de Mobiliário Urbano",
    }


def test_privacy_case_card_has_the_legal_deadline() -> None:
    card = public_case_summary(
        domain=_domain("lgpd-titular"),
        priority="normal",
        handoff_status="handoff_pending_consent",
        request_id="abcd1234",
        settings=SETTINGS,
    )
    assert card is not None
    assert card["status"] == "aguardando_confirmacao"
    assert card["deadline_label"] == "até 15 dias"
    assert card["basis"].startswith("LGPD art. 19, II")


@pytest.mark.parametrize("status", ["handoff_not_required", "handoff_unavailable", ""])
def test_no_card_when_no_case_reached_the_queue(status: str) -> None:
    assert (
        public_case_summary(
            domain=_domain("concessoes-manutencao"),
            priority="urgent",
            handoff_status=status,
            request_id="x",
            settings=SETTINGS,
        )
        is None
    )


def test_sources_show_titles_not_paths_and_are_capped() -> None:
    references = [
        "domains/concessoes-manutencao/knowledge/faqs/risco-seguranca.md",
        "domains/concessoes-manutencao/knowledge/articles/anexo-niveis-de-servico.md",
        "domains/concessoes-manutencao/knowledge/articles/anexo-niveis-de-servico.md",
        "domains/concessoes-manutencao/knowledge/faqs/tela-apagada.md",
        "domains/concessoes-manutencao/knowledge/faqs/pichacao-limpeza.md",
    ]
    sources = public_sources(references, Path("domains"))
    assert len(sources) == MAX_PUBLIC_SOURCES
    assert sources[0] == {
        "title": "Risco a pessoas: fio exposto, vidro quebrado, estrutura solta",
        "kind": "Pergunta frequente",
    }
    assert sources[1]["title"] == "Anexo de Níveis de Serviço (demonstração)"
    assert all(".md" not in source["title"] for source in sources)


def test_sources_never_read_outside_the_domains_folder() -> None:
    [source] = public_sources(["domains/../README.md"], Path("domains"))
    assert source["title"] == "Readme"


def test_chat_screen_never_prints_internal_codes() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    # The old renderer printed the raw error_code as "Status" and the full
    # request_id as "Codigo"; the citizen now sees only the short protocol.
    assert 'makeMetaItem("Status"' not in script
    assert 'makeMetaItem("Código"' not in script
    assert "Base usada:" not in script
    assert "shortProtocol" in script
    assert "renderCaseCard" in script and "renderNotice" in script


def test_chat_screen_keeps_the_demo_banner_and_no_external_assets() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Ambiente de demonstração" in html
    for text in (html, (STATIC / "styles.css").read_text(encoding="utf-8")):
        assert "https://" not in text and "http://" not in text
        assert "@import" not in text


# --------------------------------------------------------------------------- #
# Canais oferecidos na tela: WhatsApp so quando ligado; fila do time na demo
# --------------------------------------------------------------------------- #


def test_whatsapp_return_is_offered_only_when_the_channel_is_on() -> None:
    assert whatsapp_contact_available(SimpleNamespace(enable_web_whatsapp_auth=True)) is True
    assert whatsapp_contact_available(SimpleNamespace(enable_web_whatsapp_auth=False)) is False
    assert whatsapp_contact_available(SimpleNamespace()) is False


DEMO = SimpleNamespace(enable_public_demo_login=True, enable_team_ui=True)


def test_public_demo_links_the_case_to_the_team_queue() -> None:
    assert public_demo_team_url(DEMO, case_opened=True) == "/team/"


@pytest.mark.parametrize(
    ("settings", "case_opened"),
    [
        (DEMO, False),
        (SimpleNamespace(enable_public_demo_login=False, enable_team_ui=True), True),
        (SimpleNamespace(enable_public_demo_login=True, enable_team_ui=False), True),
        (SimpleNamespace(), True),
    ],
)
def test_no_team_link_outside_the_demo_or_without_a_case(settings, case_opened: bool) -> None:
    assert public_demo_team_url(settings, case_opened=case_opened) is None


def test_chat_screen_gates_the_whatsapp_offer_and_keeps_links_local() -> None:
    script = Path("app/static/chat/app.js").read_text(encoding="utf-8")
    assert "response.case && response.whatsapp_contact)" in script
    assert "renderConsentPrompt(response.request_id, response.case)" in script
    assert 'whatsapp_contact: payload?.whatsapp_contact === true' in script
    assert "team_queue_url: safeLocalPath(payload?.team_queue_url)" in script
    assert '!path.startsWith("//")' in script

