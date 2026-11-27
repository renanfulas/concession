# AI system card — concession

Inventory-style record: what the system does, who owns it, which personal data
it processes and on what legal basis, how critical it is, which controls exist
and which limits are known. Portuguese version:
[ficha-do-sistema.md](ficha-do-sistema.md).

> Demo environment. Owners, legal bases and deadlines below show how the card
> would be filled in a real operation; the contract, assets and privacy notice
> the system uses are fictitious.

## Identification

| Field | Value |
| --- | --- |
| Name | concession (maintenance and privacy service desk) |
| Type | RAG assistant with human handoff; never takes the final decision |
| Business area | Maintenance operations; Data Protection Officer (DPO) |
| Technical owner | IT (AI development) |
| Business owner | Operations (maintenance domain) and DPO (LGPD domain) |
| Model provider | OpenAI (`gpt-4o-mini`) or Anthropic, configurable per domain; `text-embedding-3-small` embeddings |
| Hosting | Python API (FastAPI) + PostgreSQL/pgvector on own infrastructure |
| Channels | WhatsApp (Meta Cloud API, off by default) and web chat |
| Status | demo; no production use |

## Scope

Does:

- answers recurring questions from versioned knowledge, citing the source
- classifies each request with rules declared in the domain and opens a prioritized case
- applies the domain's deadline (concession contract or LGPD) to the team console SLA

Does not:

- execute deletion, correction or export of personal data
- decide on fines, penalties or contract interpretation
- identify people, use images or face recognition
- close a case without a staff member

## Personal data

| Data | Where | Handling | Legal basis (LGPD art. 7) |
| --- | --- | --- | --- |
| Phone number | channel identity, OTP | stored as HMAC hash and last 4 digits; full number only when the citizen authorizes contact | public service contract execution; legitimate interest |
| Message text | conversations and tickets | masked before persistence (card, CNPJ, e-mail, phone, IP); `app/core/persistence_sanitize.py` | same |
| Session identifier | short history | only the hash reaches database and logs | same |
| OTP code | identity verification | digest only; expires | legal obligation (serving the data subject safely) |
| Asset code and address | maintenance ticket | operational, not personal | — |

Sensitive data (art. 11) is not collected. Children's data is not collected on purpose.

International transfer: the masked question and retrieved context are sent to
the LLM provider. A real deployment needs contractual clauses with the vendor
and an inventory entry (art. 33).

## Criticality

| Dimension | Rating | Why |
| --- | --- | --- |
| Wrong answer impact | medium | could state a wrong deadline; mitigated because the console deadline comes from `domain.yaml`, not from LLM text |
| Wrong classification impact | medium-high | tagging a safety risk as cleaning delays response; mitigated by evals with `required_handoff_reasons` and mandatory human handling |
| Personal data | low-medium | phone and free text, masked before persistence |
| Autonomy | low | every request that needs action becomes a case for a person |
| Public exposure | high | open citizen channel; rate limiting, confinement and safe fallback |

Suggested rating: **medium risk**, mandatory human review.

## Controls

| Control | Where | Evidence |
| --- | --- | --- |
| Scope, prompt and secret confinement | `docs/security/llm-confinement.md`, `domains/*/evals/confinement/` | confinement evals 33/33 |
| Tested classification | `domains/*/evals/cases.yaml` (`required_handoff_reasons`) | base evals 20/20 across both domains |
| Deterministic deadline | `domain.yaml` `sla` block, `app/support/sla.py` | `tests/test_support_sla.py`, `tests/test_concessoes_domain.py` |
| Fixed safety guidance | `escalation_rules[].notice` in `domain.yaml`, applied in `ChatFlowService.answer` | `tests/test_rule_notices.py`; evals require "ligue 193" and "nunca pede senha" even without an LLM |
| Masking before persistence | `app/core/persistence_sanitize.py` | `tests/test_pii_card.py`, `tests/test_privacy.py` |
| Logs without PII, tokens or raw `session_id` | `app/core/logging.py`, `docs/architecture/observability.md` | `tests/test_observability_hardening.py` |
| Consent before direct contact | consent gate on tickets | web handoff tests |
| Traceability | `request_id` on every response; audited case events | `tests/test_request_observability.py` |
| Safe fallback | provider or retrieval failure -> standard answer and handoff | `tests/test_chat_flow_errors.py` |
| AI-assisted development | `CLAUDE.md`, `.agents/skills/`, co-author trailer, tests and evals before commit | commit history |

## Known limits

- Without an LLM key, evals check retrieval, classification and handoff, not generated text quality.
- Term-based (substring) classification: unforeseen synonyms fall into `low_confidence` and go to a person; safe, but it can grow the queue.
- No dedicated CPF detector with check digits.
- Writing the case priority to a real PostgreSQL was not verified in this copy.
- No web UI for the console; the console is an API.

## Review log

| Date | Who | What |
| --- | --- | --- |
| 2026-11-26 | IT (AI development) | first version |
