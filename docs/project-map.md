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
| Dominio `lgpd-titular` | ✅ | aviso de privacidade ficticio, direitos (art. 18), prazos (art. 19, II para acesso; art. 18, §5º para exclusao e correcao, com 15 dias como meta interna demo), 4 regras com prioridade | revisao do texto pelo encarregado real; `basis` do SLA ainda cita so o art. 19, II | evals base 10/10, confinamento 16/16 |
| SLA por dominio (`sla:` no `domain.yaml`) | ✅ | override por prioridade, `basis` na resposta do console, lista, detalhe e metricas | — | `tests/test_support_sla.py`, `tests/test_web_support_console.py` |
| Prioridade do caso por regra | ✅ codigo · 🟡 banco | `escalation_rules[].priority`, `resolve_case_priority`, coluna `priority` no INSERT | rodar a suite de integracao PostgreSQL (`docker-compose.test.yml`) para provar o INSERT | `tests/test_concessoes_domain.py`; integracao nao rodada nesta copia |
| Evals com `required_handoff_reasons` | ✅ | o eval exige o motivo certo, nao so a ausencia de motivo errado | — | evals dos dois dominios |
| Roteamento manutencao x privacidade | ✅ | saudacao e esclarecimento novos, empate cai no menu | — | `tests/test_domain_router.py` |
| Ficha do sistema (PT/EN) | ✅ | `docs/ficha-do-sistema.md`, `docs/system-card.md`, alinhadas ao codigo (dados guardados, pergunta crua ao provedor, bases legais como raciocinio demo) | confirmar bases legais com o encarregado real | revisao humana |
| Mascarar a pergunta antes do provedor de LLM/embeddings | ⬜ | so higiene de entrada (`app/core/sanitize.py`); mascaramento so na persistencia | aplicar o mascaramento antes de `retrieve` e `build_prompt` em `app/orchestration/chat_flow.py` | — |
| Tela web do console (`/team`) | ⬜ | API do console pronta (`/web/support/*`) | tela para o time ver a fila e o semaforo | — |
| Intake de solucoes de IA (inventario) | ⬜ | formato da ficha | formulario, modelo de dados e fila de revisao | — |
| Relatorio mensal para a fiscalizacao | ⬜ | metricas do console | exportacao por categoria e prazo | — |
| Detector de CPF com digito verificador | ⬜ | mascaramento de cartao, CNPJ, e-mail, telefone, IP | CPF explicito (hoje provavelmente cai na regra de telefone) | — |

## Limites conhecidos (sem correcao nesta copia)

Detalhe em `docs/ficha-do-sistema.md` ("Limites conhecidos").

- A pergunta vai crua ao provedor de embeddings e de LLM (`app/orchestration/chat_flow.py:209`, `:270-272`).
- `rate_limit_exceeded` registra o IP do cliente em claro (`app/main.py:127`, `:162`).
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
