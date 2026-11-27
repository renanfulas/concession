"""SLA policy frozen into a support case when it opens (migration 020).

Lives in the support layer so every channel that opens a case (web, WhatsApp,
Hermes, the demo seed) gets the same policy through
``OperationalRepository``, with no caller able to forget it.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.logging import log_event
from app.domain_engine.loader import DomainLoader
from app.support.sla import domain_sla_overrides, resolve_case_sla_policy


logger = logging.getLogger(__name__)


def case_sla_policy(settings: Any, domain_name: str, priority: str) -> tuple[int | None, str | None]:
    """Minutes and basis for a case opening now, from ``domain.yaml`` or the global SLA.

    Returns ``(None, None)`` when the policy cannot be resolved: the case is
    still created and the console falls back to the SLA in force, same as a
    case opened before migration 020.
    """

    try:
        loader = DomainLoader(settings.domains_path)
        config = loader.load(domain_name)
        overrides = domain_sla_overrides([config] if config is not None else [])
        minutes, basis = resolve_case_sla_policy(priority, settings, overrides.get(domain_name))
    except Exception as exc:  # noqa: BLE001 - never block the ticket on SLA lookup
        log_event(
            logger,
            "support_case_sla_policy_unavailable",
            error_type=type(exc).__name__,
        )
        return None, None
    return minutes, basis or None
