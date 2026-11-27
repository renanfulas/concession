"""Modelo do intake de solucoes de IA (migration 021).

As listas fechadas aqui sao a fonte unica para a API, o servico e os CHECKs do
banco (``migrations/021_ai_solution_intake.sql``); um teste garante que as duas
pontas nao divergem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

SOLUTION_TYPES = ("interno", "fornecedor", "consultoria", "saas")
HOSTING_REGIONS = ("brasil", "uniao_europeia", "estados_unidos", "outra")
DATA_CATEGORIES = ("nenhum", "pessoal", "sensivel", "biometrico_imagem", "crianca")
# Categorias que contam como dado pessoal para as regras de criticidade.
PERSONAL_DATA_CATEGORIES = ("pessoal", "sensivel", "biometrico_imagem", "crianca")
DATA_SUBJECTS = ("cidadao", "funcionario", "cliente_anunciante", "fornecedor")
LEGAL_BASES = (
    "nao_se_aplica",
    "consentimento",
    "obrigacao_legal",
    "execucao_contrato",
    "legitimo_interesse",
    "politica_publica",
    "a_definir",
)
CRITICALITY_LEVELS = ("baixa", "media", "alta")
STATUSES = (
    "submitted",
    "in_review",
    "needs_info",
    "approved",
    "approved_conditional",
    "rejected",
    "withdrawn",
)
FINAL_STATUSES = frozenset({"approved", "approved_conditional", "rejected", "withdrawn"})
REJECTION_REASONS = (
    "risco_sem_mitigacao",
    "base_legal_inadequada",
    "duplica_solucao_existente",
    "custo_desproporcional",
    "fora_da_estrategia",
    "outro",
)


@dataclass(frozen=True)
class SolutionSubmission:
    """What a business unit declares. Free text arrives already masked."""

    name: str
    business_unit: str
    purpose: str
    owner_name: str
    owner_role: str
    solution_type: str
    hosting_region: str
    data_categories: tuple[str, ...]
    legal_basis: str
    automated_decision: bool
    external_facing: bool
    human_in_loop: bool
    data_subjects: tuple[str, ...] = ()
    vendor: str | None = None
    model_provider: str | None = None
    model_name: str | None = None


@dataclass(frozen=True)
class CriticalityAssessment:
    level: str
    reasons: tuple[str, ...]
    ripd_required: bool


@dataclass(frozen=True)
class SolutionEvent:
    action: str
    from_status: str | None
    to_status: str
    actor_staff_id: str
    actor_display_name: str
    note: str | None
    created_at: datetime


@dataclass(frozen=True)
class SolutionRecord:
    id: str
    reference: str
    submission: SolutionSubmission
    criticality: str
    criticality_reasons: tuple[str, ...]
    ripd_required: bool
    status: str
    sla_minutes: int
    sla_basis: str
    submitted_by: str
    submitted_by_name: str
    submitted_at: datetime
    updated_at: datetime
    reviewer_staff_id: str | None = None
    reviewer_name: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    conditions: str | None = None
    rejection_reason: str | None = None
    ripd_reference: str | None = None
    events: tuple[SolutionEvent, ...] = field(default_factory=tuple)
