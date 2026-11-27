# AI system card — concession

Inventory-style record: what the system does, who owns it, which personal data
it processes and on what legal basis, how critical it is, which controls exist
and which limits are known. Portuguese version:
[ficha-do-sistema.md](ficha-do-sistema.md).

> Demo environment. Owners, legal bases and deadlines below show how the card
> would be filled in a real operation; the contract, assets and privacy notice
> the system uses are fictitious.

## Identification

> Sample entry (demo). Owners, business area and hosting below show the
> expected format; they do not describe a real organization.

| Field | Value |
| --- | --- |
| Name | concession (maintenance and privacy service desk) |
| Type | RAG assistant with human handoff; never takes the final decision |
| Business area | Maintenance operations; Data Protection Officer (DPO) — sample (demo) |
| Technical owner | IT (AI development) — sample (demo) |
| Business owner | Operations (maintenance domain) and DPO (LGPD domain) — sample (demo) |
| Model provider | OpenAI (`gpt-4o-mini`) or Anthropic, configurable per domain; `text-embedding-3-small` embeddings |
| Hosting | Python API (FastAPI) + PostgreSQL/pgvector; hosting location to be defined — sample (demo) |
| Channels | WhatsApp (Meta Cloud API, off by default) and web chat |
| Status | demo; no production use |

## Scope

Does:

- answers recurring questions from versioned knowledge and returns the retrieved sources (`references`)
- classifies each request with rules declared in the domain and opens a prioritized case
- applies the domain's deadline (concession contract or LGPD) to the team console SLA

Does not:

- execute deletion, correction or export of personal data
- decide on fines, penalties or contract interpretation
- identify people, use images or face recognition
- close a case without a staff member

## Personal data

> The legal bases below are demo reasoning, not legal advice. In a real
> deployment each basis must be confirmed by the DPO and legal counsel. The
> concession contract is signed with the granting authority, not with the
> citizen, so it is not a basis for the citizen's data (art. 7, V).

| Data | Where | Handling | Legal basis (LGPD art. 7) — demo |
| --- | --- | --- | --- |
| Citizen phone number | channel identity, OTP | stored as HMAC hash and last 4 digits; the full number appears in the "`wa_id`" and "destination phone" rows below | legitimate interest (art. 7, IX) or public policy execution (art. 7, III); to be confirmed by the real DPO |
| Message text | conversations and tickets | masked before persistence (CPF with check digits, card, e-mail, phone and other long digit runs, IP); ISO dates and labeled protocol numbers stay readable for the audit trail; `app/core/persistence_sanitize.py`. The same masking applies before the LLM provider (see "International transfer") | same |
| Session identifier | short history | only the hash reaches database and logs | same |
| OTP code | identity verification | digest only; expires | legal obligation (art. 7, II: serving the data subject safely) |
| Citizen name and e-mail | `customers.display_label` and `customers.email` (migration 013, `app/db/operational.py:634-642` and `:690-696`); team alert text | given at the web handoff consent gate; name goes through `sanitize_for_persistence`; e-mail is format-validated and stored readable because the team uses it for contact | consent (art. 7, I), collected at the consent gate |
| Per-case `wa_id` (E.164 phone) | `case_whatsapp_bindings` (migration 016, `app/support/wa_binding.py`) | **reversibly** encrypted (Fernet, key `SUPPORT_WA_ENC_KEY`) plus an HMAC for lookup; wiped when the case closes or is cancelled, or after `SUPPORT_WA_BINDING_MAX_DAYS` (default 15 days) | legitimate interest (art. 7, IX) or public policy execution (art. 7, III); to be confirmed |
| Destination phone (citizen and staff) | `to` field of `operational_outbox.payload_sanitized` (`app/support/whatsapp_bridge.py:243-252`; `app/db/operational.py:556-558`) | stored **in clear**, despite the column name, so the dispatcher can deliver; no outbox purge routine exists in the code | same (citizen); legitimate interest (art. 7, IX) for staff phones |
| Staff member E.164 phone | HttpOnly remember cookie `<token>.<E.164>` in the staff member's browser (`app/support/staff_auth.py:14-19`, `:118`) | the database keeps only the token HMAC; the phone is in clear in the staff member's own cookie | legitimate interest (art. 7, IX): team access management |
| Name and role of an AI solution owner | `ai_solutions.owner_name` and `owner_role` (migration 021, AI solution intake) | employee data declared by the submitter; no e-mail, phone or ID; shown in the solution card and the inventory CSV, both behind a staff session | legitimate interest (art. 7, IX): AI governance; to be confirmed |
| Intake free text (purpose, notes, conditions) | `ai_solutions`, `ai_solution_events.note_sanitized` | masked by `sanitize_for_persistence` before storage; kept out of logs | same |
| Client IP address | `rate_limit_exceeded` log (`app/main.py`, `/chat` and `/web/chat` middleware) | only a truncated HMAC SHA-256 (`client_host_hash`, keyed by `PERSISTENCE_HASH_SECRET`); the clear IP never reaches the log | legitimate interest (art. 7, IX): channel security; to be confirmed |
| Asset code and address | maintenance ticket | operational, not personal | — |

