# Ficha do sistema de IA — concession

Formato de inventario de solucoes de IA: o que o sistema faz, quem responde,
que dado pessoal trata, com que base legal, quao critico e, quais controles
existem e quais limites sao conhecidos. Versao em ingles:
[system-card.md](system-card.md).

> Ambiente de demonstracao. Responsaveis, base legal e prazos abaixo
> descrevem como a ficha seria preenchida numa operacao real; contrato,
> ativos e aviso de privacidade usados pelo sistema sao ficticios.

## Identificacao

> Exemplo de preenchimento (demo). Donos, area e hospedagem abaixo mostram o
> formato esperado; nao descrevem uma organizacao real.

| Campo | Valor |
| --- | --- |
| Nome | concession (atendimento de manutencao e privacidade) |
| Tipo | assistente com RAG e escalonamento humano; nao toma decisao final |
| Area de negocio | Operacoes de manutencao; Encarregado de dados (DPO) — exemplo (demo) |
| Dono tecnico | TI (desenvolvimento de IA) — exemplo (demo) |
| Dono de negocio | Operacoes (dominio de manutencao) e Encarregado (dominio LGPD) — exemplo (demo) |
| Fornecedor de modelo | OpenAI (`gpt-4o-mini`) ou Anthropic, configuravel por dominio; embeddings `text-embedding-3-small` |
| Hospedagem | API Python (FastAPI) + PostgreSQL/pgvector; local de hospedagem a definir — exemplo (demo) |
| Canais | WhatsApp (Meta Cloud API, desligado por padrao) e chat web |
| Status | demonstracao; nao ha uso em producao |

## O que faz e o que nao faz

Faz:

- responde perguntas recorrentes com base em conhecimento versionado e devolve as fontes recuperadas (`references`)
- classifica o pedido por regras declaradas no dominio e abre caso com prioridade
- aplica o prazo do dominio (contrato ou LGPD) no semaforo do console do time

Nao faz:

- executar exclusao, correcao ou exportacao de dados pessoais
- decidir sobre multa, penalidade ou interpretacao de contrato
- identificar pessoas, usar imagem ou reconhecimento facial
- fechar caso sem uma pessoa do time

## Dados pessoais tratados

> As bases legais abaixo sao raciocinio de demonstracao, nao parecer
> juridico. Numa operacao real, cada base precisa ser confirmada pelo
> encarregado (DPO) e pelo juridico. O contrato de concessao e firmado com o
> poder concedente, nao com o cidadao, por isso nao serve de base para os
> dados do cidadao (art. 7, V).

