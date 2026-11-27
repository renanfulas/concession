---
name: concession-project-navigator
description: Use when an AI agent needs to understand, navigate, plan, or modify the concession project (derived from the supportFAQagent core) without guessing architecture. Helps choose the right docs, folders, and tests for changes involving product positioning, FastAPI, domains, ingestion, GitHub loaders, retrieval, LLM, evals, Meta WhatsApp, Hermes, PostgreSQL/pgvector, VPS, observability, dependency management, or knowledge base content.
---

# concession Project Navigator

## O que esta skill faz

Skill que ajuda o agente a navegar no projeto sem alucinar arquitetura. Ela orienta a leitura do `README.md`, `CONTRIBUTING.md` e dos docs certos para cada tipo de mudanca, indicando pastas, responsabilidades e testes.

Use this skill before changing project structure, code, docs, domains, integrations, or knowledge content.

Goal: understand the project from repository sources, read only the needed docs, and avoid hallucinating architecture.

Also preserve the product positioning in `docs/product-positioning.md`: commercial but technical, operationally safe, traceable, and honest about MVP limits.

## First Step

Always start with:

1. Read `README.md`.
2. Read `docs/product-positioning.md` when the task touches README, docs, PR text, public positioning, onboarding, or agent instructions.
3. Read `CONTRIBUTING.md`.
4. Identify the change area.
5. Read only the docs needed for that area.

Do not load every doc by default.

## Mapa de documentação (onde achar cada coisa)

Primeiro destino: `docs/project-map.md` (estado de cada frente) e
`docs/navigation.md` (roteador por tarefa).

| Pasta | O que vive aqui |
| --- | --- |
| `docs/` (raiz) | Índices: `project-map.md`, `navigation.md`, `documentation-status.md`, `product-positioning.md`, `agent-skills.md`, `ficha-do-sistema.md`, `system-card.md`, `demo-roteiro.md`, `references-legacy.md` |
| `docs/architecture/` | Design, fronteiras, contratos e padrões do sistema |
| `docs/setup/` | Instalação e configuração de ambiente |
| `docs/runbooks/` | Procedimentos operacionais (pgvector, console, restore, Redis) |
| `docs/security/` | Contratos de segurança (confinamento do LLM) |
| `docs/archive/` | Índice do que ficou no repositório de origem |

### Lookup por assunto

| Assunto | Onde olhar |
| --- | --- |
| Domínios da demo | `domains/concessoes-manutencao/`, `domains/lgpd-titular/`, `docs/architecture/domain-contract.md` |
| SLA por domínio e prioridade do caso | `docs/architecture/domain-contract.md` (blocos `sla` e `escalation_rules[].priority`); código em `app/support/sla.py`, `app/handoff/taxonomy.py` |
| Intake e inventario de solucoes de IA | `docs/architecture/ai-intake.md`; politica em `governance/ai-intake.yaml`; codigo em `app/ai_intake/`, `app/api/routes/ai_intake.py`, `app/static/team/intake.*` |
| Console do time / tickets | `docs/architecture/integration-contracts.md`, `docs/runbooks/support-console-smoke.md`; código em `app/support/`, `app/api/routes/web_support.py` |
| LGPD / privacidade | `docs/ficha-do-sistema.md`, `SECURITY.md`, `docs/architecture/observability.md`; código em `app/core/persistence_sanitize.py`, `app/core/privacy.py` |
| pgvector / retrieval | `docs/architecture/architecture.md`, `docs/runbooks/pgvector-promotion-checklist.md`, `docs/runbooks/pgvector-retrieval-contract.md` |
| Transporte WhatsApp (Meta, Hermes) | `docs/architecture/integration-contracts.md`. Adapter de transporte externo: não mover inteligência para lá |
| Evals / conhecimento | `docs/architecture/knowledge-authoring.md`, `docs/architecture/domain-evals.md` |
| Segurança | `SECURITY.md`, `docs/security/llm-confinement.md`, `docs/architecture/observability.md` |

O histórico de planos e runbooks de staging ficou no repositório de origem
(ver `docs/archive/README.md` e `docs/references-legacy.md`).

## Area Map

Use this map to decide what to read.