Sensitive data (art. 11) is not collected. Children's data is not collected on purpose.

International transfer: the question goes through the same masking as
persistence before it reaches the embeddings provider (pgvector query) and
the LLM provider, together with the retrieved context
(`app/orchestration/chat_flow.py`; local card and secret detection uses the
original text). A real deployment needs contractual clauses with the vendor
and an inventory entry (art. 33).

## Criticality

| Dimension | Rating | Why |
| --- | --- | --- |
| Wrong answer impact | medium | could state a wrong deadline; mitigated because the console deadline comes from `domain.yaml`, not from LLM text |
| Wrong classification impact | medium-high | tagging a safety risk as cleaning delays response; mitigated by evals with `required_handoff_reasons` and mandatory human handling |
| Personal data | medium | phone, name, e-mail and free text; text is masked before persistence and before the provider; the phone is in clear in the outbox |
| Autonomy | low | every request that needs action becomes a case for a person |
| Public exposure | high | open citizen channel; rate limiting, confinement and safe fallback |

Suggested rating: **medium risk**, mandatory human review.

## Controls

| Control | Where | Evidence |
| --- | --- | --- |
| Scope, prompt and secret confinement | `docs/security/llm-confinement.md` (concession domains section), `domains/*/evals/confinement/` | confinement evals cover 33 cases (17 maintenance, 16 LGPD), all passing |
| Tested classification | `domains/*/evals/cases.yaml` (`required_handoff_reasons`) | base evals cover 36 cases (21 maintenance, 15 LGPD), including negative cases (term present with another meaning, negated, or inside another word), all passing |
| Deterministic deadline | `domain.yaml` `sla` block, `app/support/sla.py` | `tests/test_support_sla.py`, `tests/test_concessoes_domain.py` |
| Fixed safety guidance | `escalation_rules[].notice` in `domain.yaml`, applied in `ChatFlowService.answer` | `tests/test_rule_notices.py`; evals require "ligue 193", "nunca pede senha", "4 horas" (incident) and "24 horas" (auditor notice) even without an LLM |
| Development login limited to the local machine | `ENABLE_TEAM_DEV_LOGIN` (default `false`), `app/support/dev_login.py`: refuses to boot without an explicit `APP_ENV=development`; needs a loopback peer and `Host`; refuses proxy headers | `tests/test_team_dev_login.py` |
| Monthly report with no personal data | `app/support/monthly_report.py`, `GET /web/support/reports/monthly.csv` (staff session) | `tests/test_monthly_report.py` (no phone, name, e-mail, summary or `request_id` column; formula injection neutralized) |
| AI solution intake with rule-based criticality | `governance/ai-intake.yaml` (demo), `app/ai_intake/`: deterministic criticality, deadline frozen at submission, separation of duties (the submitter never reviews), DPIA (RIPD) reference required to approve high criticality, decisions with a note and a closed-list reason, event trail; database `CHECK`s for the closed lists | `tests/test_ai_intake.py`, `tests/test_ai_intake_routes.py`, `tests/integration/test_ai_intake_postgres.py` |
| Late reason from a closed list | `late_reason` required when closing after the deadline; database `CHECK`, no free text | `tests/test_monthly_report.py`, `tests/integration/test_monthly_report_postgres.py` |
| Masking before persistence | `app/core/persistence_sanitize.py` | `tests/test_pii_card.py`, `tests/test_pii_cpf.py`, `tests/test_privacy.py` |
| Masking before the provider | the question goes through the same masking before the embedding query and the LLM prompt; local detection (card, secret) uses the original text | `tests/test_provider_masking.py` |
| Logs without tokens or raw `session_id`; PII only in the exceptions listed under "Known limits" | `app/core/logging.py`, `docs/architecture/observability.md` | `tests/test_observability_hardening.py` |
| Consent before direct contact | consent gate on tickets | web handoff tests |
| Traceability | `request_id` on every response; audited case events | `tests/test_request_observability.py` |
| Safe fallback | provider or retrieval failure -> standard answer and handoff | `tests/test_chat_flow_errors.py` |
| AI-assisted development | `CLAUDE.md`, `.agents/skills/`, co-author trailer, tests and evals before commit | commit history |

