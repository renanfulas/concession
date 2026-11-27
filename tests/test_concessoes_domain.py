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
        ("O banco do abrigo ABR-1290 esta solto, mas sem risco", "risco_seguranca"),
        ("Não há risco, só o banco balançando", "risco_seguranca"),
        ("Qual o risco de multa se o painel ficar apagado?", "risco_seguranca"),
        ("O técnico está atrasado para consertar o relógio", "informacao_incorreta"),
    ],
)
def test_ignore_terms_remove_false_positives(
    domain: DomainConfig, question: str, absent_reason: str
) -> None:
    reasons = HandoffService().inspect_question(domain, question)
    assert absent_reason not in reasons


def test_ignore_terms_never_hide_another_term_of_the_same_rule(domain: DomainConfig) -> None:
    reasons = HandoffService().inspect_question(domain, "Tem fio exposto no abrigo, sem risco?")
    assert "risco_seguranca" in reasons
    assert resolve_case_priority(domain, reasons) == "urgent"


def test_clock_running_late_is_still_wrong_information(domain: DomainConfig) -> None:
    reasons = HandoffService().inspect_question(domain, "O relógio REL-0101 está atrasado dez minutos")
    assert "informacao_incorreta" in reasons


def test_ignore_terms_are_scoped_to_their_rule(domain: DomainConfig) -> None:
    rules = [
        DomainHandoffRuleConfig(reason="a", terms=["risco"], ignore_terms=["sem risco"]),
        DomainHandoffRuleConfig(reason="b", terms=["risco"]),
    ]
    scoped = domain.model_copy(
        update={"handoff": domain.handoff.model_copy(update={"escalation_rules": rules})}
    )
    reasons = HandoffService().inspect_question(scoped, "esta sem risco")
    assert "a" not in reasons
    assert "b" in reasons


def test_security_reason_is_not_downgraded_by_a_low_rule(domain: DomainConfig) -> None:
    reasons = HandoffService().inspect_question(
        domain, "Picharam o relógio e me pediram a senha por telefone"
    )
    assert "conservacao_limpeza" in reasons
    assert "sensitive_topic" in reasons
    assert resolve_case_priority(domain, reasons) == "normal"


def test_plain_low_rule_keeps_low(domain: DomainConfig) -> None:
    reasons = HandoffService().inspect_question(domain, "Picharam o relógio da Praça da Sé")
    assert resolve_case_priority(domain, reasons) == "low"
