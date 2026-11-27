"""Relatorio mensal (Fase 1, item 5): prazo gravado na abertura, motivo do
atraso obrigatorio e CSV sem dado pessoal.

Decisoes do responsavel pelo projeto: o prazo de cada caso sai da politica
gravada na abertura (``sla_minutes``/``sla_basis``, migration 020), nao do
SLA vigente; fechar depois do prazo exige um codigo de ``LATE_REASONS``.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db.schema_contract import CONTRACT_MIGRATION, REQUIRED_COLUMNS
from app.support.case_policy import case_sla_policy
from app.support.monthly_report import (
    COLUMNS,
    InvalidMonth,
    ReportCase,
    build_report_rows,
    month_bounds,
    render_csv,
)
from app.support.sla import (
    LATE_REASONS,
    DomainSla,
    frozen_case_sla,
    resolve_case_sla_policy,
)
from app.support.transitions import (
    LateReasonNotApplicable,
    LateReasonRequired,
    SupportCaseTransitionService,
)

TZ = "America/Sao_Paulo"
SETTINGS = SimpleNamespace(
    support_sla_minutes_urgent=60,
    support_sla_minutes_high=120,
    support_sla_minutes_normal=480,
    support_sla_minutes_low=1440,
    domains_path=Path("domains"),
)
OPENED = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
MAINTENANCE = DomainSla(
    minutes_by_priority={"urgent": 240, "high": 1440, "normal": 2880, "low": 7200},
    basis="Anexo de Niveis de Servico (demo), item 3",
)


def _case(**overrides) -> ReportCase:
    values = dict(
        case_id="case-1",
        domain="concessoes-manutencao",
        channel="web",
        status="closed",
        priority="urgent",
        reason_codes=["risco_seguranca"],
        opened_at=OPENED,
        closed_at=OPENED + timedelta(hours=3),
        sla_minutes=240,
        sla_basis="Anexo de Niveis de Servico (demo), item 3",
        late_reason=None,
        waiting_seconds=0.0,
    )
    values.update(overrides)
    return ReportCase(**values)


def _rows(*cases: ReportCase, db_now: datetime | None = None) -> list[dict[str, str]]:
    rows = build_report_rows(
        cases,
        db_now=db_now or OPENED + timedelta(days=20),
        settings=SETTINGS,
        domain_sla={"concessoes-manutencao": MAINTENANCE},
        timezone_name=TZ,
    )
    return [dict(zip(COLUMNS, row)) for row in rows]


# --------------------------------------------------------------------------- #
# Prazo gravado na abertura
# --------------------------------------------------------------------------- #


def test_migration_020_is_the_contract_and_declares_the_new_columns() -> None:
    migration = Path("migrations") / CONTRACT_MIGRATION
    sql = migration.read_text(encoding="utf-8")
    assert CONTRACT_MIGRATION.startswith("020_")
    assert {"sla_minutes", "sla_basis", "late_reason"} <= REQUIRED_COLUMNS["support_cases"]
    for code in LATE_REASONS:
        assert f"'{code}'" in sql


def test_new_case_freezes_the_domain_policy_for_its_priority() -> None:
    minutes, basis = case_sla_policy(SETTINGS, "concessoes-manutencao", "urgent")
    assert minutes == 240
    assert basis is not None and "demo" in basis.lower()

    minutes, basis = case_sla_policy(SETTINGS, "lgpd-titular", "normal")
    assert minutes == 15 * 24 * 60


def test_policy_lookup_never_blocks_the_ticket() -> None:
    assert case_sla_policy(SimpleNamespace(), "concessoes-manutencao", "urgent") == (None, None)


def test_frozen_policy_wins_over_the_current_domain_sla() -> None:
    changed_later = DomainSla(minutes_by_priority={"urgent": 60}, basis="novo anexo")
    frozen = frozen_case_sla("urgent", 240, "anexo antigo", changed_later)
    assert frozen is not None
    assert resolve_case_sla_policy("urgent", SETTINGS, frozen) == (240, "anexo antigo")

    # Caso aberto antes da migration 020: segue o SLA vigente.
    assert frozen_case_sla("urgent", None, None, changed_later) is changed_later


def test_report_uses_the_frozen_policy_even_if_domain_yaml_changed() -> None:
    [row] = _rows(_case(sla_minutes=480, sla_basis="anexo de quando o caso abriu"))
    assert row["prazo_minutos"] == "480"
    assert row["base_do_prazo"] == "anexo de quando o caso abriu"


def test_legacy_case_without_policy_uses_the_current_domain_sla() -> None:
    [row] = _rows(_case(sla_minutes=None, sla_basis=None))
    assert row["prazo_minutos"] == "240"
    assert "demo" in row["base_do_prazo"].lower()


# --------------------------------------------------------------------------- #
# Resultado contra o prazo
# --------------------------------------------------------------------------- #


def test_outcomes_cover_closed_late_open_and_cancelled() -> None:
    rows = _rows(
        _case(case_id="no-prazo", closed_at=OPENED + timedelta(hours=3)),
        _case(
            case_id="fora",
            closed_at=OPENED + timedelta(hours=6),
            late_reason="aguardando_peca",
        ),
        _case(case_id="aberto-atrasado", status="in_progress", closed_at=None),
        _case(case_id="cancelado", status="cancelled", closed_at=OPENED + timedelta(hours=1)),
        db_now=OPENED + timedelta(hours=5),
    )
    outcome = {row["caso_id"]: row["resultado"] for row in rows}
    assert outcome == {
        "no-prazo": "no_prazo",
        "fora": "fora_do_prazo",
        "aberto-atrasado": "em_aberto_atrasado",
        "cancelado": "cancelado",
    }
    late = next(row for row in rows if row["caso_id"] == "fora")
    assert late["motivo_atraso"] == "aguardando_peca"


def test_pause_waiting_for_the_citizen_moves_the_deadline() -> None:
    [row] = _rows(
        _case(closed_at=OPENED + timedelta(hours=5), waiting_seconds=2 * 3600),
    )
    assert row["resultado"] == "no_prazo"
    assert row["pausado_minutos"] == "120"
    # 12:00 UTC + 4h de prazo + 2h pausado = 18:00 UTC = 15:00 em Sao Paulo.
    assert row["prazo_em"] == "2026-11-10 15:00"


def test_times_are_in_the_console_timezone() -> None:
    [row] = _rows(_case())
    assert row["aberto_em"] == "2026-11-10 09:00"
    assert row["fechado_em"] == "2026-11-10 12:00"


def test_month_bounds_follow_the_console_timezone() -> None:
    start, end = month_bounds("2026-11", TZ)
    assert start.isoformat() == "2026-11-01T00:00:00-03:00"
    assert end.isoformat() == "2026-12-01T00:00:00-03:00"
    start, end = month_bounds("2026-12", TZ)
    assert end.year == 2027 and end.month == 1


@pytest.mark.parametrize("month", ["2026-13", "26-11", "2026-1", "", "2026-11-01"])
def test_month_bounds_reject_malformed_months(month: str) -> None:
    with pytest.raises(InvalidMonth):
        month_bounds(month, TZ)


# --------------------------------------------------------------------------- #
# CSV sem dado pessoal
# --------------------------------------------------------------------------- #


def test_csv_has_no_personal_data_columns() -> None:
    forbidden = {"telefone", "phone", "email", "nome", "name", "resumo", "summary", "request_id", "cpf"}
    assert not {column.lower() for column in COLUMNS} & forbidden


def test_csv_is_excel_ptbr_friendly() -> None:
    body = render_csv(build_report_rows([_case()], db_now=OPENED, settings=SETTINGS,
                                        domain_sla={}, timezone_name=TZ))
    assert body.startswith("﻿")
    reader = csv.reader(io.StringIO(body.lstrip("﻿")), delimiter=";")
    header, first = next(reader), next(reader)
    assert tuple(header) == COLUMNS
    assert first[0] == "case-1"


def test_csv_neutralizes_formula_injection() -> None:
    body = render_csv([["=HYPERLINK(\"x\")", "+1", "-2", "@x", "ok"] + [""] * (len(COLUMNS) - 5)])
    reader = csv.reader(io.StringIO(body.lstrip("﻿")), delimiter=";")
    next(reader)
    row = next(reader)
    assert row[:5] == ["'=HYPERLINK(\"x\")", "'+1", "'-2", "'@x", "ok"]


# --------------------------------------------------------------------------- #
# Motivo obrigatorio ao fechar atrasado
# --------------------------------------------------------------------------- #


class _Cursor:
    def __init__(self, case_row: tuple, waiting_events: list | None = None) -> None:
        self._case_row = case_row
        self._waiting_events = waiting_events or []
        self.rowcount = 1
        self.executed: list[tuple[str, tuple]] = []
        self._last = ""

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._last = " ".join(sql.split())
        self.executed.append((self._last, params))

    def fetchone(self):
        if self._last.startswith("SELECT status, assignee_staff_id"):
            return self._case_row
        if self._last.startswith("SELECT display_name"):
            return ("Atendente Demo 1",)
        return None

    def fetchall(self):
        if "FROM support_case_events" in self._last:
            return self._waiting_events
        return []


class _Runtime:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.settings = SimpleNamespace(**vars(SETTINGS), support_wa_enc_key=None)

    def transaction(self):
        cursor = self._cursor

        class _Tx:
            def __enter__(self):
                return SimpleNamespace(cursor=lambda: cursor)

            def __exit__(self, *exc):
                return False

        return _Tx()


def _in_progress_row(*, hours_since_opening: float, sla_minutes: int | None = 240) -> tuple:
    now = OPENED + timedelta(hours=hours_since_opening)
    return (
        "in_progress",
        "staff-1",
        "urgent",
        OPENED,
        sla_minutes,
        "Anexo (demo)",
        "concessoes-manutencao",
        now,
    )


def _close(cursor: _Cursor, late_reason: str | None = None):
    return SupportCaseTransitionService(_Runtime(cursor)).apply(
        case_id="case-1",
        action="close",
        actor_staff_id="staff-1",
        note=None,
        late_reason=late_reason,
    )


def _late_reason_written(cursor: _Cursor) -> object:
    update = next(params for sql, params in cursor.executed if sql.startswith("UPDATE support_cases"))
    return update[1]


def test_closing_late_without_a_reason_is_refused() -> None:
    with pytest.raises(LateReasonRequired):
        _close(_Cursor(_in_progress_row(hours_since_opening=5)))


def test_closing_late_with_a_reason_stores_it() -> None:
    cursor = _Cursor(_in_progress_row(hours_since_opening=5))
    result = _close(cursor, late_reason="dependencia_externa")
    assert result.to_status == "closed"
    assert result.late_reason == "dependencia_externa"
    assert _late_reason_written(cursor) == "dependencia_externa"


def test_closing_on_time_needs_no_reason_and_refuses_one() -> None:
    cursor = _Cursor(_in_progress_row(hours_since_opening=3))
    assert _close(cursor).late_reason is None
    assert _late_reason_written(cursor) is None
    with pytest.raises(LateReasonNotApplicable):
        _close(_Cursor(_in_progress_row(hours_since_opening=3)), late_reason="outro")


def test_pause_counts_before_deciding_the_case_is_late() -> None:
    # 5h desde a abertura, 2h aguardando o cidadao: 3h ativas, dentro das 4h.
    events = [
        ("case-1", "wait_customer", OPENED + timedelta(hours=1)),
        ("case-1", "resume", OPENED + timedelta(hours=3)),
    ]
    cursor = _Cursor(_in_progress_row(hours_since_opening=5), waiting_events=events)
    assert _close(cursor).late_reason is None


def test_late_reason_is_only_for_close() -> None:
    with pytest.raises(LateReasonNotApplicable):
        SupportCaseTransitionService(_Runtime(_Cursor(_in_progress_row(hours_since_opening=1)))).apply(
            case_id="case-1", action="cancel", actor_staff_id="staff-1", note=None,
            late_reason="outro",
        )


def test_unknown_late_reason_is_rejected() -> None:
    with pytest.raises(ValueError):
        _close(_Cursor(_in_progress_row(hours_since_opening=5)), late_reason="texto livre")
