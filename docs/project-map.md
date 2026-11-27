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
| Dominio `concessoes-manutencao` | ✅ | 14 ativos ficticios, anexo de SLA ficticio (itens 3.1-3.6), 7 regras de escalonamento com prioridade (inclui `defeito_geral`, item 3.3, e `cobranca_atendimento`), prompts | trocar prazos e inventario pelos do contrato real | evals base 13/13 (3 negativos), confinamento 17/17, `tests/test_concessoes_domain.py` |
| Dominio `lgpd-titular` | ✅ | aviso de privacidade ficticio, direitos (art. 18), prazos (art. 19, II para acesso; art. 18, §5º para exclusao e correcao, com 15 dias como meta interna demo), 4 regras com prioridade | revisao do texto pelo encarregado real; `basis` do SLA ainda cita so o art. 19, II | evals base 13/13 (3 de precisao e injecao), confinamento 16/16 |
| SLA por dominio (`sla:` no `domain.yaml`) | ✅ | override por prioridade, `basis` na resposta do console, lista, detalhe e metricas; fila `attention` ordenada pela pressao do prazo de cada caso (semaforo, depois `deadline_at`, pausados no fim) | — | `tests/test_support_sla.py`, `tests/test_web_support_console.py` |
| `domain.yaml` invalido nao some calado | ✅ | `DomainLoader` registra `domain_config_invalid` (WARN, so o nome do campo, nunca o valor) e um teste exige que todo dominio versionado carregue | — | `tests/test_domain_loader_warnings.py` |
| Prioridade do caso por regra | ✅ | `escalation_rules[].priority`, `resolve_case_priority`, coluna `priority` no INSERT do `record_chat`, provada em PostgreSQL real ate `GET /web/support/cases` (prioridade, cor e `basis` por dominio) | — | `tests/test_concessoes_domain.py`, `tests/integration/test_demo_seed_console_postgres.py` (job `postgres` do Phase 0 Gates) |
| Seed de demonstracao do console | ✅ | `scripts/seed_demo_cases.py`: 13 casos ficticios nos dois dominios (todas as prioridades que as regras produzem; vermelho, amarelo, verde e pausado em cada dominio), operador `Atendente Demo 1`, idempotente, `--reset` so apaga o que e marcado `demo-seed`; recusa fora de `APP_ENV` development/test ou banco nao local | — | `tests/test_seed_demo_cases.py`, `tests/integration/test_demo_seed_console_postgres.py`; runbook `docs/runbooks/support-console-smoke.md` |
| Gates PostgreSQL do console na CI | ✅ | `test_support_console_postgres.py`, `test_support_transitions_postgres.py` e o teste do seed rodam no job `postgres` de `phase0-gates.yml` | — | CI (so depois do push) |
| Evals com `required_handoff_reasons` | ✅ | o eval exige o motivo certo, nao so a ausencia de motivo errado | — | evals dos dois dominios |
| Roteamento manutencao x privacidade | ✅ | saudacao e esclarecimento novos, empate cai no menu; numero so escolhe opcao quando e a mensagem inteira ("2", "opcao 2"), nunca "Rua 2" | nome da opcao ("manutencao", "privacidade") dentro de frase ainda conta como escolha e devolve so o welcome | `tests/test_domain_router.py` |
| Entradas da demo sem `.env` | ✅ | `DEFAULT_DOMAIN` padrao e `concessoes-manutencao` (fonte unica em `Settings`, lida pelo health); `/web/chat` usa o mesmo roteador e memoria pegajosa do WhatsApp (`ENABLE_WEB_DOMAIN_ROUTER=true` por padrao) | — | `tests/test_web_chat.py`, `tests/test_health_readiness.py` |
| `references` sem caminho do servidor | ✅ codigo · ✅ banco (ensaio local) | fonte estavel `domains/<dominio>/knowledge/...` na ingestao; resposta deduplicada e com caminhos legados reescritos (`app/orchestration/references.py`) | repetir o roteiro no primeiro ambiente com pgvector persistente (`docs/runbooks/pgvector-promotion-checklist.md`, "Ensaio da reingestao") | `tests/test_reference_paths.py` |
| Retrieval lexical com acentos e ranking | ✅ | `fold()` nos dois lados ("relógio" casa com "relogio"); stopwords e 1-2 letras so reordenam os trechos ja selecionados, com titulo pesando mais e radical de 5 letras; selecao e score iguais aos de antes, entao confianca e escalonamento nao mudam | — | `tests/test_lexical_ranking.py`, `tests/test_reference_paths.py` |
| Orientacao de seguranca deterministica (`notice`) | ✅ | texto fixo por regra (risco a pessoas: afastar e ligar 193; incidente de dados: triagem em 4 horas, trocar senhas, canal nunca pede senha; notificacao da fiscalizacao: resposta em 24 horas, sem valor de multa), antes de qualquer resposta, inclusive fallback e resposta bloqueada | revisar o texto com seguranca do trabalho e o encarregado reais | `tests/test_rule_notices.py`, evals base dos dois dominios |
| Ficha do sistema (PT/EN) | ✅ | `docs/ficha-do-sistema.md`, `docs/system-card.md`, alinhadas ao codigo (dados guardados, mascaramento antes do provedor, bases legais como raciocinio demo) | confirmar bases legais com o encarregado real | revisao humana |
| Resumo em ingles no README | ✅ | secao `English summary` no fim do `README.md`, com link no topo | atualizar junto quando o status em PT mudar | `tests/test_docs_links.py`, revisao humana |
| Mascarar a pergunta antes do provedor de LLM/embeddings | ✅ | `sanitize_for_persistence` aplicado antes de `retrieve` e `build_prompt` em `app/orchestration/chat_flow.py`; deteccao local continua no texto original | historico de conversa enviado ao prompt ja vem mascarado da persistencia | `tests/test_provider_masking.py` |
| Evals com LLM real (opt-in, nao e gate) | ✅ | `--provider-mode real`, `--runs`, `--report`; falha com `provider_error`; bloco `llm_expectation` (`any_of`, `forbidden_terms`, `allowed_durations`, `expected_citation`) em 10 casos base; relatorio com modelo, temperatura, commit, pass@all e uso de tokens | linha de base 21/26 e, depois da correcao (`3386ca6`), 26/26 pass@all no README; rodar de novo ao trocar modelo, prompt ou base | `tests/test_eval_real_mode.py` (providers falsos); gate deterministico inalterado |
| Gate de evals sem LLM independente de chave | ✅ | `run_domain_eval` em modo `deterministic` usa `OfflineLLMService` e nunca chama provedor, mesmo com `OPENAI_API_KEY` no `.env` | — | `tests/test_domain_evals.py` |
| Textos da tela do cidadao (`/chat-ui`) | ✅ | identidade visual propria e ficticia, layout em duas colunas (como funciona e prazos de demo), aviso da regra como alerta, cartao "Chamado registrado" com protocolo curto, prioridade, prazo e base, fontes pelo titulo, modo escuro; nenhum `request_id`, `error_code` ou nome de arquivo cru na tela; titulo, descricao, exemplo e perguntas rapidas da concessao (defeito com codigo do ativo, risco a pessoas, meus dados, cameras); nome de exibicao com acento | revisar o texto com o time de atendimento real | `tests/test_app.py` |
| Tela web do console (`/team`) | ✅ (somente leitura) | painel do topo com backlog por cor (`GET /web/support/metrics`, clicar filtra), barra de prazo consumido, etiquetas de dominio e de motivo, resumo mascarado visivel; `app/static/team/`, flag `ENABLE_TEAM_UI`, login OTP staff e login de desenvolvimento opcional (`ENABLE_TEAM_DEV_LOGIN`: so `APP_ENV=development` explicito, peer e `Host` de loopback, sem headers de proxy), fila `sort=attention` com semaforo, prazo, base, filtros e refresh de 60 s; `GET /web/support/domains` para os nomes de exibicao | acoes de escrita (assumir, pausar, fechar), painel de metricas | `tests/test_team_screen.py` |
| GIF de demonstracao no README | ✅ | `docs/assets/demo-concession.gif` (55 s, 1,0 MB, regravado com as telas novas): chat do cidadao (alerta de seguranca e cartao do chamado; exclusao de dados com prazo de 15 dias) e fila `/team` com semaforo, prazo e base, com dados ficticios do seed | regravar quando a tela mudar; depende das branches de roteamento, aviso de seguranca, fila, seed, textos da UI e `/team` | revisao humana |
| Intake de solucoes de IA (inventario) | ⬜ | formato da ficha | formulario, modelo de dados e fila de revisao | — |
| Relatorio mensal para a fiscalizacao | ✅ | `GET /web/support/reports/monthly.csv` e "Baixar CSV" na `/team`: um caso por linha, prazo gravado na abertura (`sla_minutes`/`sla_basis`, migration 020), resultado contra o prazo com pausas descontadas, `late_reason` obrigatorio ao fechar atrasado (lista fechada); sem dado pessoal; `;` e BOM para Excel pt-BR | revisar colunas e motivos com a fiscalizacao real | `tests/test_monthly_report.py`, `tests/integration/test_monthly_report_postgres.py` |
| Superficies herdadas fora do nucleo | ✅ | removidos a rota `/zoom` (bot de reuniao via Recall.ai, `RECALL_API_KEY`, `ZOOM_WEBHOOK_SECRET`), o atalho de checkout com link de pagamento (`DomainCheckoutConfig`) e o contrato documentado de `/web/fontesan/leads`, que nao existe neste repositorio; `rate_limit_exceeded` registra so `client_host_hash` | — | `tests/test_auth.py`, `tests/test_rate_limit.py` |
| Lint na CI | ✅ | `ruff check app tests scripts` no job de CI, regras de correcao (`E4`, `E7`, `E9`, `F`) em `pyproject.toml` | ampliar as regras aos poucos; sem checagem de tipos | CI |
| Detector de CPF com digito verificador | ✅ | `[REDACTED_CPF]` (mascara sempre; 11 digitos so com digito verificador), datas ISO e protocolos rotulados preservados, `REDACTION_VERSION` `phase0-v2` com leitura de `phase0-v1` | protocolo sem rotulo continua mascarado (limite aceito) | `tests/test_pii_cpf.py`, `tests/test_pii_card.py` |

## Limites conhecidos (sem correcao nesta copia)

Detalhe em `docs/ficha-do-sistema.md` ("Limites conhecidos").

- O campo `to` do `operational_outbox.payload_sanitized` guarda o telefone em claro; nao ha purga do outbox.
- O cookie de lembrete do operador carrega o telefone E.164 em claro (`app/support/staff_auth.py:14-19`).
- `lgpd-titular` nao declara `low_minutes` no bloco `sla`: um caso `low` cairia no
  SLA global de 24h (`SUPPORT_SLA_MINUTES_LOW`, `app/support/sla.py:160`), mais
  curto que o `normal` de 15 dias. Latente: nenhuma regra do dominio usa `low`
  hoje e o padrao sem regra e `normal`.

## Herdado do nucleo (sem mudanca nesta copia)

API FastAPI, retrieval lexical e pgvector, providers OpenAI e Anthropic com
fallback, handoff com taxonomia, ticket duravel, console com transicoes
auditadas, OTP via WhatsApp com consentimento, persistencia sanitizada,
readiness, transporte Meta WhatsApp e Hermes (desligados por padrao).

Mais detalhes em `docs/documentation-status.md`.
