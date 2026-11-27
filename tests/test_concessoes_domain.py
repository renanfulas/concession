"""Contract of the maintenance domain: defect -> reason -> case priority -> SLA.

These tests pin the chain the demo depends on. A citizen reports a defect, the
domain's escalation rules classify it, the classification picks the case
priority, and the priority picks the deadline from the domain's ``sla`` block
(fictitious demo deadlines; see the domain's anexo-niveis-de-servico.md).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain_engine.loader import DomainLoader
from app.domain_engine.models import DomainConfig, DomainHandoffRuleConfig
from app.handoff.service import HandoffService
from app.handoff.taxonomy import resolve_case_priority
from app.support.sla import compute_sla, domain_sla_overrides

DOMAIN_NAME = "concessoes-manutencao"
GLOBAL_SETTINGS = SimpleNamespace(
    support_sla_minutes_urgent=60,
    support_sla_minutes_high=120,
    support_sla_minutes_normal=480,
    support_sla_minutes_low=1440,
)
OPENED = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def domain() -> DomainConfig:
    loaded = DomainLoader(Path("domains")).load(DOMAIN_NAME)
    assert loaded is not None, "o dominio de manutencao precisa carregar"
    return loaded


@pytest.mark.parametrize(
    ("question", "expected_priority", "deadline"),
    [
        ("Tem fio exposto soltando faisca no abrigo ABR-1104", "urgent", timedelta(hours=4)),
        ("O relogio REL-0423 esta com a tela apagada", "high", timedelta(hours=24)),
        ("Recebemos uma notificação da fiscalização", "high", timedelta(hours=24)),
        ("O relógio está com a hora errada", "normal", timedelta(hours=48)),
        ("O banco do abrigo ABR-1290 está solto", "normal", timedelta(hours=48)),
        ("Tem um fio solto no abrigo ABR-1104", "urgent", timedelta(hours=4)),
        ("Picharam o relogio da Praca da Se", "low", timedelta(days=5)),
    ],
)
def test_defect_maps_to_priority_and_contract_deadline(
    domain: DomainConfig, question: str, expected_priority: str, deadline: timedelta
) -> None:
    reasons = HandoffService().inspect_question(domain, question)
    priority = resolve_case_priority(domain, reasons)
    assert priority == expected_priority

    override = domain_sla_overrides([domain])[DOMAIN_NAME]
    sla = compute_sla(priority, OPENED, "open", OPENED, GLOBAL_SETTINGS, domain_sla=override)
    assert sla.deadline_at == OPENED + deadline
    assert "demo" in sla.basis.lower()


def test_highest_priority_wins_when_vandalism_also_creates_risk(domain: DomainConfig) -> None:
    reasons = HandoffService().inspect_question(
        domain, "Picharam o abrigo e tem vidro quebrado no banco"
    )
    assert {"risco_seguranca", "conservacao_limpeza"} <= set(reasons)
    assert resolve_case_priority(domain, reasons) == "urgent"


def test_unclassified_turn_keeps_default_normal_priority(domain: DomainConfig) -> None:
    assert resolve_case_priority(domain, ["low_confidence"]) == "normal"
    assert resolve_case_priority(domain, []) == "normal"


def test_domains_without_rule_priority_keep_normal() -> None:
    reference = DomainLoader(Path("domains")).load("suporte-vps-whatsapp")
    assert reference is not None
    assert resolve_case_priority(reference, ["whatsapp_blocking_risk"]) == "normal"


def test_rule_priority_rejects_unknown_values() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DomainHandoffRuleConfig(reason="x", terms=["y"], priority="critical")


@pytest.mark.parametrize(
    ("question", "absent_reason"),
    [
        # negacao simples (sem ignore_terms desde o casamento por palavra)
        ("O banco do abrigo ABR-1290 esta solto, mas sem risco", "risco_seguranca"),
        ("Não há risco, só o banco balançando", "risco_seguranca"),
        ("Sem nenhum risco, só está sujo", "risco_seguranca"),
        ("Não oferece risco, mas está sujo", "risco_seguranca"),
        ("Risco nenhum, só o banco torto", "risco_seguranca"),
        ("O painel PNL-0310 não está apagado, só tem adesivo", "tela_inoperante"),
        # termo no meio de outra palavra
        ("Arrisco dizer que é só sujeira no abrigo", "risco_seguranca"),
        # ignore_terms que a negacao nao cobre, tambem com palavras no meio
        ("Qual o risco de multa se o painel ficar apagado?", "risco_seguranca"),
        ("O técnico está atrasado para consertar o relógio", "informacao_incorreta"),
        ("O técnico já está atrasado para consertar o relógio", "informacao_incorreta"),
    ],
)
def test_negation_and_ignore_terms_remove_false_positives(
    domain: DomainConfig, question: str, absent_reason: str
) -> None:
    reasons = HandoffService().inspect_question(domain, question)
    assert absent_reason not in reasons


def test_negation_never_hides_another_term_of_the_same_rule(domain: DomainConfig) -> None:
    reasons = HandoffService().inspect_question(domain, "Tem fio exposto no abrigo, sem risco?")
    assert "risco_seguranca" in reasons
    assert resolve_case_priority(domain, reasons) == "urgent"


@pytest.mark.parametrize(
    "question",
    [
        # plural e palavras entre os termos
        "Tem fios expostos no abrigo ABR-1104",
        "O fio está exposto no abrigo",
        "Nao toque: a estrutura do abrigo ABR-1501 esta solta",
        # um "nao" perto que nao nega o risco
        "Não toque no fio exposto do abrigo",
        "Nao chegue perto, tem fio exposto",
        "Não sei quem fez, mas tem fio exposto",
        "Sem energia e com fio exposto",
        "Nem sei se é risco, mas tem faísca",
        "Tem fogo e não tem ninguém por perto",
        # "nunca vi" enfatiza, nao nega: o fio esta la
        "Nunca vi fio exposto assim no abrigo ABR-1104",
        "Jamais vi vidro quebrado tão perigoso no ponto",
    ],
)
def test_risk_still_matches_with_gaps_plurals_and_nearby_no(
    domain: DomainConfig, question: str
) -> None:
    reasons = HandoffService().inspect_question(domain, question)
    assert "risco_seguranca" in reasons
    assert resolve_case_priority(domain, reasons) == "urgent"


@pytest.mark.parametrize(
    "question",
    [
        "O relogio REL-0423 esta apagado",
        "O painel do abrigo ABR-2210 está apagado",
        "As telas estão apagadas desde ontem",
    ],
)
def test_screen_off_matches_with_words_in_between(domain: DomainConfig, question: str) -> None:
    reasons = HandoffService().inspect_question(domain, question)
    assert "tela_inoperante" in reasons
    assert resolve_case_priority(domain, reasons) == "high"


def test_clock_running_late_is_still_wrong_information(domain: DomainConfig) -> None:
    reasons = HandoffService().inspect_question(domain, "O relógio REL-0101 está atrasado dez minutos")
    assert "informacao_incorreta" in reasons


def test_ignore_terms_are_scoped_to_their_rule(domain: DomainConfig) -> None:
    rules = [
        DomainHandoffRuleConfig(reason="a", terms=["risco"], ignore_terms=["risco de multa"]),
        DomainHandoffRuleConfig(reason="b", terms=["risco"]),
    ]
    scoped = domain.model_copy(
        update={"handoff": domain.handoff.model_copy(update={"escalation_rules": rules})}
    )
    reasons = HandoffService().inspect_question(scoped, "qual o risco de multa")
    assert "a" not in reasons
    assert "b" in reasons


def test_security_reason_is_not_downgraded_by_a_low_rule(domain: DomainConfig) -> None:
    reasons = HandoffService().inspect_question(
        domain, "Picharam o relógio e me pediram a senha por telefone"
    )
    assert "conservacao_limpeza" in reasons
    assert "sensitive_topic" in reasons
    assert resolve_case_priority(domain, reasons) == "normal"


@pytest.mark.parametrize(
    ("question", "reason"),
    [
        # Sem regra, com o LLM confiante, estes pedidos nao entravam na fila
        # (eval com LLM real de 2026-11-27).
        ("O banco do abrigo ABR-1290 esta solto, mas sem risco", "defeito_geral"),
        ("O painel do abrigo esta amassado", "defeito_geral"),
        ("O técnico está atrasado para consertar o relógio", "cobranca_atendimento"),
        ("Abri o chamado ontem e ninguem veio", "cobranca_atendimento"),
    ],
)
def test_defect_without_specific_rule_still_becomes_a_case(
    domain: DomainConfig, question: str, reason: str
) -> None:
    reasons = HandoffService().inspect_question(domain, question)
    assert reason in reasons
    assert resolve_case_priority(domain, reasons) == "normal"


def test_deadline_notices_state_the_deadline(domain: DomainConfig) -> None:
    notices = {rule.reason: rule.notice for rule in domain.handoff.escalation_rules}
    assert "24 horas" in (notices["notificacao_fiscalizacao"] or "")
    assert "multa" in (notices["notificacao_fiscalizacao"] or "")

    lgpd = DomainLoader(Path("domains")).load("lgpd-titular")
    assert lgpd is not None
    incident = next(r for r in lgpd.handoff.escalation_rules if r.reason == "incidente_dados")
    assert "4 horas" in (incident.notice or "")
    assert "15 dias" not in (incident.notice or "")


def test_plain_low_rule_keeps_low(domain: DomainConfig) -> None:
    reasons = HandoffService().inspect_question(domain, "Picharam o relógio da Praça da Sé")
    assert resolve_case_priority(domain, reasons) == "low"