## Known limits

- The `to` field of `operational_outbox.payload_sanitized` keeps the phone in clear, and the code has no outbox purge.
- The staff remember cookie carries the E.164 phone in clear.
- The `lgpd-titular` SLA `basis` cites art. 19, II for every `pedido_titular`, including deletion and correction, whose deadline follows regulation (art. 18, §5); there the 15 days are an internal target.
- Without an LLM key, evals check retrieval, classification and handoff, not generated text quality.
- Term-based classification (word start, `app/handoff/term_match.py`): a term matches at the start of a word (`picha` covers "picharam", but `risco` does not match inside "arrisco"), allows up to 2 content words inside a multi-word term (asset codes and function words do not count: "relogio REL-0423 esta apagado"), and skips simple negation right before, inside or right after the term ("sem risco", "nao ha nenhum risco", "o painel nao esta apagado", "risco nenhum"). It stays deterministic, with no LLM. Limits: unforeseen synonyms, more than 2 words in between ("o relogio da praca central ficou apagado") and negation that is farther away or worded differently ("nao esta com a hora errada") are not recognized. Negation errors fail safe: an unrecognized negation opens the case with the term's priority; a term that does not match leaves the turn on `low_confidence`, which goes to a person (safe, but it can grow the queue). Senses negation cannot express ("risco de multa", "tecnico atrasado") stay in per-rule `ignore_terms`; all of it is proven by negative and positive eval cases. The gap can raise a false high priority ("outra vez a pessoa" matches `outra pessoa` in the LGPD domain), always in the direction of sending the turn to a person.
- A protocol number without a label ("protocolo", "chamado", "ticket", "OS", "ordem de servico") or shorter than 13 digits is still masked: when in doubt, a number is treated as personal data. A protocol that passes the card checksum (Luhn) becomes `[REDACTED_CARD]`.
- Known masking limits: a phone glued to letters (`telefone11...`) is not caught; a formatted CNPJ is only partly masked; an ISO birth date stays readable (dd/mm/yyyy already did).
- Writing the case priority to a real PostgreSQL was not verified in this copy.
- No web UI for the console; the console is an API.
- AI solution intake: no roles (anyone on the console team can review; separation of duties is the only rule); deadlines in calendar days; criticality depends on what the submitter declares; no attachments (the DPIA is only a reference) and no notifications.

## Review log

| Date | Who | What |
| --- | --- | --- |
| 2026-11-26 | IT (AI development) — sample (demo) | first version |
| 2026-11-26 | coding agent, human review pending | data, transfer and limits aligned with the code |
| 2026-11-27 | coding agent, human review pending | AI solution intake: owner data, controls and limits |
| 2026-11-27 | coding agent, human review pending | word-start classification with a short gap and simple negation; limit and eval counts updated |
