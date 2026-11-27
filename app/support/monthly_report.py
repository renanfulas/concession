"""Relatorio mensal para a fiscalizacao (Fase 1, item 5).

Uma linha por caso aberto no mes (fuso do console), com a politica de prazo
gravada na abertura (migration 020), o resultado contra o prazo e o motivo do
atraso. Sem dado pessoal: nada de telefone, nome, e-mail, resumo, transcript
ou ``request_id``. O SQL fica no repositorio; aqui so calculo e formatacao.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from app.support.sla import (
    DomainSla,
    compute_sla,
    frozen_case_sla,
    resolve_case_sla_policy,
)


MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
GLOBAL_BASIS = "SLA global do console"
# Excel pt-BR uses ";" as the list separator and needs the BOM to read accents.
CSV_DELIMITER = ";"
CSV_BOM = "﻿"
# Cells starting with these are read as formulas by spreadsheet apps.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

COLUMNS = (
    "caso_id",
    "dominio",
    "canal",
    "motivos",
    "prioridade",
    "status",
    "aberto_em",
    "fechado_em",
    "prazo_minutos",
    "base_do_prazo",
    "prazo_em",
    "pausado_minutos",
    "resultado",
    "motivo_atraso",
)


@dataclass(frozen=True)
class ReportCase:
    case_id: str
    domain: str
    channel: str
    status: str
    priority: str
    reason_codes: list[str]
    opened_at: datetime
    closed_at: datetime | None
    sla_minutes: int | None
    sla_basis: str | None
    late_reason: str | None
    waiting_seconds: float = 0.0


class InvalidMonth(ValueError):
    pass


def month_bounds(month: str, timezone_name: str) -> tuple[datetime, datetime]:
    """``[start, end)`` of ``YYYY-MM`` in the console timezone, as aware datetimes."""

    match = MONTH_PATTERN.match(month or "")
    if match is None:
        raise InvalidMonth(month)
    year, month_number = int(match.group(1)), int(match.group(2))
    zone = ZoneInfo(timezone_name)
    start = datetime(year, month_number, 1, tzinfo=zone)
    end = (
        datetime(year + 1, 1, 1, tzinfo=zone)
        if month_number == 12
        else datetime(year, month_number + 1, 1, tzinfo=zone)
    )
    return start, end


def build_report_rows(
    cases: Iterable[ReportCase],
    *,
    db_now: datetime,
    settings: Any,
    domain_sla: Mapping[str, DomainSla] | None = None,
    timezone_name: str,
) -> list[list[str]]:
    zone = ZoneInfo(timezone_name)
    overrides = domain_sla or {}
    rows: list[list[str]] = []
    for case in cases:
        policy = frozen_case_sla(
            case.priority, case.sla_minutes, case.sla_basis, overrides.get(case.domain)
        )
        minutes, basis = resolve_case_sla_policy(case.priority, settings, policy)
        finished = case.status in {"closed", "cancelled"} and case.closed_at is not None
        reference = case.closed_at if finished else db_now
        assessment = compute_sla(
            case.priority,
            case.opened_at,
            "in_progress" if finished else case.status,
            reference,
            settings,
            waiting_seconds=case.waiting_seconds,
            domain_sla=policy,
        )
        rows.append(
            [
                case.case_id,
                case.domain,
                case.channel,
                "|".join(str(code) for code in case.reason_codes),
                case.priority,
                case.status,
                _local(case.opened_at, zone),
                _local(case.closed_at, zone) if case.closed_at else "",
                str(minutes),
                basis or GLOBAL_BASIS,
                _local(assessment.deadline_at, zone),
                str(int(max(0.0, case.waiting_seconds) // 60)),
                _outcome(case, assessment.elapsed_ratio),
                case.late_reason or "",
            ]
        )
    return rows


def render_csv(rows: Iterable[list[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([_neutralize_formula(cell) for cell in row])
    return CSV_BOM + buffer.getvalue()


def _outcome(case: ReportCase, elapsed_ratio: float) -> str:
    late = elapsed_ratio > 1.0
    if case.status == "cancelled":
        return "cancelado"
    if case.status == "closed":
        return "fora_do_prazo" if late else "no_prazo"
    return "em_aberto_atrasado" if late else "em_aberto_no_prazo"


def _local(value: datetime, zone: ZoneInfo) -> str:
    return value.astimezone(zone).strftime("%Y-%m-%d %H:%M")


def _neutralize_formula(cell: str) -> str:
    text = str(cell)
    return f"'{text}" if text.startswith(_FORMULA_PREFIXES) else text
