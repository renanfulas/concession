# concession

Atendimento com RAG para operacao de concessoes de mobiliario urbano e midia
exterior: registra defeitos com o prazo do contrato, atende o titular de dados
com o prazo da LGPD e coloca os dois na mesma fila auditada do time.

> **Ambiente de demonstracao.** Contrato, prazos de manutencao, inventario de
> ativos e aviso de privacidade sao ficticios e estao marcados como tal em cada
> arquivo. Nao representam nenhuma empresa real. O nucleo vem do
> `supportFAQagent`, um agente de suporte que ja operou em staging real.

## O problema

Uma concessao de mobiliario urbano vive de prazos que nao sao do time:

- **Prazo do contrato.** Um relogio de rua apagado ou um abrigo com vidro
  quebrado tem prazo de atendimento no anexo de niveis de servico. Perder o
  prazo e risco de penalidade e de desgaste na renovacao, e tela apagada e
  veiculacao que deixa de ser entregue.
- **Prazo da lei.** Um cidadao que pergunta "voces estao me filmando?" ou pede
  a exclusao dos seus dados tem resposta garantida em ate 15 dias (LGPD
  art. 19, II).
- **Prova.** Nos dois casos, quem fiscaliza quer ver quando o pedido chegou,
  qual prazo valia e quem tratou.

## O que este projeto faz

```text
Cidadao, tecnico ou fiscal (WhatsApp ou web)
  -> roteador de dominio (manutencao | privacidade)
  -> retrieval na base do dominio (anexo de SLA, aviso de privacidade)
  -> resposta citando a fonte, ou fallback seguro
  -> regra do dominio classifica o pedido (ex.: fio exposto = risco_seguranca)
  -> ticket com prioridade (urgent | high | normal | low)
  -> semaforo de SLA com o prazo e a base do prazo (clausula ou artigo)
```

| Dominio | Exemplo | Classificacao | Prazo no console | Base |
| --- | --- | --- | --- | --- |
| `concessoes-manutencao` | "Fio exposto soltando faisca no abrigo ABR-1104" | `risco_seguranca` -> urgent | 4h | Anexo de SLA (demo), item 3.1 |
| `concessoes-manutencao` | "O relogio REL-0423 esta com a tela apagada" | `tela_inoperante` -> high | 24h | Anexo de SLA (demo), item 3.2 |
| `concessoes-manutencao` | "Picharam o relogio da Praca da Se" | `conservacao_limpeza` -> low | 5 dias | Anexo de SLA (demo), item 3.4 |
| `lgpd-titular` | "Quero excluir meus dados" | `pedido_titular` -> normal | 15 dias | LGPD art. 19, II |
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
- **Evals que provam classificacao**: `required_handoff_reasons` exige que
  "fio exposto" levante `risco_seguranca`, e nao so que nada inesperado
  apareca.
- **Do nucleo herdado**: API FastAPI, roteamento de dominio por mensagem,
  retrieval lexical ou pgvector, provider OpenAI ou Anthropic com fallback
  seguro, handoff com taxonomia, ticket duravel com console de SLA e
  transicoes auditadas, OTP via WhatsApp com consentimento LGPD, mascaramento
  de cartao, CNPJ, e-mail, telefone e IP antes de persistir, `request_id` em
  toda resposta.

## Status

| Item | Estado |
| --- | --- |
| Testes automatizados (`python -m pytest`) | 949 passam, 44 pulados (integracao PostgreSQL, exigem banco) |
| Evals `concessoes-manutencao` (base + confinamento) | 27/27 |
| Evals `lgpd-titular` (base + confinamento) | 26/26 |
| Evals do dominio de referencia `suporte-vps-whatsapp` | 20/20 |
| Gravacao da prioridade no ticket contra PostgreSQL real | nao verificada nesta copia (suite de integracao precisa de Docker) |
| Tela web do console (`/team`) | nao existe; o console e uma API |
| Chat com LLM real | exige `OPENAI_API_KEY`; sem chave, responde com o fallback seguro |

Os evals rodam sem chave de LLM. Nesse modo, eles validam retrieval,
referencias citadas, classificacao e escalonamento, mas nao a qualidade do
texto gerado pelo modelo.

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

Este projeto nao decide sozinho. Ele registra, classifica, cita a fonte e
entrega o caso para uma pessoa com o prazo certo. Nao executa exclusao de
dados, nao discute multa, nao promete prazo menor que o do contrato e nao
revela dado pessoal pelo chat.