| Change area | Read before editing | Likely folders |
| --- | --- | --- |
| Product positioning, README, public docs, PR narrative, agent instructions | `docs/product-positioning.md`, `README.md`, `docs/agent-skills.md` | `README.md`, `docs/`, `.agents/skills/` |
| Architecture or module boundaries | `docs/architecture/architecture.md`, `docs/architecture/architecture.md`, `docs/navigation.md` | `app/`, `docs/` |
| API contracts | `docs/architecture/integration-contracts.md`, `docs/architecture/observability.md` | `app/api/routes/`, `app/api/schemas/`, `app/feedback/`, `tests/` |
| Domain behavior | `docs/architecture/domain-contract.md`, `docs/navigation.md` | `domains/<domain>/domain.yaml`, `app/domain_engine/` |
| Knowledge base or FAQs | `docs/architecture/knowledge-authoring.md`, `docs/architecture/domain-evals.md` | `domains/<domain>/knowledge/`, `domains/<domain>/evals/` |
| Evals or calibration | `docs/architecture/domain-evals.md`, `docs/architecture/knowledge-authoring.md` | `app/evals/`, `domains/<domain>/evals/`, `tests/` |
| Ingestion | `docs/architecture/integration-contracts.md`, `docs/architecture/architecture.md` | `app/ingestion/`, `app/api/routes/ingestion.py`, `app/api/schemas/ingestion.py` |
| GitHub document loader or external source loading | `docs/architecture/knowledge-authoring.md`, `docs/architecture/architecture.md`, `docs/navigation.md` | `app/ingestion/github_loader.py`, `scripts/fetch_github_document.py`, `tests/test_github_loader.py` |
| Retrieval or vector store | `docs/architecture/architecture.md`, `docs/architecture/architecture.md` | `app/retrieval/`, `app/orchestration/` |
| LLM/provider/prompt | `docs/architecture/architecture.md`, `docs/architecture/domain-contract.md` | `app/llm/`, `app/orchestration/`, `domains/<domain>/prompts/` |
| Handoff or escalation | `docs/architecture/domain-contract.md`, `docs/architecture/integration-contracts.md`, `docs/architecture/domain-evals.md` | `app/handoff/`, `app/orchestration/`, `domains/<domain>/domain.yaml`, `tests/` |
| Observability/logging | `docs/architecture/observability.md`, `docs/architecture/architecture.md` | `app/core/`, `app/main.py`, route files |
| Security or public surface hardening | `SECURITY.md`, `docs/security/`, `docs/architecture/observability.md`, `docs/architecture/code-standards.md` | `app/core/`, `app/api/`, `tests/security/`, `.github/workflows/` |
| Meta WhatsApp, Hermes or external transport integration | `docs/architecture/integration-contracts.md`, `docs/architecture/observability.md`, `docs/architecture/architecture.md` | docs first; do not move intelligence into any external transport |
| PostgreSQL/pgvector | `docs/architecture/architecture.md`, `docs/architecture/architecture.md`, `docs/runbooks/pgvector-promotion-checklist.md` | `app/db/`, `app/retrieval/`, `app/ingestion/pgvector_writer.py`, `migrations/`, `scripts/ingest_domain_pgvector.py` |
| Deploy/runtime | `docs/setup/environments.md`, `docs/architecture/observability.md`, `docs/runbooks/` | `scripts/runtime_preflight.ps1`, config/docs |
| Dependency management or security audit | `pyproject.toml`, `CONTRIBUTING.md`, `.github/workflows/security.yml` | `pyproject.toml`, `.github/workflows/`, docs that mention install commands |
| Local chat UI or static assets | `README.md`, `docs/setup/environments.md`, `docs/architecture/architecture.md` | `app/static/`, `app/main.py`, `app/core/config.py` |

## Project Rules

- Keep the core reusable across domains.
- Put domain-specific behavior in `domains/`, not hardcoded in `app/`.
- Routes should validate and orchestrate, not hold business logic.
- Prefer small adapters and interfaces over heavy framework coupling.
- Keep Meta, Hermes and any external transport outside the
  intelligence core.
- Treat PostgreSQL + pgvector as the planned production vector store.
- Treat Chroma as local/prototype unless the team explicitly decides otherwise.
- Treat `pyproject.toml` as the only dependency source of truth; do not create parallel dependency lists.
- Use the official GitHub Contents API for GitHub document ingestion; do not scrape GitHub HTML.
- Keep public communication commercial-technical: explain business value, traceability, safe fallback, and human handoff without promising full autonomy.
- Do not log raw PII, tokens, secrets, prompts with sensitive data, or raw `session_id`.

## Before Editing

Answer these internally:

1. Is this shared core behavior or domain-specific behavior?
2. Which docs define the current contract?
3. Which area of the codebase does this touch?
4. What test or eval should prove the change?
5. Does this require documentation updates?

## Validation Guidance

Choose validations by change type:

- Any code change: `python -m pytest`
- Any Python module change: `python -m compileall app tests scripts`
- Domain, prompt, retrieval, handoff, or knowledge change: `python -m app.evals.run_domain_eval concessoes-manutencao` e `python -m app.evals.run_domain_eval lgpd-titular`
- API contract change: add/update endpoint tests and update `docs/architecture/integration-contracts.md`
- Knowledge article change: update eval references when expected behavior changes
- Dependency change: `python -m pip_audit .`, `python -m pip check`, and extra dry-runs when optional extras change

## Output Style

When reporting a plan or summary, include:

- Area touched.
- Docs read.
- Files likely affected.
- Tests/evals required.
