"""Coverage for the console SLA math (pure functions, injected clock)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.support.sla import (
    attention_sort_key,
    compute_sla,
    matches_color_filter,
    sort_by_attention,
)


SETTINGS = SimpleNamespace(
    support_sla_minutes_urgent=60,
    support_sla_minutes_high=120,
    support_sla_minutes_normal=480,
    support_sla_minutes_low=1440,
)

OPENED = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)


def _sla(priority: str, *, minutes_elapsed: int, status: str = "open"):
    return compute_sla(
        priority,
        OPENED,
        status,
        OPENED + timedelta(minutes=minutes_elapsed),
        SETTINGS,
    )


# --------------------------------------------------------------------------- #
# Color thresholds: green < 0.6 <= yellow <= 1.0 < red
# --------------------------------------------------------------------------- #


def test_color_green_below_sixty_percent() -> None:
    sla = _sla("urgent", minutes_elapsed=35)
    assert sla.color == "green"
    assert not sla.paused
    assert sla.deadline_at == OPENED + timedelta(minutes=60)


def test_color_yellow_between_sixty_percent_and_deadline() -> None:
    assert _sla("urgent", minutes_elapsed=36).color == "yellow"
    assert _sla("urgent", minutes_elapsed=60).color == "yellow"


def test_color_red_after_deadline() -> None:
    sla = _sla("urgent", minutes_elapsed=61)
    assert sla.color == "red"
    assert sla.elapsed_ratio > 1.0


def test_unknown_priority_falls_back_to_normal_sla() -> None:
    sla = _sla("banana", minutes_elapsed=480)
    assert sla.deadline_at == OPENED + timedelta(minutes=480)


# --------------------------------------------------------------------------- #
# Paused cases never go red
# --------------------------------------------------------------------------- #


def test_paused_case_never_red_even_way_past_deadline() -> None:
    sla = _sla("urgent", minutes_elapsed=600, status="waiting_customer")
    assert sla.paused
    assert sla.color == "yellow"
    assert "aguardando cliente" in sla.explanation


def test_pending_consent_counts_as_paused() -> None:
    sla = _sla("normal", minutes_elapsed=10, status="pending_consent")
    assert sla.paused
    assert "aguardando consentimento" in sla.explanation


# --------------------------------------------------------------------------- #
# Explanations (staff-facing pt-BR, ortografia plena)
# --------------------------------------------------------------------------- #


def test_explanation_overdue_matches_plan_example() -> None:
    sla = _sla("urgent", minutes_elapsed=372)  # aberto ha 6h12, SLA 60min
    assert sla.explanation == "urgente, aberto há 6h12, prazo estourado há 5h12"


def test_explanation_within_deadline_shows_remaining_time() -> None:
    sla = _sla("high", minutes_elapsed=30)
    assert sla.explanation == "alta, aberto há 30min, prazo em 1h30"


def test_explanation_uses_days_for_long_waits() -> None:
    sla = _sla("low", minutes_elapsed=3 * 24 * 60)
    assert "aberto há 3d" in sla.explanation


# --------------------------------------------------------------------------- #
# Fase B seam: waiting_seconds pushes the deadline and pauses the clock
# --------------------------------------------------------------------------- #


def test_waiting_seconds_extends_deadline_and_discounts_elapsed() -> None:
    waited = 30 * 60
    sla = compute_sla(
        "urgent",
        OPENED,
        "open",
        OPENED + timedelta(minutes=60),
        SETTINGS,
        waiting_seconds=waited,
    )
    assert sla.deadline_at == OPENED + timedelta(minutes=90)
    assert sla.elapsed_ratio == 0.5
    assert sla.color == "green"


# --------------------------------------------------------------------------- #
# Attention ordering: semaforo (vermelho > amarelo > verde > pausado), depois
# prazo mais proximo, depois prioridade, mais antigo e case_id
# --------------------------------------------------------------------------- #


def test_attention_order_by_severity_then_deadline() -> None:
    now = OPENED + timedelta(hours=3)

    def entry(case_id: str, priority: str, opened_delta_minutes: int, status: str = "open"):
        opened = OPENED + timedelta(minutes=opened_delta_minutes)
        return case_id, priority, opened, compute_sla(priority, opened, status, now, SETTINGS)

    entries = [
        entry("normal-old", "normal", 0),
        entry("urgent-overdue", "urgent", 10),  # 2h50 > 60min SLA
        entry("urgent-paused-overdue", "urgent", 0, status="waiting_customer"),
        entry("high-fresh", "high", 170),
        entry("high-overdue", "high", 30),  # 2h30 > 2h SLA
    ]
    ordered = sorted(
        entries,
        key=lambda item: attention_sort_key(
            priority=item[1], opened_at=item[2], sla=item[3]
        ),
    )

    assert [item[0] for item in ordered] == [
        "urgent-overdue",  # estourou primeiro (prazo 13:10)
        "high-overdue",  # estourou depois (prazo 14:30)
        "high-fresh",  # verde, prazo 16:50
        "normal-old",  # verde, prazo 20:00
        "urgent-paused-overdue",  # pausado vai para o fim: aguarda o cliente
    ]


def _case(case_id: str, priority: str, opened_at: datetime):
    return SimpleNamespace(case_id=case_id, priority=priority, opened_at=opened_at)


def test_cross_domain_queue_follows_deadline_pressure_not_age() -> None:
    from app.support.sla import DomainSla

    now = OPENED + timedelta(days=10)
    maintenance = DomainSla(minutes_by_priority={"normal": 48 * 60}, basis="Contrato demo")
    lgpd = DomainSla(minutes_by_priority={"normal": 15 * 24 * 60}, basis="LGPD art. 19, II")

    lgpd_opened = now - timedelta(days=3)
    maintenance_opened = now - timedelta(hours=47)
    lgpd_case = _case("lgpd-normal", "normal", lgpd_opened)
    maintenance_case = _case("manutencao-normal", "normal", maintenance_opened)
    lgpd_sla = compute_sla("normal", lgpd_opened, "open", now, SETTINGS, domain_sla=lgpd)
    maintenance_sla = compute_sla(
        "normal", maintenance_opened, "open", now, SETTINGS, domain_sla=maintenance
    )

    # Antes: mesma prioridade, o LGPD (mais antigo) vinha primeiro.
    assert lgpd_sla.color == "green" and lgpd_sla.elapsed_ratio == 0.2
    assert maintenance_sla.color == "yellow" and maintenance_sla.elapsed_ratio > 0.97
    assert "prazo em 1h" in maintenance_sla.explanation

    ordered = sort_by_attention([(lgpd_case, lgpd_sla), (maintenance_case, maintenance_sla)])

    assert [case.case_id for case, _ in ordered] == ["manutencao-normal", "lgpd-normal"]


def test_breached_low_priority_beats_high_priority_green() -> None:
    now = OPENED + timedelta(hours=30)
    low_opened = OPENED  # 30h > 24h do SLA low: estourado
    urgent_opened = now - timedelta(minutes=5)  # 5 de 60 min: verde
    low = (_case("low-breached", "low", low_opened), compute_sla("low", low_opened, "open", now, SETTINGS))
    urgent = (
        _case("urgent-green", "urgent", urgent_opened),
        compute_sla("urgent", urgent_opened, "open", now, SETTINGS),
    )
    assert low[1].color == "red"
    assert urgent[1].color == "green"

    ordered = sort_by_attention([urgent, low])

    assert [case.case_id for case, _ in ordered] == ["low-breached", "urgent-green"]


def test_attention_order_is_deterministic_on_full_ties() -> None:
    now = OPENED + timedelta(hours=1)
    entries = [
        (_case(case_id, "normal", OPENED), compute_sla("normal", OPENED, "open", now, SETTINGS))
        for case_id in ("case-c", "case-a", "case-b")
    ]

    forward = sort_by_attention(entries)
    backward = sort_by_attention(list(reversed(entries)))

    assert [case.case_id for case, _ in forward] == ["case-a", "case-b", "case-c"]
    assert [case.case_id for case, _ in backward] == ["case-a", "case-b", "case-c"]
    # Puro: a entrada nao foi reordenada.
    assert [case.case_id for case, _ in entries] == ["case-c", "case-a", "case-b"]


def test_equal_deadline_falls_back_to_priority_weight() -> None:
    now = OPENED + timedelta(minutes=65)
    # high aberto em OPENED (prazo +120) e urgent aberto 60 min depois (prazo +120):
    # mesmo prazo, ambos verdes; a prioridade desempata.
    urgent_opened = OPENED + timedelta(minutes=60)
    high = (_case("high", "high", OPENED), compute_sla("high", OPENED, "open", now, SETTINGS))
    urgent = (
        _case("urgent", "urgent", urgent_opened),
        compute_sla("urgent", urgent_opened, "open", now, SETTINGS),
    )
    assert high[1].deadline_at == urgent[1].deadline_at

    ordered = sort_by_attention([high, urgent])

    assert [case.case_id for case, _ in ordered] == ["urgent", "high"]


# --------------------------------------------------------------------------- #
# Color filter: paused is its own bucket
# --------------------------------------------------------------------------- #


def test_color_filter_paused_bucket_is_exclusive() -> None:
    paused = _sla("urgent", minutes_elapsed=600, status="waiting_customer")
    active_red = _sla("urgent", minutes_elapsed=600)

    assert matches_color_filter(paused, "paused")
    assert not matches_color_filter(paused, "yellow")
    assert matches_color_filter(active_red, "red")
    assert not matches_color_filter(active_red, "paused")


# --------------------------------------------------------------------------- #
# Per-domain SLA (domain.yaml ``sla:`` block): contract / legal deadlines
# --------------------------------------------------------------------------- #

from pathlib import Path  # noqa: E402

from app.domain_engine.models import DomainConfig, DomainSlaConfig  # noqa: E402
from app.support.sla import DomainSla, domain_sla_overrides  # noqa: E402


def _domain(name: str, sla: DomainSlaConfig | None = None) -> DomainConfig:
    payload = {"name": name, "display_name": name, "root_path": Path("domains") / name}
    if sla is not None:
        payload["sla"] = sla
    return DomainConfig.model_validate(payload)


def test_domain_sla_overrides_declared_priorities_and_keeps_global_for_the_rest() -> None:
    # 15 dias para a declaracao completa ao titular (LGPD art. 19, II).
    legal = DomainSla(minutes_by_priority={"normal": 15 * 24 * 60}, basis="LGPD art. 19, II")

    overridden = compute_sla(
        "normal", OPENED, "open", OPENED + timedelta(days=10), SETTINGS, domain_sla=legal
    )
    inherited = compute_sla(
        "urgent", OPENED, "open", OPENED + timedelta(minutes=30), SETTINGS, domain_sla=legal
    )

    assert overridden.deadline_at == OPENED + timedelta(days=15)
    assert overridden.color == "yellow"  # 10/15 dias = 0.67
    assert overridden.basis == "LGPD art. 19, II"
    # urgent nao foi declarado: usa o global (60 min) e ainda carrega a base.
    assert inherited.deadline_at == OPENED + timedelta(minutes=60)


def test_without_domain_sla_the_global_values_and_empty_basis_apply() -> None:
    sla = _sla("high", minutes_elapsed=60)
    assert sla.deadline_at == OPENED + timedelta(minutes=120)
    assert sla.basis == ""


def test_domain_sla_overrides_only_lists_domains_that_declare_one() -> None:
    domains = [
        _domain("referencia"),
        _domain(
            "concessoes-manutencao",
            DomainSlaConfig(urgent_minutes=240, high_minutes=1440, basis="Contrato demo, anexo de SLA"),
        ),
    ]

    overrides = domain_sla_overrides(domains)

    assert set(overrides) == {"concessoes-manutencao"}
    assert overrides["concessoes-manutencao"].minutes_by_priority == {"urgent": 240, "high": 1440}
    assert overrides["concessoes-manutencao"].basis == "Contrato demo, anexo de SLA"


def test_domain_sla_config_rejects_non_positive_minutes() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DomainSlaConfig(high_minutes=0)
