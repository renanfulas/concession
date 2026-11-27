import pytest
from fastapi.testclient import TestClient

from app.api.schemas.feedback import FeedbackResponse
from app.core.config import get_settings
from app.core.request_context import REQUEST_ID_HEADER
from app.main import CHAT_STATIC_DIR, create_app
from app.orchestration.chat_flow import ChatFlowService
from app.orchestration.domain_router import CLARIFICATION_TEXT, GREETING_TEXT


@pytest.fixture
def web_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENABLE_PUBLIC_CHAT_UI", "true")
    # These tests cover the unrouted public contract (one domain answers every
    # message); routing by message has its own tests below.
    monkeypatch.setenv("ENABLE_WEB_DOMAIN_ROUTER", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    try:
        yield client
    finally:
        get_settings.cache_clear()


def test_web_chat_accepts_valid_payload_without_api_key_and_returns_public_contract(
    monkeypatch: pytest.MonkeyPatch,
    web_client: TestClient,
) -> None:
    captured: dict[str, object] = {}

    def fake_answer(
        self,
        domain,
        question: str,
        session_id: str | None = None,
        request_id: str | None = None,
        provider_api_key: str | None = None,
        channel: str = "api",
        customer_id: str | None = None,
    ) -> dict[str, object]:
        captured["domain"] = domain.name
        captured["question"] = question
        captured["session_id"] = session_id
        captured["request_id"] = request_id
        captured["provider_api_key"] = provider_api_key
        captured["channel"] = channel
        return {
            "request_id": request_id or "",
            "domain": domain.name,
            "answer": "Resposta publica segura.",
            "confidence": 0.91,
            "escalated": False,
            "handoff_reasons": [],
            "references": ["qrcode-whatsapp.md"],
            "error_code": None,
        }

    monkeypatch.setattr(
        "app.orchestration.chat_flow.ChatFlowService.answer",
        fake_answer,
    )

    response = web_client.post(
        "/web/chat",
        headers={REQUEST_ID_HEADER: "web-chat-ok-1"},
        json={"message": "Como conectar o WhatsApp na Evolution API?"},
    )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "web-chat-ok-1"
    assert "sfaq_web_session=" in response.headers["set-cookie"]

    payload = response.json()
    assert payload == {
        "request_id": "web-chat-ok-1",
        "answer": "Resposta publica segura.",
        "escalated": False,
        "handoff_reasons": [],
        "references": ["qrcode-whatsapp.md"],
        "support_code": "web-chat-ok-1",
        "error_code": None,
        "support_deep_link": None,
        "notices": [],
        "case": None,
        # The fake references a file outside domains/: title from the name.
        "sources": [{"title": "Qrcode whatsapp", "kind": "Documento"}],
    }
    assert "domain" not in payload
    assert "confidence" not in payload
    assert captured["question"] == "Como conectar o WhatsApp na Evolution API?"
    assert isinstance(captured["session_id"], str)
    assert str(captured["session_id"]).startswith("web:")
    assert captured["provider_api_key"] is None
    assert captured["channel"] == "web"


def test_web_chat_rejects_domain_extra_field(web_client: TestClient) -> None:
    response = web_client.post(
        "/web/chat",
        headers={REQUEST_ID_HEADER: "web-chat-domain-extra"},
        json={
            "message": "Como instalar Evolution API?",
            "domain": "suporte-vps-whatsapp",
        },
    )

    assert response.status_code == 422
    assert response.headers[REQUEST_ID_HEADER] == "web-chat-domain-extra"
    assert response.json()["request_id"] == "web-chat-domain-extra"


def test_web_chat_rejects_session_id_extra_field(web_client: TestClient) -> None:
    response = web_client.post(
        "/web/chat",
        headers={REQUEST_ID_HEADER: "web-chat-session-extra"},
        json={
            "message": "Como instalar Evolution API?",
            "session_id": "web:forged",
        },
    )

    assert response.status_code == 422
    assert response.headers[REQUEST_ID_HEADER] == "web-chat-session-extra"
    assert response.json()["request_id"] == "web-chat-session-extra"


def test_web_chat_reuses_valid_anonymous_session_cookie(
    monkeypatch: pytest.MonkeyPatch,
    web_client: TestClient,
) -> None:
    captured: list[str | None] = []

    def fake_answer(
        self,
        domain,
        question: str,
        session_id: str | None = None,
        request_id: str | None = None,
        provider_api_key: str | None = None,
        channel: str = "api",
        customer_id: str | None = None,
    ) -> dict[str, object]:
        _ = (domain, question, provider_api_key, channel)
        captured.append(session_id)
        return {
            "request_id": request_id or "",
            "domain": "suporte-vps-whatsapp",
            "answer": "ok",
            "confidence": 0.5,
            "escalated": False,
            "handoff_reasons": [],
            "references": [],
            "error_code": None,
        }

    monkeypatch.setattr(
        "app.orchestration.chat_flow.ChatFlowService.answer",
        fake_answer,
    )

    existing_session = "web:123e4567-e89b-12d3-a456-426614174000"
    web_client.cookies.set("sfaq_web_session", existing_session)

    response = web_client.post(
        "/web/chat",
        headers={REQUEST_ID_HEADER: "web-chat-cookie-reuse"},
        json={"message": "Teste de sessao."},
    )

    assert response.status_code == 200
    assert captured == [existing_session]
    assert "set-cookie" not in response.headers


def test_web_chat_rate_limit_returns_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_answer(
        self,
        domain,
        question: str,
        session_id: str | None = None,
        request_id: str | None = None,
        provider_api_key: str | None = None,
        channel: str = "api",
        customer_id: str | None = None,
    ) -> dict[str, object]:
        _ = (domain, question, session_id, provider_api_key, channel)
        return {
            "request_id": request_id or "",
            "domain": "suporte-vps-whatsapp",
            "answer": "ok",
            "confidence": 0.5,
            "escalated": False,
            "handoff_reasons": [],
            "references": [],
            "error_code": None,
        }

    monkeypatch.setenv("WEB_CHAT_RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setattr(
        "app.orchestration.chat_flow.ChatFlowService.answer",
        fake_answer,
    )

    get_settings.cache_clear()
    client = TestClient(create_app())
    payload = {"message": "Como instalar a Evolution API no VPS?"}

    first = client.post("/web/chat", json=payload)
    second = client.post("/web/chat", json=payload)
    third = client.post("/web/chat", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["Retry-After"]
    assert third.json()["detail"] == "Too many requests"
    assert third.json()["request_id"]
    get_settings.cache_clear()


def test_web_feedback_accepts_without_api_key_and_forces_source_web(
    monkeypatch: pytest.MonkeyPatch,
    web_client: TestClient,
) -> None:
    captured: dict[str, object] = {}

    def fake_record(self, payload) -> FeedbackResponse:
        captured["payload"] = payload.model_dump()
        return FeedbackResponse(
            feedback_id="feedback-web-1",
            accepted=True,
            status="accepted",
            storage="pending_persistence",
        )

    monkeypatch.setattr("app.feedback.service.FeedbackService.record", fake_record)

    session_id = "web:123e4567-e89b-12d3-a456-426614174001"
    web_client.cookies.set("sfaq_web_session", session_id)
    response = web_client.post(
        "/web/feedback",
        headers={REQUEST_ID_HEADER: "web-feedback-ok-1"},
        json={
            "request_id": "chat-request-1",
            "helpful": True,
            "reason": "resolved",
            "comment": "A resposta ajudou.",
        },
    )

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "web-feedback-ok-1"
    assert response.json() == {
        "feedback_id": "feedback-web-1",
        "accepted": True,
        "status": "accepted",
        "storage": "pending_persistence",
    }
    assert captured["payload"] == {
        "request_id": "chat-request-1",
        "session_id": session_id,
        "message_id": None,
        "helpful": True,
        "reason": "resolved",
        "comment": "A resposta ajudou.",
        "source": "web",
        "escalated": None,
        "handoff_reasons": [],
        "references": [],
        "error_code": None,
    }


def test_web_feedback_rejects_extra_fields(web_client: TestClient) -> None:
    response = web_client.post(
        "/web/feedback",
        headers={REQUEST_ID_HEADER: "web-feedback-extra"},
        json={
            "request_id": "chat-request-1",
            "helpful": False,
            "comment": "Nao ajudou.",
            "source": "browser-forged",
        },
    )

    assert response.status_code == 422
    assert response.headers[REQUEST_ID_HEADER] == "web-feedback-extra"
    assert response.json()["request_id"] == "web-feedback-extra"


def test_chat_route_remains_protected_without_api_key(web_client: TestClient) -> None:
    response = web_client.post(
        "/chat",
        headers={REQUEST_ID_HEADER: "web-chat-does-not-open-chat"},
        json={
            "domain": "suporte-vps-whatsapp",
            "message": "Como instalar Evolution API?",
        },
    )

    assert response.status_code == 403
    assert response.headers[REQUEST_ID_HEADER] == "web-chat-does-not-open-chat"
    assert response.json()["detail"] == "Invalid API key"


@pytest.fixture
def routed_web_client(monkeypatch: pytest.MonkeyPatch):
    """Web chat with routing on, as the demo runs out of the box."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENABLE_PUBLIC_CHAT_UI", "true")
    monkeypatch.setenv("ENABLE_WEB_DOMAIN_ROUTER", "true")
    monkeypatch.setenv("WHATSAPP_ROUTER_DOMAINS", "concessoes-manutencao,lgpd-titular")
    monkeypatch.setenv("DEFAULT_DOMAIN", "concessoes-manutencao")
    get_settings.cache_clear()
    answered: list[str] = []
    real_answer = ChatFlowService.answer

    def recording_answer(self, domain, *args, **kwargs):
        answered.append(domain.name)
        return real_answer(self, domain, *args, **kwargs)

    monkeypatch.setattr(
        "app.orchestration.chat_flow.ChatFlowService.answer",
        recording_answer,
    )
    client = TestClient(create_app())
    client.answered_domains = answered  # type: ignore[attr-defined]
    try:
        yield client
    finally:
        get_settings.cache_clear()


def test_web_chat_routes_privacy_request_to_lgpd_domain(
    routed_web_client: TestClient,
) -> None:
    response = routed_web_client.post("/web/chat", json={"message": "Quero excluir meus dados"})

    assert response.status_code == 200
    assert routed_web_client.answered_domains == ["lgpd-titular"]
    payload = response.json()
    assert "pedido_titular" in payload["handoff_reasons"]
    assert payload["references"]
    assert all("lgpd-titular" in ref for ref in payload["references"])
    assert "domain" not in payload


def test_web_chat_routes_exposed_wire_to_maintenance_with_safety_risk(
    routed_web_client: TestClient,
) -> None:
    response = routed_web_client.post("/web/chat", json={"message": "Tem fio exposto no abrigo"})

    assert response.status_code == 200
    assert routed_web_client.answered_domains == ["concessoes-manutencao"]
    payload = response.json()
    assert payload["escalated"] is True
    assert "risco_seguranca" in payload["handoff_reasons"]
    assert all("concessoes-manutencao" in ref for ref in payload["references"])


def test_web_chat_follow_up_in_same_session_stays_in_routed_domain(
    routed_web_client: TestClient,
) -> None:
    first = routed_web_client.post("/web/chat", json={"message": "Quero excluir meus dados"})
    assert first.status_code == 200
    # Same cookie (TestClient keeps it); the follow-up has no routing keyword.
    follow_up = routed_web_client.post(
        "/web/chat",
        json={"message": "E quanto tempo voces levam para responder?"},
    )

    assert follow_up.status_code == 200
    assert routed_web_client.answered_domains == ["lgpd-titular", "lgpd-titular"]


def test_web_chat_session_without_choice_does_not_inherit_other_session_domain(
    routed_web_client: TestClient,
) -> None:
    routed_web_client.post("/web/chat", json={"message": "Quero excluir meus dados"})
    routed_web_client.cookies.clear()

    response = routed_web_client.post(
        "/web/chat",
        json={"message": "E quanto tempo voces levam para responder?"},
    )

    assert response.status_code == 200
    assert routed_web_client.answered_domains == ["lgpd-titular"]
    assert response.json()["answer"] == GREETING_TEXT


def test_web_chat_greeting_returns_router_menu_then_clarification(
    routed_web_client: TestClient,
) -> None:
    first = routed_web_client.post(
        "/web/chat",
        headers={REQUEST_ID_HEADER: "web-chat-greeting-1"},
        json={"message": "Oi"},
    )
    second = routed_web_client.post("/web/chat", json={"message": "bom dia"})

    assert first.status_code == 200
    assert routed_web_client.answered_domains == []
    assert first.json() == {
        "request_id": "web-chat-greeting-1",
        "answer": GREETING_TEXT,
        "escalated": False,
        "handoff_reasons": [],
        "references": [],
        "support_code": "web-chat-greeting-1",
        "error_code": None,
        "support_deep_link": None,
        "notices": [],
        "case": None,
        "sources": [],
    }
    assert second.json()["answer"] == CLARIFICATION_TEXT


def test_web_chat_bare_menu_number_returns_domain_welcome_and_binds_session(
    routed_web_client: TestClient,
) -> None:
    chosen = routed_web_client.post("/web/chat", json={"message": "2"})
    follow_up = routed_web_client.post(
        "/web/chat",
        json={"message": "E quanto tempo voces levam para responder?"},
    )

    assert chosen.status_code == 200
    assert chosen.json()["answer"].startswith("Este é o canal de privacidade")
    assert routed_web_client.answered_domains == ["lgpd-titular"]
    assert follow_up.status_code == 200


def test_web_chat_address_number_is_not_a_menu_choice(
    routed_web_client: TestClient,
) -> None:
    response = routed_web_client.post(
        "/web/chat",
        json={"message": "O relogio da Rua 2 esta apagado"},
    )

    assert response.status_code == 200
    assert routed_web_client.answered_domains == ["concessoes-manutencao"]


def test_public_chat_assets_do_not_contain_secret_strings() -> None:
    forbidden_strings = [
        "X-API-Key",
        "OPENAI_API_KEY",
        "API_SECRET_KEY",
        "X-LLM-API-Key",
    ]

    asset_files = sorted(path for path in CHAT_STATIC_DIR.glob("*") if path.is_file())

    assert asset_files

    for asset_file in asset_files:
        content = asset_file.read_text(encoding="utf-8")
        for forbidden in forbidden_strings:
            assert forbidden not in content, f"{forbidden} found in {asset_file.name}"


def test_web_chat_returns_the_case_card_and_notices_when_a_case_is_queued(
    monkeypatch: pytest.MonkeyPatch,
    web_client: TestClient,
) -> None:
    from app.db.operational import ChatPersistenceResult

    notice = "Segurança primeiro: ligue 193 (Corpo de Bombeiros)."

    def fake_answer(self, domain, question, **kwargs) -> dict[str, object]:
        return {
            "request_id": kwargs.get("request_id") or "",
            "domain": domain.name,
            "answer": f"{notice}\n\nVou encaminhar para a equipe.",
            "confidence": 0.4,
            "escalated": True,
            "handoff_reasons": ["risco_seguranca"],
            "references": [
                "domains/concessoes-manutencao/knowledge/faqs/risco-seguranca.md"
            ],
            "error_code": None,
            "notices": [notice],
        }

    monkeypatch.setattr("app.orchestration.chat_flow.ChatFlowService.answer", fake_answer)
    monkeypatch.setattr(
        "app.db.operational.OperationalRepository.record_chat",
        lambda self, audit: ChatPersistenceResult(
            handoff_status="handoff_queued", persistence_status="persisted", turn_id="t-1"
        ),
    )

    response = web_client.post(
        "/web/chat",
        headers={REQUEST_ID_HEADER: "7da038c9-0000-0000-0000-000000000000"},
        json={"message": "Tem um fio exposto no abrigo ABR-1104"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["notices"] == [notice]
    assert payload["answer"].startswith(notice)
    assert payload["case"]["protocol"] == "7DA0-38C9"
    assert payload["case"]["priority_label"] == "Urgente"
    assert payload["case"]["deadline_label"] == "até 4 horas"
    assert payload["case"]["status"] == "registrado"
    assert payload["sources"] == [
        {
            "title": "Risco a pessoas: fio exposto, vidro quebrado, estrutura solta",
            "kind": "Pergunta frequente",
        }
    ]
