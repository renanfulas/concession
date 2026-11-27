import json
import logging
from pathlib import Path

from pydantic import ValidationError
import yaml

from app.domain_engine.models import DomainConfig


logger = logging.getLogger(__name__)


class DomainLoader:
    def __init__(self, domains_path: Path) -> None:
        self.domains_path = domains_path

    def list_domains(self) -> list[str]:
        if not self.domains_path.exists():
            return []

        return sorted(
            item.name
            for item in self.domains_path.iterdir()
            if item.is_dir() and self.load(item.name) is not None
        )

    def load(self, domain_name: str) -> DomainConfig | None:
        domain_root = self.domains_path / domain_name
        config_path = domain_root / "domain.yaml"
        if not config_path.exists():
            return None

        try:
            with config_path.open("r", encoding="utf-8") as file:
                raw = yaml.safe_load(file) or {}
        except (OSError, yaml.YAMLError) as exc:
            _warn_invalid(domain_name, "unreadable_yaml", error_type=type(exc).__name__)
            return None

        if not isinstance(raw, dict):
            _warn_invalid(domain_name, "not_a_mapping")
            return None

        if raw.get("name") != domain_name:
            _warn_invalid(domain_name, "name_mismatch")
            return None

        raw["root_path"] = domain_root
        try:
            return DomainConfig.model_validate(raw)
        except ValidationError as exc:
            # Only field locations go to the log, never the offending values.
            fields = sorted({".".join(str(part) for part in err["loc"]) for err in exc.errors()})
            _warn_invalid(
                domain_name,
                "validation_error",
                error_count=exc.error_count(),
                fields=fields[:10],
            )
            return None


def _warn_invalid(domain_name: str, reason: str, **fields: object) -> None:
    """A broken domain.yaml must not vanish silently: the domain would drop out
    of routing and its SLA would fall back to the global deadlines."""
    payload = {
        "event": "domain_config_invalid",
        "domain": domain_name,
        "reason": reason,
        **fields,
    }
    logger.warning(json.dumps(payload, ensure_ascii=True, default=str))
