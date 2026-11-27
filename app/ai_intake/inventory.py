"""Inventario de solucoes de IA: CSV para a governanca e ficha por solucao.

O CSV segue o formato do relatorio mensal (``;`` e BOM para o Excel pt-BR,
celulas que comecam com ``=``/``+``/``-``/``@`` neutralizadas). A ficha usa as
secoes de ``docs/ficha-do-sistema.md``: responsavel, dados tratados, base
legal, criticidade e limites, para o inventario ter o mesmo formato da ficha
deste proprio sistema.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from app.ai_intake.policy import IntakePolicy
from app.ai_intake.service import SolutionView
from app.support.monthly_report import CSV_BOM, CSV_DELIMITER, neutralize_formula

INVENTORY_COLUMNS = (
    "referencia",
    "nome",
    "unidade",
    "responsavel",
    "papel_do_responsavel",
    "tipo",
    "fornecedor",
    "provedor_do_modelo",
    "modelo",
    "hospedagem",
    "dados_tratados",
    "titulares",
    "base_legal",
    "decisao_automatizada",
    "uso_externo",
    "revisao_humana",
    "criticidade",
    "motivos",
    "ripd_exigido",
    "ripd",
    "status",
    "submetido_em",
    "prazo_em",
    "base_do_prazo",
    "decidido_em",
    "resultado",
    "condicoes",
    "motivo_rejeicao",
)

STATUS_LABELS = {
    "submitted": "submetido",
    "in_review": "em analise",
    "needs_info": "aguardando informacao",
    "approved": "aprovado",
    "approved_conditional": "aprovado com condicoes",
    "rejected": "rejeitado",
    "withdrawn": "retirado",
}


def inventory_rows(views: Iterable[SolutionView], timezone_name: str) -> list[list[str]]:
    zone = ZoneInfo(timezone_name)
    rows: list[list[str]] = []
    for view in sorted(views, key=lambda item: item.record.reference):
        record, submission = view.record, view.record.submission
        rows.append(
            [
                record.reference,
                submission.name,
                submission.business_unit,
                submission.owner_name,
                submission.owner_role,
                submission.solution_type,
                submission.vendor or "",
                submission.model_provider or "",
                submission.model_name or "",
                submission.hosting_region,
                ",".join(submission.data_categories),
                ",".join(submission.data_subjects),
                submission.legal_basis,
                _yes(submission.automated_decision),
                _yes(submission.external_facing),
                _yes(submission.human_in_loop),
                record.criticality,
                ",".join(record.criticality_reasons),
                _yes(record.ripd_required),
                record.ripd_reference or "",
                record.status,
                _local(record.submitted_at, zone),
                _local(view.sla.deadline_at, zone),
                record.sla_basis,
                _local(record.decided_at, zone),
                view.outcome,
                record.conditions or "",
                record.rejection_reason or "",
            ]
        )
    return rows


def render_inventory_csv(rows: Iterable[list[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\r\n")
    writer.writerow(INVENTORY_COLUMNS)
    for row in rows:
        writer.writerow([neutralize_formula(cell) for cell in row])
    return CSV_BOM + buffer.getvalue()


def render_ficha(view: SolutionView, policy: IntakePolicy, timezone_name: str) -> str:
    """Markdown ficha of one solution, in the format of docs/ficha-do-sistema.md."""

    zone = ZoneInfo(timezone_name)
    record, submission = view.record, view.record.submission
    reasons = [f"- {policy.reason_text(rule_id)} (`{rule_id}`)" for rule_id in record.criticality_reasons]
    events = [
        f"| {_local(event.created_at, zone)} | {event.action} | "
        f"{event.from_status or '-'} -> {event.to_status} | {_cell(event.actor_display_name)} | "
        f"{_cell(event.note or '')} |"
        for event in record.events
    ]
    decision = [
        f"- Status: {STATUS_LABELS.get(record.status, record.status)}",
        f"- Resultado contra o prazo: {view.outcome}",
    ]
    if record.decided_at is not None:
        decision.append(f"- Decidido em: {_local(record.decided_at, zone)}")
    if record.decision_note:
        decision.append(f"- Nota da decisao: {record.decision_note}")
    if record.conditions:
        decision.append(f"- Condicoes: {record.conditions}")
    if record.rejection_reason:
        decision.append(f"- Motivo da rejeicao: `{record.rejection_reason}`")
    if record.ripd_reference:
        decision.append(f"- RIPD: {record.ripd_reference}")

    lines = [
        f"# Ficha da solucao {record.reference}: {submission.name}",
        "",
        "> Gerada pelo intake de solucoes de IA (demonstracao). Politica de "
        "criticidade e prazos ficticios.",
        "",
        "## Identificacao",
        "",
        "| Campo | Valor |",
        "| --- | --- |",
        f"| Unidade de negocio | {_cell(submission.business_unit)} |",
        f"| Responsavel | {_cell(submission.owner_name)} ({_cell(submission.owner_role)}) |",
        f"| Finalidade | {_cell(submission.purpose)} |",
        f"| Tipo | {submission.solution_type} |",
        f"| Fornecedor | {_cell(submission.vendor or '-')} |",
        f"| Modelo | {_cell(' / '.join(filter(None, [submission.model_provider, submission.model_name])) or '-')} |",
        f"| Hospedagem | {submission.hosting_region} |",
        "",
        "## Dados tratados e base legal",
        "",
        "| Campo | Valor |",
        "| --- | --- |",
        f"| Categorias de dados | {', '.join(submission.data_categories)} |",
        f"| Titulares | {', '.join(submission.data_subjects) or '-'} |",
        f"| Base legal declarada | {submission.legal_basis} |",
        f"| Decisao automatizada sobre pessoas | {_yes(submission.automated_decision)} |",
        f"| Usada por publico externo | {_yes(submission.external_facing)} |",
        f"| Revisao humana | {_yes(submission.human_in_loop)} |",
        "",
        "## Criticidade",
        "",
        f"**{record.criticality}**. RIPD exigido: {_yes(record.ripd_required)}.",
        "",
        *(reasons or ["- nenhuma regra casou; nivel padrao da politica"]),
        "",
        "## Prazo da analise",
        "",
        f"- Base: {record.sla_basis}",
        f"- Submetido em: {_local(record.submitted_at, zone)}",
        f"- Prazo: {_local(view.sla.deadline_at, zone)} "
        f"(pausado {int(view.paused_seconds // 60)} min aguardando informacao)",
        "",
        "## Decisao",
        "",
        *decision,
        "",
        "## Trilha de auditoria",
        "",
        "| Quando | Acao | Estado | Quem | Nota |",
        "| --- | --- | --- | --- | --- |",
        *events,
        "",
    ]
    return "\n".join(lines)


def _yes(value: bool) -> str:
    return "sim" if value else "nao"


def _local(value: datetime | None, zone: ZoneInfo) -> str:
    if value is None:
        return ""
    return value.astimezone(zone).strftime("%Y-%m-%d %H:%M")


def _cell(text: str) -> str:
    """Keep a value inside one Markdown table cell."""

    return " ".join(str(text).split()).replace("|", "\\|")
