# concession

Atendimento com RAG para operacao de concessoes de mobiliario urbano e midia
exterior: registra defeitos com o prazo do contrato, atende o titular de dados
com o prazo da LGPD e coloca os dois na mesma fila auditada do time.

> **Ambiente de demonstracao.** Contrato, prazos de manutencao, inventario de
> ativos e aviso de privacidade sao ficticios e estao marcados como tal em cada
> arquivo. Nao representam nenhuma empresa real. O nucleo vem do
> `supportFAQagent`, um agente de suporte cujos planos e runbooks de staging
> ficaram no repositorio de origem (ver `docs/archive/README.md`).

**English:** [summary in English](#english-summary) ·
[system card](docs/system-card.md).

## O problema

Uma concessao de mobiliario urbano vive de prazos que nao sao do time:

- **Prazo do contrato.** Um relogio de rua apagado ou um abrigo com vidro
  quebrado tem prazo de atendimento no anexo de niveis de servico. Perder o
  prazo e risco de penalidade e de desgaste na renovacao, e tela apagada e
  veiculacao que deixa de ser entregue.
- **Prazo da lei.** Um cidadao que pergunta "voces estao me filmando?" ou pede
  acesso aos seus dados tem direito a declaracao completa em ate 15 dias (LGPD
  art. 19, II). Para exclusao ou correcao, o prazo segue regulamento (art. 18,
  §5º); nesta demo, o caso usa os mesmos 15 dias como meta interna.
- **Prova.** Nos dois casos, quem fiscaliza quer ver quando o pedido chegou,
  qual prazo valia e quem tratou.

## O que este projeto faz

```text
Cidadao, tecnico ou fiscal (WhatsApp ou web)
  -> roteador de dominio (manutencao | privacidade)
  -> retrieval na base do dominio (anexo de SLA, aviso de privacidade)
  -> resposta com as fontes recuperadas, ou fallback seguro
  -> regra do dominio classifica o pedido (ex.: fio exposto = risco_seguranca)
  -> ticket com prioridade (urgent | high | normal | low)
  -> semaforo de SLA com o prazo e a base do prazo (clausula ou artigo)
```

| Dominio | Exemplo | Classificacao | Prazo no console | Base |
| --- | --- | --- | --- | --- |
| `concessoes-manutencao` | "Fio exposto soltando faisca no abrigo ABR-1104" | `risco_seguranca` -> urgent | 4h | Anexo de SLA (demo), item 3.1 |
| `concessoes-manutencao` | "O relogio REL-0423 esta com a tela apagada" | `tela_inoperante` -> high | 24h | Anexo de SLA (demo), item 3.2 |
| `concessoes-manutencao` | "Picharam o relogio da Praca da Se" | `conservacao_limpeza` -> low | 5 dias | Anexo de SLA (demo), item 3.4 |
| `lgpd-titular` | "Quero saber quais dados voces tem" | `pedido_titular` -> normal | 15 dias | LGPD art. 19, II |
| `lgpd-titular` | "Quero excluir meus dados" | `pedido_titular` -> normal | 15 dias | meta interna (demo); prazo legal segue regulamento (art. 18, §5º) |
| `lgpd-titular` | "Acho que meus dados vazaram" | `incidente_dados` -> urgent | 4h | meta interna (demo) |

O mesmo motor de SLA atende um prazo de contrato (horas) e um prazo legal
(dias). Cada dominio declara os seus no proprio `domain.yaml`, sem codigo
novo no nucleo.

## O que ja funciona

- **Dois dominios novos**, com base de conhecimento, prompts e evals:
  `concessoes-manutencao` e `lgpd-titular`.
- **SLA por dominio**: bloco `sla:` no `domain.yaml` sobrescreve o SLA global;
  a origem do prazo (`basis`) aparece em cada caso do console.
- **Prioridade por tipo de pedido**: `escalation_rules[].priority` define a
  prioridade do ticket; quando varias regras casam, vale a maior.
- **Evals que cobrem a classificacao** (20 casos base, 10 por dominio):
  `required_handoff_reasons` exige que "fio exposto" levante
  `risco_seguranca`, e nao so que nada inesperado apareca.
- **Do nucleo herdado**: API FastAPI, roteamento de dominio por mensagem,
  retrieval lexical ou pgvector, provider OpenAI ou Anthropic com fallback
  seguro, handoff com taxonomia, ticket duravel com console de SLA e
  transicoes auditadas, OTP via WhatsApp com consentimento LGPD, mascaramento
  de cartao, CNPJ, e-mail, telefone e IP antes de persistir, `request_id` em
  toda resposta.

## Status

| Item | Estado |
| --- | --- |
| Testes automatizados (`python -m pytest`) | 1048 passam, 44 pulados (integracao PostgreSQL, exigem banco) |
| Evals `concessoes-manutencao` (base + confinamento) | 30/30, com 3 casos negativos de precisao |
| Evals `lgpd-titular` (base + confinamento) | 29/29, com 3 casos de precisao e injecao |
| Evals do dominio de referencia `suporte-vps-whatsapp` | 20/20 |
| Gravacao da prioridade no ticket contra PostgreSQL real | nao verificada nesta copia (suite de integracao precisa de Docker) |
| Tela web do console (`/team`) | nao existe; o console e uma API |
| Chat com LLM real | exige `OPENAI_API_KEY`; sem chave, responde com o fallback seguro |

Os evals rodam sem chave de LLM. Nesse modo, eles validam retrieval,
fontes recuperadas (`references`), classificacao e escalonamento, mas nao a
qualidade do texto gerado pelo modelo nem o que ele de fato cita.

## Rodando localmente

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Linux/macOS: .venv/bin/python
cp .env.example .env
python -m pytest
python -m app.evals.run_domain_eval concessoes-manutencao
python -m app.evals.run_domain_eval lgpd-titular
uvicorn app.main:app --reload
```

Roteiro de demonstracao em 5 minutos: [docs/demo-roteiro.md](docs/demo-roteiro.md).

## Governanca e LGPD

- [Ficha do sistema](docs/ficha-do-sistema.md) (PT) e
  [System card](docs/system-card.md) (EN): responsavel, dados tratados, base
  legal, criticidade, controles e limites, no formato de um inventario de
  solucoes de IA.
- Agentes de codigo seguem `CLAUDE.md` e as skills versionadas em
  `.agents/skills/` (navegacao sem alucinar arquitetura, fluxo de commit com
  testes e evals, planejamento do proximo passo). Commits feitos com agente
  levam trailer de coautoria.

## Estrutura

```text
app/                      nucleo reutilizavel (API, handoff, SLA, retrieval, LLM, console)
domains/
  concessoes-manutencao/  manutencao do mobiliario urbano (demo)
  lgpd-titular/           canal do titular de dados (demo)
  suporte-vps-whatsapp/   dominio de referencia herdado, usado como regressao do nucleo
docs/                     arquitetura, contratos, setup, runbooks, ficha do sistema
migrations/               schema PostgreSQL
tests/                    testes unitarios e de integracao
```

## Documentacao

- [Mapa do projeto](docs/project-map.md): estado de cada frente.
- [Como navegar](docs/navigation.md): quais docs ler para cada tipo de mudanca.
- [Arquitetura](docs/architecture/architecture.md) e
  [contrato de dominio](docs/architecture/domain-contract.md).
- [Contratos de integracao](docs/architecture/integration-contracts.md).
- [Posicionamento](docs/product-positioning.md).

## Limites

Este projeto nao decide sozinho. Ele registra, classifica, devolve as fontes
recuperadas e
entrega o caso para uma pessoa com o prazo certo. Nao executa exclusao de
dados, nao discute multa, nao promete prazo menor que o do contrato e nao
revela dado pessoal pelo chat.

---

## English summary

`concession` is a RAG service desk for street furniture and outdoor
advertising concessions. It logs asset defects against the contract's
service-level deadline, handles data subject requests against the LGPD
(Brazil's data protection law) deadline, and puts both in the same audited
queue for the team.

> **Demo environment.** The contract, maintenance deadlines, asset inventory
> and privacy notice are fictional and labeled as such in every file. They do
> not represent any real company. The core comes from `supportFAQagent`, a
> support agent that has run in a real staging environment.

### The problem

A street furniture concession runs on deadlines the team does not set:

- **Contract deadline.** A dark street clock or a shelter with broken glass
  has a response time in the service-level annex. Missing it risks penalties
  and weakens the renewal case, and a dark screen is advertising that is not
  delivered.
- **Legal deadline.** A citizen who asks "are you filming me?" or requests
  deletion of their data is entitled to an answer within 15 days (LGPD
  art. 19, II).
- **Evidence.** In both cases, the auditor wants to see when the request
  arrived, which deadline applied and who handled it.

### What it does

```text
Citizen, technician or auditor (WhatsApp or web)
  -> domain router (maintenance | privacy)
  -> retrieval over the domain knowledge base (SLA annex, privacy notice)
  -> answer citing the source, or a safe fallback
  -> domain rule classifies the request (e.g. exposed wire = risco_seguranca)
  -> ticket with priority (urgent | high | normal | low)
  -> SLA traffic light with the deadline and its basis (clause or article)
```

| Domain | Example request | Classification | Console deadline | Basis |
| --- | --- | --- | --- | --- |
| `concessoes-manutencao` | Exposed wire sparking at shelter ABR-1104 | `risco_seguranca` -> urgent | 4h | SLA annex (demo), item 3.1 |
| `concessoes-manutencao` | Clock REL-0423 has a dark screen | `tela_inoperante` -> high | 24h | SLA annex (demo), item 3.2 |
| `concessoes-manutencao` | Graffiti on the clock at Praca da Se | `conservacao_limpeza` -> low | 5 days | SLA annex (demo), item 3.4 |
| `lgpd-titular` | "I want my data deleted" | `pedido_titular` -> normal | 15 days | LGPD art. 19, II |
| `lgpd-titular` | "I think my data leaked" | `incidente_dados` -> urgent | 4h | internal target (demo) |

The same SLA engine handles a contract deadline (hours) and a legal deadline
(days). Each domain declares its own in its `domain.yaml`, with no new code in
the core. Requests to the bot are in Portuguese; the examples above are
translated.

### What works today

- **Two new domains** with knowledge base, prompts and evals:
  `concessoes-manutencao` (maintenance) and `lgpd-titular` (data subject).
- **Per-domain SLA**: an `sla:` block in `domain.yaml` overrides the global
  SLA, and the deadline's source (`basis`) is shown on every console case.
- **Priority by request type**: `escalation_rules[].priority` sets the ticket
  priority; when several rules match, the highest wins.
- **Evals that prove classification**: `required_handoff_reasons` requires
  "exposed wire" to raise `risco_seguranca`, not just that nothing unexpected
  shows up.
- **Inherited from the core**: FastAPI API, per-message domain routing,
  lexical or pgvector retrieval, OpenAI or Anthropic provider with safe
  fallback, handoff taxonomy, durable tickets with an SLA console and audited
  transitions, WhatsApp OTP with LGPD consent, masking of card numbers, CNPJ,
  e-mail, phone and IP before persistence, and a `request_id` on every
  response.

### Status and limits

The status table above applies as is. In short: 1048 tests pass (44 skipped
PostgreSQL integration tests need a database), and the domain evals pass
(30/30 maintenance, 29/29 data subject, 20/20 reference domain). The evals run
without an LLM key, so they check retrieval, cited references, classification
and escalation, not the quality of model-generated text. Priority persistence
against a real PostgreSQL database is not yet verified in this copy, and the
team console is an API with no web screen yet.

The system does not decide on its own. It logs, classifies, cites the source
and hands the case to a person with the right deadline. It does not execute
data deletion, discuss penalties, promise a deadline shorter than the
contract's or disclose personal data in the chat.

Governance: the [system card](docs/system-card.md) lists owner, data
processed, legal basis, criticality, controls and limits, in the format of an
AI solution inventory. Coding agents follow `CLAUDE.md` and the skills in
`.agents/skills/`.
