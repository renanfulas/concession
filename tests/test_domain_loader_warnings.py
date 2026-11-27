"""A broken domain.yaml is reported, and every shipped domain loads."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.domain_engine.loader import DomainLoader


SHIPPED_DOMAINS = Path("domains")


def _write(root: Path, name: str, body: str) -> None:
    (root / name).mkdir(parents=True)
    (root / name / "domain.yaml").write_text(body, encoding="utf-8")


def _events(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.levelno == logging.WARNING and "domain_config_invalid" in record.getMessage()
    ]


def test_every_shipped_domain_loads() -> None:
    folders = sorted(
        item.name
        for item in SHIPPED_DOMAINS.iterdir()
        if (item / "domain.yaml").exists()
    )
    assert folders, "o repositorio deve ter dominios"
    assert DomainLoader(SHIPPED_DOMAINS).list_domains() == folders


def test_invalid_sla_value_is_reported_without_the_value(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = (SHIPPED_DOMAINS / "lgpd-titular" / "domain.yaml").read_text(encoding="utf-8")
    broken = source.replace("normal_minutes: 21600", "normal_minutes: quinze-dias-demo")
    assert broken != source
    _write(tmp_path, "lgpd-titular", broken)

    with caplog.at_level(logging.WARNING, logger="app.domain_engine.loader"):
        assert DomainLoader(tmp_path).load("lgpd-titular") is None

    [event] = _events(caplog)
    assert event["domain"] == "lgpd-titular"
    assert event["reason"] == "validation_error"
    assert any("normal_minutes" in field for field in event["fields"])
    assert "quinze-dias-demo" not in caplog.text


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("name: [unterminated", "unreadable_yaml"),
        ("- uma\n- lista\n", "not_a_mapping"),
        ("name: outro-nome\n", "name_mismatch"),
    ],
)
def test_other_failures_are_reported(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, body: str, reason: str
) -> None:
    _write(tmp_path, "dominio-quebrado", body)
    with caplog.at_level(logging.WARNING, logger="app.domain_engine.loader"):
        assert DomainLoader(tmp_path).load("dominio-quebrado") is None
    assert [event["reason"] for event in _events(caplog)] == [reason]


def test_missing_domain_is_silent(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.domain_engine.loader"):
        assert DomainLoader(tmp_path).load("nao-existe") is None
    assert _events(caplog) == []
