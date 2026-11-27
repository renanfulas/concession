"""CPF detection and the audit-safe exemptions of the phone rule.

Every CPF here is fictitious: built from a sequential base with check digits
computed by ``_with_check_digits``. Phone numbers use the 98765-4321 /
3456-7890 placeholders. No value belongs to a real person.
"""

from __future__ import annotations

import pytest

from app.core.persistence_sanitize import (
    READABLE_REDACTION_VERSIONS,
    REDACTED_CARD,
    REDACTED_CPF,
    REDACTED_SECRET,
    REDACTION_VERSION,
    _is_cpf,
    _luhn_valid,
    sanitize_for_persistence,
    sanitize_payload,
)
from app.support.transcript import (
    count_conversation_turns,
    fetch_conversation_transcript,
)


PHONE = "[REDACTED_PHONE]"


def _with_check_digits(base: str) -> str:
    nums = [int(c) for c in base]
    for weight_start in (10, 11):
        total = sum(n * (weight_start - i) for i, n in enumerate(nums))
        nums.append((total * 10) % 11 % 10)
    return "".join(str(n) for n in nums)


def _mask(digits: str) -> str:
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


CPF_A = _with_check_digits("123456789")  # 12345678909
CPF_B = _with_check_digits("987654321")
CPF_A_WRONG_DV = CPF_A[:9] + ("00" if CPF_A[9:] != "00" else "11")


def _clean(text: str) -> str:
    result = sanitize_for_persistence(text)
    assert result is not None
    return result


def test_fixture_cpfs_are_valid_and_wrong_dv_is_not() -> None:
    assert _is_cpf(CPF_A)
    assert _is_cpf(CPF_B)
    assert not _is_cpf(CPF_A_WRONG_DV)
    assert not _is_cpf("11111111111")
    assert not _is_cpf("1234567890")


# --- CPF -------------------------------------------------------------------


def test_formatted_valid_cpf_is_redacted_as_cpf() -> None:
    out = _clean(f"meu CPF e {_mask(CPF_A)}, obrigado")
    assert out == f"meu CPF e {REDACTED_CPF}, obrigado"


def test_raw_valid_cpf_is_redacted_as_cpf() -> None:
    out = _clean(f"cpf {CPF_A}")
    assert out == f"cpf {REDACTED_CPF}"


def test_formatted_cpf_with_wrong_check_digit_is_still_redacted() -> None:
    # A mistyped CPF is still a person's number: the mask alone is enough.
    out = _clean(f"CPF: {_mask(CPF_A_WRONG_DV)}")
    assert out == f"CPF: {REDACTED_CPF}"


def test_cpf_without_dots_but_with_dash_is_redacted() -> None:
    out = _clean(f"documento {CPF_A[:9]}-{CPF_A[9:]}")
    assert out == f"documento {REDACTED_CPF}"


def test_raw_eleven_digits_with_wrong_check_digit_is_not_cpf_but_is_masked() -> None:
    out = _clean(f"numero {CPF_A_WRONG_DV}")
    assert REDACTED_CPF not in out
    assert CPF_A_WRONG_DV not in out
    assert PHONE in out


def test_repeated_digit_cpf_is_masked_only_when_formatted() -> None:
    assert _clean("cpf 111.111.111-11") == f"cpf {REDACTED_CPF}"
    raw = _clean("cpf 11111111111")
    assert REDACTED_CPF not in raw
    assert "11111111111" not in raw


@pytest.mark.parametrize(
    "template",
    ["CPF{cpf}", "id_{cpf}", "https://x.test/consulta?cpf={cpf}", "cpf:{cpf}."],
)
def test_cpf_glued_to_letters_or_inside_url_is_redacted(template: str) -> None:
    out = _clean(template.format(cpf=CPF_A))
    assert CPF_A not in out
    assert REDACTED_CPF in out


def test_cpf_glued_to_more_digits_is_not_a_cpf() -> None:
    out = _clean(f"codigo {CPF_A}7")
    assert REDACTED_CPF not in out
    assert CPF_A not in out  # the broad digit rule still masks the run


def test_multiple_cpfs_in_one_sentence() -> None:
    out = _clean(f"titular {_mask(CPF_A)} e dependente {CPF_B}.")
    assert out == f"titular {REDACTED_CPF} e dependente {REDACTED_CPF}."


def test_cnpj_is_not_relabeled_as_cpf() -> None:
    out = _clean("empresa 11.222.333/0001-81")
    assert REDACTED_CPF not in out


def test_cpf_inside_nested_payload() -> None:
    payload = {"turns": [{"text": f"cpf {_mask(CPF_B)}"}], "count": 1}
    sanitized = sanitize_payload(payload)
    assert sanitized == {"turns": [{"text": f"cpf {REDACTED_CPF}"}], "count": 1}


def test_cpf_after_protocol_label_is_still_redacted() -> None:
    assert _clean(f"protocolo {_mask(CPF_A)}") == f"protocolo {REDACTED_CPF}"
    assert _clean(f"protocolo {CPF_A}") == f"protocolo {REDACTED_CPF}"


# --- phone rule keeps masking ----------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "tel (11) 98765-4321",
        "+55 11 98765-4321",
        "11987654321",
        "fixo 3456-7890 ramal",
        "rg 12.345.678-9",
    ],
)
def test_phone_and_other_digit_runs_stay_masked(text: str) -> None:
    out = _clean(text)
    assert PHONE in out
    assert "98765" not in out and "4321" not in out
    assert "345.678" not in out and "3456-7890" not in out


