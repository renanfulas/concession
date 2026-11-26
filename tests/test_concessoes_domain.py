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