| Dado | Onde | Tratamento | Base legal (LGPD art. 7) — demo |
| --- | --- | --- | --- |
| Numero de telefone do cidadao | identidade do canal, OTP | guardado como hash (HMAC) e ultimos 4 digitos; o numero completo aparece nas linhas "`wa_id`" e "telefone de destino" abaixo | legitimo interesse (art. 7, IX) ou execucao de politica publica (art. 7, III); a confirmar pelo encarregado real |
| Texto das mensagens | conversas e tickets | mascarado antes de persistir (CPF com digito verificador, cartao, e-mail, telefone e demais sequencias longas de digitos, IP); datas ISO e protocolos rotulados ficam legiveis para a trilha de auditoria; `app/core/persistence_sanitize.py`. O mesmo mascaramento vale antes do provedor de LLM (ver "Transferencia internacional") | idem |
| Identificador de sessao | historico curto | so o hash vai para banco e log | idem |
| Codigo OTP | verificacao de identidade | so o digest; expira | cumprimento de obrigacao legal (art. 7, II: atender o titular com seguranca) |
| Nome e e-mail do cidadao | `customers.display_label` e `customers.email` (migration 013, `app/db/operational.py:634-642` e `:690-696`); texto do alerta ao time | informados no gate de consentimento do handoff web; nome passa por `sanitize_for_persistence`; e-mail validado por formato e guardado legivel porque o time usa para contato | consentimento (art. 7, I), colhido no gate de consentimento |
| `wa_id` (telefone E.164) por caso | `case_whatsapp_bindings` (migration 016, `app/support/wa_binding.py`) | cifrado de forma **reversivel** (Fernet, chave `SUPPORT_WA_ENC_KEY`) mais HMAC para busca; apagado quando o caso fecha ou e cancelado, ou apos `SUPPORT_WA_BINDING_MAX_DAYS` (padrao 15 dias) | legitimo interesse (art. 7, IX) ou execucao de politica publica (art. 7, III); a confirmar |
| Telefone de destino (cidadao e membros do time) | campo `to` do `operational_outbox.payload_sanitized` (`app/support/whatsapp_bridge.py:243-252`; `app/db/operational.py:556-558`) | gravado **em claro**, apesar do nome da coluna, para o dispatcher entregar a mensagem; nao ha rotina de purga do outbox no codigo | idem (cidadao); legitimo interesse (art. 7, IX) para o telefone do time |
| Telefone E.164 do operador do time | cookie HttpOnly de lembrete `<token>.<E.164>` no navegador do operador (`app/support/staff_auth.py:14-19`, `:118`) | o banco guarda so o HMAC do token; o telefone fica em claro no cookie do proprio operador | legitimo interesse (art. 7, IX): gestao de acesso do time |
| Endereco IP do cliente | log `rate_limit_exceeded` (`app/main.py`, middleware de `/chat` e `/web/chat`) | so o HMAC SHA-256 truncado (`client_host_hash`, chave `PERSISTENCE_HASH_SECRET`); o IP em claro nao vai para o log | legitimo interesse (art. 7, IX): seguranca do canal; a confirmar |
| Nome e papel do responsavel por uma solucao de IA | `ai_solutions.owner_name` e `owner_role` (migration 021, intake de solucoes de IA) | dado de funcionario, informado por quem submete; sem e-mail, telefone ou documento; aparece na ficha e no inventario CSV, que exigem sessao staff | legitimo interesse (art. 7, IX): governanca do uso de IA; a confirmar |
| Texto livre do intake (finalidade, notas, condicoes) | `ai_solutions`, `ai_solution_events.note_sanitized` | mascarado por `sanitize_for_persistence` antes de gravar; fora dos logs | idem |
| Codigo do ativo e endereco | ticket de manutencao | dado operacional, nao pessoal | — |

Dados sensiveis (art. 11): nao sao coletados. Dados de criancas: nao sao coletados de proposito.

Transferencia internacional: a pergunta passa pelo mesmo mascaramento da
persistencia antes de ir ao provedor de embeddings (consulta pgvector) e ao
provedor de LLM, junto com o contexto recuperado (`app/orchestration/chat_flow.py`;
a deteccao local de cartao e segredo usa o texto original). Numa operacao real,
isso exige clausula contratual com o fornecedor e registro no inventario (art. 33).

## Criticidade

| Dimensao | Avaliacao | Por que |
| --- | --- | --- |
| Impacto de erro na resposta | medio | resposta errada pode informar prazo errado; mitigado porque o prazo do console vem do `domain.yaml`, nao do texto do LLM |
| Impacto de erro na classificacao | medio-alto | classificar risco a pessoas como limpeza atrasa o atendimento; mitigado por evals com `required_handoff_reasons` e por escalonamento sempre humano |
| Dado pessoal | medio | telefone, nome, e-mail e texto livre; o texto e mascarado antes de persistir e antes do provedor; o telefone fica em claro no outbox |
| Autonomia | baixa | todo pedido que exige acao vira caso para uma pessoa |
| Exposicao publica | alta | canal aberto ao cidadao; rate limit, confinamento e fallback seguro |

Classificacao sugerida: **risco medio**, com revisao humana obrigatoria.

## Controles

