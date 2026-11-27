"""Politica do intake: criticidade por regra e prazo da analise.

Deterministico de proposito, como as ``escalation_rules`` dos dominios: o
nivel de risco de uma solucao nao pode depender de um modelo estar disponivel
nem mudar entre duas execucoes. A politica vem de um YAML versionado
(``governance/ai-intake.yaml``), marcado como demonstracao.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai_intake.models import (
    CRITICALITY_LEVELS,
    DATA_CATEGORIES,
    HOSTING_REGIONS,
    CriticalityAssessment,
    SolutionSubmission,
)

DEFAULT_POLICY_PATH = Path("governance") / "ai-intake.yaml"
# Criticidade -> prioridade que o motor de SLA ja entende (app/support/sla.py).
LEVEL_TO_PRIORITY = {"baixa": "low", "media": "normal", "alta": "high"}
_RANK = {level: index for index, level in enumerate(CRITICALITY_LEVELS)}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleCondition(_Strict):
    data_categories_any: tuple[str, ...] | None = None
    automated_decision: bool | None = None
    external_facing: bool | None = None
    human_in_loop: bool | None = None
    hosting_region_in: tuple[str, ...] | None = None
    hosting_region_not_in: tuple[str, ...] | None = None

    @field_validator("data_categories_any")
    @classmethod
    def _known_categories(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        unknown = set(value or ()) - set(DATA_CATEGORIES)
        if unknown:
            raise ValueError(f"unknown data category: {sorted(unknown)}")
        return value

    @field_validator("hosting_region_in", "hosting_region_not_in")
    @classmethod
    def _known_regions(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        unknown = set(value or ()) - set(HOSTING_REGIONS)
        if unknown:
            raise ValueError(f"unknown hosting region: {sorted(unknown)}")
        return value

    @model_validator(mode="after")
    def _not_empty(self) -> "RuleCondition":
        if not self.model_dump(exclude_none=True):
            raise ValueError("a rule needs at least one condition")
        return self

    def matches(self, submission: SolutionSubmission) -> bool:
        categories = set(submission.data_categories)
        checks = [
            self.data_categories_any is None
            or bool(categories & set(self.data_categories_any)),
            self.automated_decision is None
            or submission.automated_decision is self.automated_decision,
            self.external_facing is None
            or submission.external_facing is self.external_facing,
            self.human_in_loop is None
            or submission.human_in_loop is self.human_in_loop,
            self.hosting_region_in is None
            or submission.hosting_region in self.hosting_region_in,
            self.hosting_region_not_in is None
            or submission.hosting_region not in self.hosting_region_not_in,
        ]
        return all(checks)


class CriticalityRule(_Strict):
    id: str
    level: str
    reason: str
    when: RuleCondition

    @field_validator("level")
    @classmethod
    def _known_level(cls, value: str) -> str:
        if value not in CRITICALITY_LEVELS:
            raise ValueError(f"unknown criticality level: {value}")
        return value


class IntakePolicy(_Strict):
    version: int
    basis: str
    default_level: str = "baixa"
    sla_days: dict[str, int]
    ripd_required_for: tuple[str, ...] = ()
    rules: tuple[CriticalityRule, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _complete(self) -> "IntakePolicy":
        if self.default_level not in CRITICALITY_LEVELS:
            raise ValueError(f"unknown default_level: {self.default_level}")
        missing = set(CRITICALITY_LEVELS) - set(self.sla_days)
        if missing:
            raise ValueError(f"sla_days missing levels: {sorted(missing)}")
        if any(days <= 0 for days in self.sla_days.values()):
            raise ValueError("sla_days must be positive")
        unknown = set(self.ripd_required_for) - set(CRITICALITY_LEVELS)
        if unknown:
            raise ValueError(f"unknown ripd_required_for level: {sorted(unknown)}")
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        return self

    def assess(self, submission: SolutionSubmission) -> CriticalityAssessment:
        matched = [rule for rule in self.rules if rule.when.matches(submission)]
        level = self.default_level
        for rule in matched:
            if _RANK[rule.level] > _RANK[level]:
                level = rule.level
        # Highest level first, then file order, so the ficha reads by severity.
        ordered = sorted(matched, key=lambda rule: -_RANK[rule.level])
        return CriticalityAssessment(
            level=level,
            reasons=tuple(rule.id for rule in ordered),
            ripd_required=level in self.ripd_required_for,
        )

    def reason_text(self, rule_id: str) -> str:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule.reason
        return rule_id

    def sla_minutes(self, level: str) -> int:
        return self.sla_days[level] * 24 * 60


def load_policy(path: Path | str = DEFAULT_POLICY_PATH) -> IntakePolicy:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("ai intake policy must be a mapping")
    return IntakePolicy.model_validate(raw)
