# Mapa do projeto — concession

Mapa vivo: o que ja foi feito, o que esta em andamento e o que falta. Use como
primeiro destino; depois va para `docs/navigation.md`.

> Atualize este mapa ao terminar uma frente, seguindo a secao "Atualizar o
> estado do projeto" da skill `concession-git-flow`.

Legenda: ✅ feito · 🟡 parcial · ⬜ falta.

---

## Onde estamos

Copia limpa do nucleo `supportFAQagent` (sem historico, marca ou conteudo do
cliente original), adaptada para operacao de concessao de mobiliario urbano e
midia exterior. Dois dominios novos compartilham o mesmo console de SLA:
manutencao (prazo de contrato) e titular LGPD (prazo legal).

---

## Frentes

| Frente | Status | O que existe | O que falta | Validacao |
| --- | --- | --- | --- | --- |
| Dominio `concessoes-manutencao` | ✅ | 14 ativos ficticios, anexo de SLA ficticio (itens 3.1-3.6), 5 regras de escalonamento com prioridade, prompts | trocar prazos e inventario pelos do contrato real | evals base 10/10, confinamento 17/17, `tests/test_concessoes_domain.py` |
| Dominio `lgpd-titular` | ✅ | aviso de privacidade ficticio, direitos (art. 18), prazos (art. 19, II), 4 regras com prioridade | revisao do texto pelo encarregado real | evals base 10/10, confinamento 16/16 |
| SLA por dominio (`sla:` no `domain.yaml`) | ✅ | override por prioridade, `basis` na resposta do console, lista, detalhe e metricas | — | `tests/test_support_sla.py`, `tests/test_web_support_console.py` |
| Prioridade do caso por regra | ✅ | `escalation_rules[].priority`, `resolve_case_priority`, coluna `priority` no INSERT do `record_chat`, provada em PostgreSQL real ate `GET /web/support/cases` (prioridade, cor e `basis` por dominio) | — | `tests/test_concessoes_domain.py`, `tests/integration/test_demo_seed_console_postgres.py` (job `postgres` do Phase 0 Gates) |
| Seed de demonstracao do console | ✅ | `scripts/seed_demo_cases.py`: 13 casos ficticios nos dois dominios (todas as prioridades que as regras produzem; vermelho, amarelo, verde e pausado em cada dominio), operador `Atendente Demo 1`, idempotente, `--reset` so apaga o que e marcado `demo-seed`; recusa fora de `APP_ENV` development/test ou banco nao local | — | `tests/test_seed_demo_cases.py`, `tests/integration/test_demo_seed_console_postgres.py`; runbook `docs/runbooks/support-console-smoke.md` |
| Gates PostgreSQL do console na CI | ✅ | `test_support_console_postgres.py`, `test_support_transitions_postgres.py` e o teste do seed rodam no job `postgres` de `phase0-gates.yml` | — | CI (so depois do push) |
| Evals com `required_handoff_reasons` | ✅ | o eval exige o motivo certo, nao so a ausencia de motivo errado | — | evals dos dois dominios |
| Roteamento manutencao x privacidade | ✅ | saudacao e esclarecimento novos, empate cai no menu | — | `tests/test_domain_router.py` |
| Ficha do sistema (PT/EN) | ✅ | `docs/ficha-do-sistema.md`, `docs/system-card.md` | — | revisao humana |
| Tela web do console (`/team`) | ⬜ | API do console pronta (`/web/support/*`) | tela para o time ver a fila e o semaforo | — |
| Intake de solucoes de IA (inventario) | ⬜ | formato da ficha | formulario, modelo de dados e fila de revisao | — |
| Relatorio mensal para a fiscalizacao | ⬜ | metricas do console | exportacao por categoria e prazo | — |
| Detector de CPF com digito verificador | ⬜ | mascaramento de cartao, CNPJ, e-mail, telefone, IP | CPF explicito (hoje provavelmente cai na regra de telefone) | — |

## Herdado do nucleo (sem mudanca nesta copia)

API FastAPI, retrieval lexical e pgvector, providers OpenAI e Anthropic com
fallback, handoff com taxonomia, ticket duravel, console com transicoes
auditadas, OTP via WhatsApp com consentimento, persistencia sanitizada,
readiness, transporte Meta WhatsApp e Hermes (desligados por padrao).

Mais detalhes em `docs/documentation-status.md`.