| Controle | Onde | Evidencia |
| --- | --- | --- |
| Confinamento de escopo, prompt e segredo | `docs/security/llm-confinement.md` (secao dos dominios da concessao), `domains/*/evals/confinement/` | evals de confinamento cobrem 33 casos (17 manutencao, 16 LGPD), todos passando |
| Classificacao testada | `domains/*/evals/cases.yaml` (`required_handoff_reasons`) | evals base cobrem 36 casos (21 manutencao, 15 LGPD), incluindo casos negativos (termo presente com outro sentido, negado ou no meio de outra palavra), todos passando |
| Prazo deterministico | `domain.yaml` bloco `sla`, `app/support/sla.py` | `tests/test_support_sla.py`, `tests/test_concessoes_domain.py` |
| Orientacao de seguranca fixa | `escalation_rules[].notice` no `domain.yaml`, aplicada em `ChatFlowService.answer` | `tests/test_rule_notices.py`; evals exigem "ligue 193", "nunca pede senha", "4 horas" (incidente) e "24 horas" (fiscalizacao) mesmo sem LLM |
| Login de desenvolvimento restrito a maquina local | `ENABLE_TEAM_DEV_LOGIN` (padrao `false`), `app/support/dev_login.py`: nao sobe sem `APP_ENV=development` explicito; exige peer e `Host` de loopback; recusa headers de proxy | `tests/test_team_dev_login.py` |
| Demo publica isolada | `ENABLE_PUBLIC_DEMO_LOGIN` (padrao `false`): libera o login do operador ficticio para qualquer visitante, mas a aplicacao nao sobe sem PostgreSQL dedicado e console, nem com canal de saida ligado (WhatsApp, Hermes, OTP, aviso ao time, outbox ingress, arquivo de conversas, webhooks verificados); banco recriado todo dia e dispatcher do outbox nunca roda (`docs/runbooks/public-demo.md`) | `tests/test_public_demo.py` |
| Relatorio mensal sem dado pessoal | `app/support/monthly_report.py`, `GET /web/support/reports/monthly.csv` (sessao staff) | `tests/test_monthly_report.py` (sem coluna de telefone, nome, e-mail, resumo ou `request_id`; injecao de formula neutralizada) |
| Motivo de atraso em lista fechada | `late_reason` obrigatorio ao fechar depois do prazo; `CHECK` no banco, sem texto livre | `tests/test_monthly_report.py`, `tests/integration/test_monthly_report_postgres.py` |
| Mascaramento antes de persistir | `app/core/persistence_sanitize.py` | `tests/test_pii_card.py`, `tests/test_pii_cpf.py`, `tests/test_privacy.py` |
| Mascaramento antes do provedor | a pergunta passa pelo mesmo mascaramento antes da consulta de embeddings e do prompt do LLM; a deteccao local (cartao, segredo) usa o texto original | `tests/test_provider_masking.py` |
| Logs sem token ou `session_id` bruto; PII so nas excecoes listadas em "Limites conhecidos" | `app/core/logging.py`, `docs/architecture/observability.md` | `tests/test_observability_hardening.py` |
| Consentimento antes de contato direto | gate de consentimento no ticket | testes de handoff web |
| Rastreabilidade | `request_id` em toda resposta; eventos de caso auditados | `tests/test_request_observability.py` |
| Fallback seguro | provider ou retrieval falha -> resposta padrao e escalonamento | `tests/test_chat_flow_errors.py` |
| Intake de solucoes de IA com criticidade por regra | `governance/ai-intake.yaml` (demo), `app/ai_intake/`: criticidade deterministica, prazo gravado na submissao, separacao de funcoes (quem submete nao analisa), RIPD exigido para aprovar nivel alto, decisao com nota e motivo de lista fechada, trilha de eventos; `CHECK` no banco para as listas fechadas | `tests/test_ai_intake.py`, `tests/test_ai_intake_routes.py`, `tests/integration/test_ai_intake_postgres.py` |
| Desenvolvimento com agente de IA | `CLAUDE.md`, `.agents/skills/`, trailer de coautoria, testes e evals antes do commit | historico de commits |

