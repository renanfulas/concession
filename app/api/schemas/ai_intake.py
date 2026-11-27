"""Contratos HTTP do intake de solucoes de IA (/web/support/intake/*).

As listas fechadas nao se repetem aqui: o servico valida contra
``app.ai_intake.models`` e ``GET /options`` devolve as opcoes para a tela.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SolutionSubmitRequest(_Request):
    name: str = Field(max_length=200)
    business_unit: str = Field(max_length=200)
    purpose: str = Field(max_length=4000)
    owner_name: str = Field(max_length=200)
    owner_role: str = Field(max_length=200)
    solution_type: str = Field(max_length=40)
    hosting_region: str = Field(max_length=40)
    data_categories: list[str] = Field(max_length=10)
    data_subjects: list[str] = Field(default_factory=list, max_length=10)
    legal_basis: str = Field(max_length=40)
    automated_decision: bool
    external_facing: bool
    human_in_loop: bool
    vendor: str | None = Field(default=None, max_length=200)
    model_provider: str | None = Field(default=None, max_length=200)
    model_name: str | None = Field(default=None, max_length=200)


class SolutionTransitionRequest(_Request):
    action: str = Field(max_length=40)
    note: str | None = Field(default=None, max_length=1000)
    conditions: str | None = Field(default=None, max_length=1000)
    rejection_reason: str | None = Field(default=None, max_length=40)
    ripd_reference: str | None = Field(default=None, max_length=120)


class IntakeSlaResponse(BaseModel):
    deadline_at: datetime
    color: str
    paused: bool
    elapsed_ratio: float
    paused_minutes: int
    basis: str


class CriticalityReasonResponse(BaseModel):
    id: str
    text: str


class SolutionEventResponse(BaseModel):
    action: str
    from_status: str | None
    to_status: str
    actor_display_name: str
    note: str | None
    created_at: datetime


class SolutionResponse(BaseModel):
    id: str
    reference: str
    name: str
    business_unit: str
    purpose: str
    owner_name: str
    owner_role: str
    solution_type: str
    vendor: str | None
    model_provider: str | None
    model_name: str | None
    hosting_region: str
    data_categories: list[str]
    data_subjects: list[str]
    legal_basis: str
    automated_decision: bool
    external_facing: bool
    human_in_loop: bool
    criticality: str
    criticality_reasons: list[CriticalityReasonResponse]
    ripd_required: bool
    status: str
    submitted_by_name: str
    submitted_by_me: bool
    reviewer_name: str | None
    reviewing_by_me: bool
    submitted_at: datetime
    decided_at: datetime | None
    decision_note: str | None
    conditions: str | None
    rejection_reason: str | None
    ripd_reference: str | None
    outcome: str
    sla: IntakeSlaResponse
    events: list[SolutionEventResponse] = Field(default_factory=list)


class SolutionListResponse(BaseModel):
    items: list[SolutionResponse]
    durable: bool


class IntakeRuleResponse(BaseModel):
    id: str
    level: str
    reason: str


class IntakeOptionsResponse(BaseModel):
    solution_types: list[str]
    hosting_regions: list[str]
    data_categories: list[str]
    data_subjects: list[str]
    legal_bases: list[str]
    rejection_reasons: list[str]
    sla_days: dict[str, int]
    ripd_required_for: list[str]
    basis: str
    rules: list[IntakeRuleResponse]
    durable: bool
