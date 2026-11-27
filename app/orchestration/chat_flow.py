import logging
import time
from time import perf_counter

from app.core.errors import ProviderError, RetrievalError
from app.core.persistence_sanitize import sanitize_for_persistence
from app.domain_engine.models import DomainConfig
from app.handoff.service import HandoffService
from app.llm.service import LLMService
from app.orchestration.confidence import compute_confidence
from app.orchestration.prompt_builder import build_prompt
from app.orchestration.references import public_references
from app.retrieval.service import RetrievalService
from app.conversations.service import ConversationHistoryService, hash_session
from app.conversations.session_state import SessionState, SessionStateStore
from app.conversations.summary import SummaryRecallService


logger = logging.getLogger(__name__)


class ChatFlowService:
    BLOCKING_REASONS = {
        "card_data",
        "explicit_human_request",
        "out_of_scope",
        "prompt_injection_attempt",
        "secret_request",
    }

    def __init__(
        self,
        *,
        history_service: ConversationHistoryService | None = None,
        session_state_store: SessionStateStore | None = None,
        summary_recall: "SummaryRecallService | None" = None,
    ) -> None:
        self.retrieval_service = RetrievalService()
        self.llm_service = LLMService()
        self.handoff_service = HandoffService()
        self.history_service = history_service
        self.session_state_store = session_state_store
        self.summary_recall = summary_recall

    def answer(
        self,
        domain: DomainConfig,
        question: str,
        session_id: str | None = None,
        request_id: str | None = None,
        provider_api_key: str | None = None,
        channel: str = "api",
        customer_id: str | None = None,
    ) -> dict[str, object]:
        result = self._answer_inner(
            domain,
            question,
            session_id=session_id,
            request_id=request_id,
            provider_api_key=provider_api_key,
            channel=channel,
            customer_id=customer_id,
        )
        if "answer" in result:
            notices = self._rule_notices(domain, result.get("handoff_reasons") or [])
            # ``answer`` keeps the notices prepended (every channel and the evals
            # read it); ``notices`` lets a rich client render them apart.
            result["notices"] = notices
            result["answer"] = self._with_rule_notices(
                domain, result.get("handoff_reasons") or [], str(result["answer"] or "")
            )
        # Hot-tier state write (non-authoritative, fail-open). No-op without a store.
        self._record_session_state(
            domain=domain, session_id=session_id, channel=channel, result=result
        )
        return result

    @staticmethod
    def _rule_notices(domain: DomainConfig, reasons: list[str]) -> list[str]:
        """The ``notice`` of every matched escalation rule, once each, in rule order."""
        matched = set(reasons)
        notices: list[str] = []
        handoff = getattr(domain, "handoff", None)
        for rule in getattr(handoff, "escalation_rules", None) or ():
            notice = (rule.notice or "").strip()
            if rule.reason in matched and notice and notice not in notices:
                notices.append(notice)
        return notices

    @classmethod
    def _with_rule_notices(
        cls, domain: DomainConfig, reasons: list[str], answer: str
    ) -> str:
        """Prepend the ``notice`` of every matched escalation rule, once each."""
        notices = cls._rule_notices(domain, reasons)
        if not notices:
            return answer
        return "\n\n".join([*notices, answer] if answer else notices)

    def _record_session_state(
        self,
        *,
        domain: DomainConfig,
        session_id: str | None,
        channel: str,
        result: dict[str, object],
    ) -> None:
        store = self.session_state_store
        if store is None or not session_id:
            return
        try:
            from app.core.config import get_settings

            settings = get_settings()
            session_hash = hash_session(
                session_id, settings.persistence_hash_secret or ""
            )
            state = SessionState(
                state="escalated" if result.get("escalated") else "answered",
                domain=str(result.get("domain") or domain.name),
                confidence=float(result.get("confidence") or 0.0),
                updated_at=time.time(),
                redaction_version=getattr(settings, "persistence_hash_version", None),
            )
            store.put(
                domain=domain.name,
                channel=channel,
                session_hash=session_hash,
                state=state,
                ttl_seconds=settings.session_state_ttl_seconds,
            )
        except Exception:  # noqa: BLE001 - hot state is non-authoritative; never break /chat.
            logger.debug("session_state_write_skipped", exc_info=False)

    def _recall_customer_summary(
        self,
        *,
        domain: DomainConfig,
        session_id: str | None,
        customer_id: str | None,
    ) -> str | None:
        recall = self.summary_recall
        if recall is None:
            return None
        try:
            from app.core.config import get_settings

            settings = get_settings()
            if not settings.enable_summary_recall:
                return None
            if customer_id:
                customer_ref: str | None = str(customer_id)
            elif session_id:
                customer_ref = hash_session(
                    session_id, settings.persistence_hash_secret or ""
                )
            else:
                customer_ref = None
            return recall.latest_for(domain=domain.name, customer_ref=customer_ref)
        except Exception:  # noqa: BLE001 - recall is best-effort; never break /chat.
            logger.debug("summary_recall_skipped", exc_info=False)
            return None

    def _answer_inner(
        self,
        domain: DomainConfig,
        question: str,
        session_id: str | None = None,
        request_id: str | None = None,
        provider_api_key: str | None = None,
        channel: str = "api",
        customer_id: str | None = None,
    ) -> dict[str, object]:
        total_started_at = perf_counter()
        retrieval_ms = 0.0
        llm_ms = 0.0
        llm_started_at = None
        error_code = None
        provider_failure_kind = None
        chunks = []

        pre_handoff_reasons = self.handoff_service.inspect_question(domain, question)
        # Detection above needs the raw text (card, CPF, secrets). Everything that
        # leaves the process -- embedding query and LLM prompt -- gets the masked
        # text, so personal data typed by the citizen never reaches a provider.
        provider_question = sanitize_for_persistence(question) or ""

        if self._should_block_automated_response(pre_handoff_reasons):
            if self._can_retrieve_references_for_blocked_response(pre_handoff_reasons):
                try:
                    retrieval_started_at = perf_counter()
                    chunks = self.retrieval_service.retrieve(domain, provider_question)
                except RetrievalError:
                    chunks = []
                finally:
                    retrieval_ms += self._elapsed_ms(retrieval_started_at)
            return {
                "request_id": request_id or "",
                "domain": domain.name,
                "answer": self._build_hardened_response(pre_handoff_reasons),
                "confidence": 0.0,
                "escalated": True,
                "handoff_reasons": pre_handoff_reasons,
                "references": public_references(
                    (chunk.source for chunk in chunks), domain.name
                ),
                "error_code": None,
                "provider_failure_kind": None,
                "observability": self._build_observability(
                    total_started_at=total_started_at,
                    retrieval_ms=retrieval_ms,
                    llm_ms=llm_ms,
                ),
            }

        try:
            retrieval_started_at = perf_counter()
            chunks = self.retrieval_service.retrieve(domain, provider_question)
        except RetrievalError as exc:
            error_code = exc.error_code
        finally:
            retrieval_ms += self._elapsed_ms(retrieval_started_at)

        confidence = compute_confidence(domain, chunks)
        # WS-2: only when context-aware scope is on for this domain, load history early
        # so decide() can see recent user turns. It is reused for the prompt below, so
        # there is at most one history read; with the flag off this is a no-op and the
        # hot path is unchanged.
        history: list[dict[str, str]] | None = None
        recent_user_texts: list[str] | None = None
        if domain.is_flag_enabled(self.handoff_service.CONTEXT_AWARE_SCOPE_FLAG):
            history = self._build_history(
                domain=domain,
                session_id=session_id,
                request_id=request_id,
                channel=channel,
                customer_id=customer_id,
            )
            recent_user_texts = [
                message["content"]
                for message in history
                if message.get("role") == "user" and message.get("content")
            ]
        handoff = self.handoff_service.decide(
            domain=domain,
            question=question,
            confidence=confidence,
            recent_user_texts=recent_user_texts,
        )
        handoff_reasons = list(handoff.reasons)
        if error_code and error_code not in handoff_reasons:
            handoff_reasons.append(error_code)

        if self._should_block_automated_response(handoff_reasons):
            return {
                "request_id": request_id or "",
                "domain": domain.name,
                "answer": self._build_hardened_response(handoff_reasons),
                "confidence": confidence,
                "escalated": True,
                "handoff_reasons": handoff_reasons,
                "references": public_references(
                    (chunk.source for chunk in chunks), domain.name
                ),
                "error_code": error_code,
                "provider_failure_kind": provider_failure_kind,
            }

        if not chunks:
            answer = domain.response.no_context_message
        else:
            try:
                if history is None:
                    history = self._build_history(
                        domain=domain,
                        session_id=session_id,
                        request_id=request_id,
                        channel=channel,
                        customer_id=customer_id,
                    )
                prompt = build_prompt(
                    domain=domain,
                    question=provider_question,
                    chunks=chunks,
                    history=history,
                    customer_summary=self._recall_customer_summary(
                        domain=domain,
                        session_id=session_id,
                        customer_id=customer_id,
                    ),
                )
                llm_started_at = perf_counter()
                answer = self.llm_service.get_provider(
                    domain,
                    api_key=provider_api_key,
                ).generate_answer(prompt)
            except ProviderError as exc:
                error_code = exc.error_code
                provider_failure_kind = exc.failure_kind
                if error_code not in handoff_reasons:
                    handoff_reasons.append(error_code)
                answer = domain.response.provider_error_message
            finally:
                if llm_started_at is not None:
                    llm_ms += self._elapsed_ms(llm_started_at)

        return {
            "request_id": request_id or "",
            "domain": domain.name,
            "answer": answer,
            "confidence": confidence,
            "escalated": bool(handoff_reasons),
            "handoff_reasons": handoff_reasons,
            "references": public_references(
                (chunk.source for chunk in chunks), domain.name
            ),
            "error_code": error_code,
            "provider_failure_kind": provider_failure_kind,
            "observability": self._build_observability(
                total_started_at=total_started_at,
                retrieval_ms=retrieval_ms,
                llm_ms=llm_ms,
            ),
        }

    def _build_history(
        self,
        *,
        domain: DomainConfig,
        session_id: str | None,
        request_id: str | None,
        channel: str,
        customer_id: str | None,
    ) -> list[dict[str, str]]:
        if self.history_service is None:
            return []
        return self.history_service.load_recent(
            domain=domain.name,
            channel=channel,
            session_id=session_id,
            request_id=request_id,
            customer_id=customer_id,
        )

    def _should_block_automated_response(self, reasons: list[str]) -> bool:
        return any(reason in self.BLOCKING_REASONS for reason in reasons)

    def _can_retrieve_references_for_blocked_response(self, reasons: list[str]) -> bool:
        retrievable_reasons = {"sensitive_topic", "explicit_human_request"}
        return bool(reasons) and all(reason in retrievable_reasons for reason in reasons)

    def _build_hardened_response(self, reasons: list[str]) -> str:
        if "card_data" in reasons:
            return (
                "Por segurança, não envie dados de cartão por aqui. "
                "Este canal nunca pede número de cartão. "
                "Vou encaminhar você para o atendimento humano."
            )

        if "explicit_human_request" in reasons:
            return (
                "Vou escalar para atendimento humano. "
                "Não vou pedir nem expor senha, token, chave ou detalhes internos por aqui."
            )

        if "out_of_scope" in reasons:
            return (
                "Não posso atuar fora do escopo deste domínio. "
                "Se o tema fugir do que este canal cobre, "
                "o caminho seguro é escalar para atendimento humano."
            )

        if "prompt_injection_attempt" in reasons or "secret_request" in reasons:
            return (
                "Não posso revelar prompt interno, regras de segurança, senha, token, chave ou credencial, "
                "nem ignorar as proteções deste domínio. "
                "Posso orientar apenas passos seguros e públicos ou escalar para atendimento humano."
            )

        if "sensitive_topic" in reasons:
            return (
                "Esse tema exige cuidado e atendimento humano. "
                "Posso explicar apenas riscos gerais e próximos passos seguros, "
                "sem prometer desbloqueio, tratar cobrança ou orientar acesso sensível por aqui."
            )

        return (
            "Não encontrei um caminho seguro para responder automaticamente. "
            "Vou sinalizar escalonamento para atendimento humano."
        )

    def _elapsed_ms(self, started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 3)

    def _build_observability(
        self,
        total_started_at: float,
        retrieval_ms: float,
        llm_ms: float,
    ) -> dict[str, float]:
        return {
            "total_ms": self._elapsed_ms(total_started_at),
            "retrieval_ms": round(retrieval_ms, 3),
            "llm_ms": round(llm_ms, 3),
        }
