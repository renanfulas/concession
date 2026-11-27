"""Regras de leitura do console staff (/web/support/*).

A rota valida a entrada e orquestra; aqui ficam as regras: SLA de cada caso
sobre o relogio do banco (com o prazo congelado na abertura e o override do
``domain.yaml``), filtro por cor e ordenacao por atencao da fila ativa,
detalhe com SLA e trilha, relatorio mensal em CSV e metricas.

Nada aqui conhece HTTP: excecoes de dominio (``InvalidMonth``) e
``DatabaseUnavailableError`` sobem para a rota traduzir em status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.runtime import DatabaseRuntime
from app.domain_engine.loader import DomainLoader
from app.domain_engine.models import DomainConfig
from app.support.context import SupportCaseContext
from app.support.metrics import SupportMetricsRepository, build_console_metrics
from app.support.monthly_report import build_report_rows, month_bounds, render_csv
from app.support.repository import (
    CaseEventSummary,
    SupportCaseRepository,
    SupportCaseSummary,
)
from app.support.sla import (
    DomainSla,
    SlaAssessment,
    compute_sla,
    domain_sla_overrides,
    frozen_case_sla,
    matches_color_filter,
    sort_by_attention,
)


CLOSED_STATUSES = {"closed", "cancelled"}


@dataclass(frozen=True)
class ConsoleCase:
    summary: SupportCaseSummary
    # None no historico: fechados/cancelados nao passam por SLA.
    sla: SlaAssessment | None = None


@dataclass(frozen=True)
class ConsoleCasePage:
    cases: list[ConsoleCase]
    truncated: bool = False


@dataclass(frozen=True)
class ConsoleCaseDetail:
    context: SupportCaseContext
    sla: SlaAssessment | None
    events: list[CaseEventSummary]


@dataclass(frozen=True)
class MonthlyReport:
    body: str
    row_count: int
    truncated: bool


def load_domain_configs(domains_path: Any) -> list[DomainConfig]:
    """Every domain that loads from ``domains_path``; invalid ones are skipped."""

    loader = DomainLoader(domains_path)
    configs = [loader.load(name) for name in loader.list_domains()]
    return [config for config in configs if config is not None]


def load_domain_sla_overrides(settings: Any) -> dict[str, DomainSla]:
    """Per-domain SLA declared in each ``domain.yaml``; read once per request."""

    return domain_sla_overrides(load_domain_configs(settings.domains_path))


def assess_case(
    case: SupportCaseSummary,
    db_now: Any,
    settings: Any,
    overrides: dict[str, DomainSla] | None = None,
) -> SlaAssessment:
    return compute_sla(
        case.priority,
        case.opened_at,
        case.status,
        db_now,
        settings,
        waiting_seconds=case.waiting_seconds,
        domain_sla=frozen_case_sla(
            case.priority, case.sla_minutes, case.sla_basis, (overrides or {}).get(case.domain)
        ),
    )


class SupportConsoleService:
    """Read side of the staff console over ``SupportCaseRepository``."""

    def __init__(self, *, settings: Any, database_runtime: DatabaseRuntime) -> None:
        self.settings = settings
        self.database_runtime = database_runtime
        self.repository = SupportCaseRepository(database_runtime)

    def list_history(
        self,
        *,
        domain: str | None,
        status: str | None,
        limit: int,
        offset: int,
        assignee_staff_id: str | None,
    ) -> ConsoleCasePage:
        # Historico nao passa por SLA: paginacao SQL normal.
        summaries = self.repository.list_history_cases(
            domain=domain,
            status=status,
            limit=limit,
            offset=offset,
            assignee_staff_id=assignee_staff_id,
        )
        return ConsoleCasePage(cases=[ConsoleCase(summary=case) for case in summaries])

    def list_active(
        self,
        *,
        domain: str | None,
        status: str | None,
        color: str | None,
        sort: str,
        limit: int,
        offset: int,
        assignee_staff_id: str | None,
    ) -> ConsoleCasePage:
        """Active queue: SLA, color filter and attention order in Python.

        SQL only filters and caps the active set; pagination happens after
        the color filter and ordering, so a page never skips a case.
        """

        active = self.repository.list_active_cases(
            domain=domain,
            status=status,
            cap=self.settings.support_console_active_cases_cap,
            assignee_staff_id=assignee_staff_id,
        )
        overrides = load_domain_sla_overrides(self.settings)
        assessed = [
            (case, assess_case(case, active.db_now, self.settings, overrides))
            for case in active.cases
        ]
        if color is not None:
            assessed = [item for item in assessed if matches_color_filter(item[1], color)]
        if sort == "attention":
            assessed = sort_by_attention(assessed)
        page = assessed[offset : offset + limit]
        return ConsoleCasePage(
            cases=[ConsoleCase(summary=case, sla=sla) for case, sla in page],
            truncated=active.truncated,
        )

    def get_case_detail(self, case_id: str) -> ConsoleCaseDetail | None:
        """Case with context, SLA (only while open) and audit trail; None if absent."""

        repository = self.repository
        context = repository.get_case_with_context(case_id)
        if context is None:
            return None
        sla = None
        if context.status not in CLOSED_STATUSES and context.opened_at:
            db_now = repository.database_now()
            waiting_seconds = repository.get_case_waiting_seconds(case_id, db_now)
            sla = compute_sla(
                context.priority,
                context.opened_at,
                context.status,
                db_now,
                self.settings,
                waiting_seconds=waiting_seconds,
                domain_sla=frozen_case_sla(
                    context.priority,
                    context.sla_minutes,
                    context.sla_basis,
                    load_domain_sla_overrides(self.settings).get(context.domain),
                ),
            )
        events = repository.get_case_events(case_id)
        return ConsoleCaseDetail(context=context, sla=sla, events=events)

    def monthly_report(self, *, month: str, domain: str | None) -> MonthlyReport:
        """CSV for the auditor; raises ``InvalidMonth`` before touching the database."""

        timezone_name = self.settings.support_console_timezone
        start, end = month_bounds(month, timezone_name)
        cases, db_now, truncated = self.repository.list_cases_opened_between(
            start=start, end=end, domain=domain
        )
        body = render_csv(
            build_report_rows(
                cases,
                db_now=db_now,
                settings=self.settings,
                domain_sla=load_domain_sla_overrides(self.settings),
                timezone_name=timezone_name,
            )
        )
        return MonthlyReport(body=body, row_count=len(cases), truncated=truncated)

    def metrics(self, *, window: str, domain: str | None) -> dict[str, Any]:
        now = self.repository.database_now()
        return build_console_metrics(
            case_repository=self.repository,
            metrics_repository=SupportMetricsRepository(self.database_runtime),
            window=window,
            domain=domain,
            settings=self.settings,
            now=now,
            domain_sla=load_domain_sla_overrides(self.settings),
        )