## Limites conhecidos

- Na demo publica (`ENABLE_PUBLIC_DEMO_LOGIN`), todo visitante ve na `/team` as mensagens que outros visitantes mandaram no chat, ja mascaradas. O chat avisa para nao enviar dado pessoal real e o banco e recriado todo dia, mas o texto livre que escapar do mascaramento fica visivel ate o reset.
- O campo `to` do `operational_outbox.payload_sanitized` guarda o telefone em claro, e nao ha purga do outbox no codigo.
- O cookie de lembrete do operador carrega o telefone E.164 em claro.
- O `basis` do SLA do dominio `lgpd-titular` cita o art. 19, II para todo `pedido_titular`, inclusive exclusao e correcao, cujo prazo segue regulamento (art. 18, §5º); os 15 dias sao meta interna nesses casos.
- Sem chave de LLM, os evals validam retrieval, classificacao e escalonamento, mas nao a qualidade do texto gerado.
- Classificacao por termos (inicio de palavra, `app/handoff/term_match.py`): o termo casa no inicio de uma palavra (`picha` cobre "picharam", mas `risco` nao casa em "arrisco"), aceita ate 2 palavras de conteudo no meio de um termo composto (codigo de ativo e palavra funcional nao contam: "relogio REL-0423 esta apagado") e ignora negacao simples logo antes, no meio ou logo depois do termo ("sem risco", "nao ha nenhum risco", "o painel nao esta apagado", "risco nenhum"). Continua deterministico e sem LLM. Limites: sinonimos nao previstos, mais de 2 palavras no meio ("o relogio da praca central ficou apagado") e negacao mais distante ou com outras palavras ("nao esta com a hora errada") nao sao reconhecidos. O erro na negacao vai para o lado seguro: quando a negacao nao e reconhecida, o caso e aberto com a prioridade do termo; quando o termo nao casa, a conversa cai em `low_confidence` e vai para uma pessoa, o que e seguro, mas pode gerar fila. Sentidos que a negacao nao cobre ("risco de multa", "tecnico atrasado") continuam em `ignore_terms` por regra; tudo isso e provado por casos negativos e positivos nos evals. O intervalo pode gerar falso positivo de prioridade alta ("outra vez a pessoa" casa `outra pessoa` no dominio LGPD), sempre no sentido de mandar para uma pessoa.
- Protocolo sem rotulo ("protocolo", "chamado", "ticket", "OS", "ordem de servico") ou com menos de 13 digitos continua mascarado: na duvida, o numero e tratado como dado pessoal. Protocolo que passa no algoritmo de cartao (Luhn) vira `[REDACTED_CARD]`.
- Limites conhecidos do mascaramento: telefone colado a letras (`telefone11...`) nao e pego; CNPJ formatado perde so a primeira parte; data de nascimento em formato ISO fica legivel (em dd/mm/aaaa ja ficava).
- A gravacao da prioridade no PostgreSQL real nao foi verificada nesta copia.
- Nao existe tela web do console; o console e uma API.
- Intake de solucoes de IA: nao ha papeis (toda pessoa da equipe do console pode revisar; a unica regra e a separacao de funcoes); prazo em dias corridos; a criticidade depende do que quem submete declara; sem anexos (o RIPD e so uma referencia) e sem notificacao.

## Revisao

| Data | Quem | O que |
| --- | --- | --- |
| 2026-11-26 | TI (desenvolvimento de IA) — exemplo (demo) | primeira versao da ficha |
| 2026-11-26 | agente de codigo, revisao humana pendente | dados, transferencia e limites alinhados ao codigo |
| 2026-11-27 | agente de codigo, revisao humana pendente | intake de solucoes de IA: dados do responsavel, controles e limites |
| 2026-11-27 | agente de codigo, revisao humana pendente | classificacao por inicio de palavra, intervalo curto e negacao simples; limite e contagem de evals atualizados |
