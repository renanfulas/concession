# Como navegar no projeto

## Primeiro mapa mental

- `app/` e o nucleo reutilizavel: API, orquestracao, handoff, SLA, retrieval, LLM, console.
- `domains/` guarda o que e especifico de cada setor: persona, regras, prazos, conhecimento e evals.
- `docs/` explica contratos, arquitetura e operacao.
- `tests/` prova o comportamento; `domains/<dominio>/evals/` prova a qualidade do dominio.

## Comece Em 10 Minutos

1. `README.md`: o que o projeto faz e o estado atual.
2. `docs/project-map.md`: frentes, status e o que falta.
3. `docs/architecture/domain-contract.md`: como um dominio declara regras e prazos.
4. `domains/concessoes-manutencao/domain.yaml`: um dominio completo.
5. `docs/demo-roteiro.md`: como mostrar funcionando.

## Leitura Por Tarefa

| Tarefa | Leia antes |
| --- | --- |
| Criar ou mudar um dominio | `docs/architecture/domain-contract.md`, `docs/architecture/knowledge-authoring.md`, `docs/architecture/domain-evals.md` |
| Mudar prazo ou prioridade | `docs/architecture/domain-contract.md` (blocos `sla` e `escalation_rules[].priority`) |
| Mudar API ou console | `docs/architecture/integration-contracts.md`, `docs/architecture/observability.md` |
| Retrieval ou pgvector | `docs/architecture/architecture.md`, `docs/runbooks/pgvector-promotion-checklist.md` |
| LGPD, dados, logs | `docs/ficha-do-sistema.md`, `SECURITY.md`, `docs/architecture/observability.md` |
| Seguranca do LLM | `docs/security/llm-confinement.md` |
| Ambiente e setup | `docs/setup/environments.md`, `docs/setup/local-postgres-test-harness.md` |
| Instrucoes para agentes de codigo | `CLAUDE.md`, `docs/agent-skills.md` |

## O que procurar em cada pasta

## `app/main.py`

Mostra como a API sobe e quais rotas estao expostas.

## `app/api/routes/`

Aqui ficam os endpoints. E o lugar certo para entender o contrato publico da aplicacao.

## `app/core/request_context.py`

Centraliza o `X-Request-ID` usado para correlacionar chamadas, erros e logs.

## `app/core/config.py`

Mostra variaveis de ambiente, defaults locais, feature flags como `RETRIEVAL_BACKEND` e protecoes como `API_SECRET_KEY`.

## `app/api/schemas/`

Define entrada e saida da API.

## `app/domain_engine/`

Mostra como um dominio e carregado do disco para a aplicacao. O contrato esperado esta em `docs/architecture/domain-contract.md`.

## `app/ingestion/`

Mostra como artigos e FAQs viram insumos utilizaveis pelo RAG.

Inclui tambem `github_loader.py`, que busca arquivos pela GitHub Contents API oficial. Use esse caminho para fontes GitHub; nao crie scraping de HTML do GitHub.

## `app/retrieval/`

Mostra como o contexto e localizado para responder perguntas.

## `app/llm/`

Mostra como os providers sao isolados do restante do sistema.

## `app/orchestration/`

Aqui esta o fluxo principal do agente. Quando quiser entender a jornada ponta a ponta, comece por aqui.

## `app/handoff/`

Concentra regras de escalonamento humano reutilizaveis, como baixa confianca, pedido explicito e termos sensiveis. `taxonomy.py` decide se o turno vai para a fila humana e qual a prioridade do caso (`resolve_case_priority`).

## `app/support/`

Console do time: fila de casos, semaforo de SLA (`sla.py`, com override por dominio), transicoes auditadas, metricas e ponte WhatsApp.

## `app/feedback/`

Concentra o servico e o contrato interno de feedback. Quando
`PERSISTENCE_BACKEND=postgres`, o contexto confiavel vem da resposta original
persistida e o cliente nao pode substituir referencias ou motivos de handoff.

## `app/conversations/`

Concentra persistencia sanitizada de conversas e mensagens, isolamento por
dominio, canal e hash de sessao, alem da leitura do historico curto real.

## `app/health/`

Concentra readiness operacional separado para banco, migrations, retrieval e
outbox. `GET /health` continua sendo liveness simples; `GET /health/ready` e o
gate autenticado para promover runtime.

## `app/evals/`

Ferramentas locais para rodar calibragem de dominio contra casos reais versionados.

## `app/db/` e `migrations/`

Guardam modelos, conexao e artefatos SQL. Mudancas de schema, indices, migrations e queries finais de pgvector devem respeitar ownership de banco.

O fluxo atual usa migrations SQL forward-only com ledger, checksum e runner em
`python -m scripts.migrate`. Nunca aplique `006` e `007` juntas em banco
existente sem executar o backfill e confirmar que writers legados foram
drenados.

## `app/static/`

Chat UI local/staging para validacao controlada. Nao substitui integracoes externas como Meta WhatsApp, Hermes ou outros consumidores servidor-servidor.

## `scripts/`

Comandos operacionais e validacoes pontuais, incluindo ingestao pgvector, preflight de runtime, smoke de staging e fetch de documento GitHub.

## Pastas de `docs/`

| Pasta | O que vive aqui |
| --- | --- |
| `docs/` (raiz) | Indices: `project-map.md`, `navigation.md`, `documentation-status.md`, `product-positioning.md`, `agent-skills.md`, `ficha-do-sistema.md`, `system-card.md`, `demo-roteiro.md`, `references-legacy.md` |
| `docs/architecture/` | Design, fronteiras, contratos e padroes do sistema |
| `docs/setup/` | Instalacao e configuracao de ambiente |
| `docs/runbooks/` | Procedimentos operacionais |
| `docs/security/` | Contratos de seguranca |
| `docs/archive/` | Indice do que ficou no repositorio de origem |

## `.agents/skills/`

Instrucoes versionadas para agentes de IA navegarem, decidirem proximos passos, alterarem, testarem, commitarem e abrirem PRs neste projeto.

## `domains/concessoes-manutencao/` e `domains/lgpd-titular/`

Os dois dominios da demo. Cada um tem `domain.yaml` (persona, escopo, regras de escalonamento com prioridade, bloco `sla`), `knowledge/`, `prompts/` e `evals/` (base e confinamento). Use como modelo para um dominio novo.

## `domains/suporte-vps-whatsapp/`

Dominio de referencia herdado do nucleo. Fica no repositorio como regressao: boa parte dos testes do nucleo roda contra ele. Nao faz parte da demo.

## Como pensar uma nova mudanca

Pergunte primeiro:

1. Isso e compartilhado entre dominios ou especifico de um?
2. Isso e regra de negocio, infraestrutura ou contrato HTTP?
3. Isso muda conteudo, comportamento ou persistencia?

Esse filtro simples costuma apontar a pasta correta antes mesmo de codar.