# --- ISO dates are audit data ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "defeito desde 2024-03-01",
        "registrado em 2024-03-01 10:15",
        "registrado em 2024-03-01T10:15:00-03:00",
        "registrado em 2024-03-01T10:15:00.123Z.",
    ],
)
def test_iso_dates_are_preserved(text: str) -> None:
    assert _clean(text) == text


def test_date_next_to_phone_keeps_date_and_masks_phone() -> None:
    out = _clean("em 2024-03-01 11 98765-4321")
    assert out.startswith("em 2024-03-01 ")
    assert "98765" not in out
    assert PHONE in out


@pytest.mark.parametrize(
    "text",
    ["data 2024-13-45", "data 2024-02-30", "num 2024-03-0112345678"],
)
def test_invalid_or_glued_dates_are_not_shielded(text: str) -> None:
    out = _clean(text)
    digits_only = text.split(" ", 1)[1]
    assert digits_only not in out
    assert PHONE in out or REDACTED_CARD in out


def test_secret_that_looks_like_a_date_is_still_a_secret() -> None:
    out = _clean("senha: 2024-03-01")
    assert "2024-03-01" not in out
    assert REDACTED_SECRET in out


# --- labeled protocols are audit data ----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "protocolo 2026112612345",
        "Protocolo nº 2026112612345",
        "protocolo: 2026112612345",
        "chamado #2026112612345",
        "ticket 2026112612345678",
        "OS 2026112612345",
        "ordem de servico 2026112612345",
    ],
)
def test_labeled_protocol_is_preserved(text: str) -> None:
    assert _clean(text) == text


def test_protocol_and_phone_in_same_sentence() -> None:
    out = _clean("chamado 2026112612345 tel 11 98765-4321")
    assert out == f"chamado 2026112612345 tel {PHONE}"


def test_unlabeled_protocol_is_still_masked() -> None:
    # Documented limit: without a label a long number is treated as personal.
    out = _clean("o numero 2026112612345 nao chegou")
    assert "2026112612345" not in out


@pytest.mark.parametrize(
    "text",
    [
        "protocolo 11987654321",  # 11 digits: could be a mobile with DDD
        "protocolo 98765-4321",
        "protocolo 551187654321",  # +55 landline without the plus (12 digits)
        "protocolo 5511987654321",  # +55 mobile without the plus
        "chamado #11987654321",
        "liguei para os 11987654321",  # lowercase "os" is the article
        "os 2026112612345",
    ],
)
def test_phone_after_protocol_label_is_not_shielded(text: str) -> None:
    out = _clean(text)
    assert PHONE in out or REDACTED_CPF in out
    assert "98765" not in out and "8765432" not in out and "2612345" not in out


@pytest.mark.parametrize(
    "text",
    ["protocolo 4111111111111111", "chamado #4111111111111111", "protocolo 4111 1111 1111 1111"],
)
def test_card_after_protocol_label_is_still_a_card(text: str) -> None:
    out = _clean(text)
    assert REDACTED_CARD in out
    assert "4111" not in out


def test_labeled_protocol_passing_luhn_is_masked_as_card() -> None:
    # Accepted limit: a 13-19 digit protocol that passes Luhn is treated as a
    # card. Privacy wins over the audit trail when the two collide.
    number = next(
        f"2026112612{suffix:03d}"
        for suffix in range(1000)
        if _luhn_valid(f"2026112612{suffix:03d}")
    )
    assert _clean(f"protocolo {number}") == f"protocolo {REDACTED_CARD}"


def test_sanitizer_is_idempotent_with_new_rules() -> None:
    text = (
        f"cpf {_mask(CPF_A)}, protocolo 2026112612345 em 2024-03-01 10:15, "
        "tel (11) 98765-4321"
    )
    once = _clean(text)
    assert _clean(once) == once
    assert "protocolo 2026112612345 em 2024-03-01 10:15" in once


# --- redaction version --------------------------------------------------------


class _ScriptedCursor:
    def __init__(self, result: list | tuple) -> None:
        self.result = result
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple) -> None:
        self.calls.append((sql, params))

    def fetchall(self) -> list:
        return list(self.result)

    def fetchone(self) -> tuple:
        return tuple(self.result)


def test_current_version_is_readable_and_v1_rows_stay_visible() -> None:
    assert REDACTION_VERSION in READABLE_REDACTION_VERSIONS
    assert "phase0-v1" in READABLE_REDACTION_VERSIONS
    assert "legacy-unverified" not in READABLE_REDACTION_VERSIONS


def test_transcript_queries_filter_by_readable_versions() -> None:
    cursor = _ScriptedCursor([])
    fetch_conversation_transcript(cursor, "conv-ficticia", limit=5)
    sql, params = cursor.calls[0]
    assert "redaction_version = ANY(%s)" in sql
    assert list(READABLE_REDACTION_VERSIONS) in params

    counter = _ScriptedCursor((0,))
    count_conversation_turns(counter, "conv-ficticia")
    sql, params = counter.calls[0]
    assert "redaction_version = ANY(%s)" in sql
    assert list(READABLE_REDACTION_VERSIONS) in params
