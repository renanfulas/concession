# Estado Da Documentacao

## Fontes Ativas De Verdade

| Tema | Fonte |
| --- | --- |
| O que o projeto e e o que nao promete | `README.md`, `docs/product-positioning.md` |
| Estado das frentes | `docs/project-map.md` |
| Arquitetura e fronteiras | `docs/architecture/architecture.md`, `docs/architecture/framework-boundary.md` |
| Contrato de dominio (inclui `sla` e `priority`) | `docs/architecture/domain-contract.md` |
| Contratos HTTP (inclui `sla.basis` do console) | `docs/architecture/integration-contracts.md` |
| Evals | `docs/architecture/domain-evals.md` |
| Autoria de conhecimento | `docs/architecture/knowledge-authoring.md` |
| Observabilidade e privacidade de logs | `docs/architecture/observability.md` |
| Confinamento do LLM | `docs/security/llm-confinement.md`, `SECURITY.md` |
| Dados tratados, base legal, controles | `docs/ficha-do-sistema.md`, `docs/system-card.md` |
| Ambientes | `docs/setup/environments.md`, `docs/setup/local-postgres-test-harness.md` |
| Operacao | `docs/runbooks/` |
| Instrucoes para agentes | `CLAUDE.md`, `docs/agent-skills.md`, `.agents/skills/` |

## Estado Consolidado

- Dominios da demo: `concessoes-manutencao` e `lgpd-titular`, com conteudo
  ficticio marcado em cada arquivo.
- Dominio de referencia: `suporte-vps-whatsapp`, mantido como regressao do
  nucleo.
- Migrations `001-019` sem mudanca de schema nesta copia; a coluna `priority`
  de `support_cases` ja existia e agora recebe o valor do turno.
- Seed de demonstracao do console: `scripts/seed_demo_cases.py` (somente
  `APP_ENV` development/test e banco local, fora de `migrations/`), descrito
  em `docs/runbooks/support-console-smoke.md`. O job `postgres` de
  `.github/workflows/phase0-gates.yml` agora roda tambem os testes de
  integracao do console (leitura/metricas, transicoes e seed).
- Planos historicos, runbooks de staging e relatorios do repositorio de origem
  nao foram copiados (ver `docs/archive/README.md`).

## Regra De Atualizacao

Atualize este arquivo quando mudar contrato HTTP, migration, dominio novo,
ownership ou operacao. Mudancas de status de frente vao em
`docs/project-map.md`. A guarda `tests/test_docs_links.py` falha se um link
de doc quebrar.
