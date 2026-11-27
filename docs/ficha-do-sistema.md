# Ficha do sistema de IA — concession

Formato de inventario de solucoes de IA: o que o sistema faz, quem responde,
que dado pessoal trata, com que base legal, quao critico e, quais controles
existem e quais limites sao conhecidos. Versao em ingles:
[system-card.md](system-card.md).

> Ambiente de demonstracao. Responsaveis, base legal e prazos abaixo
> descrevem como a ficha seria preenchida numa operacao real; contrato,
> ativos e aviso de privacidade usados pelo sistema sao ficticios.

## Identificacao

| Campo | Valor |
| --- | --- |
| Nome | concession (atendimento de manutencao e privacidade) |
| Tipo | assistente com RAG e escalonamento humano; nao toma decisao final |
| Area de negocio | Operacoes de manutencao; Encarregado de dados (DPO) |
| Dono tecnico | TI (desenvolvimento de IA) |
| Dono de negocio | Operacoes (dominio de manutencao) e Encarregado (dominio LGPD) |
| Fornecedor de modelo | OpenAI (`gpt-4o-mini`) ou Anthropic, configuravel por dominio; embeddings `text-embedding-3-small` |
| Hospedagem | API Python (FastAPI) + PostgreSQL/pgvector em infraestrutura propria |
| Canais | WhatsApp (Meta Cloud API, desligado por padrao) e chat web |
| Status | demonstracao; nao ha uso em producao |

## O que faz e o que nao faz

Faz:

- responde perguntas recorrentes com base em conhecimento versionado, citando a fonte
- classifica o pedido por regras declaradas no dominio e abre caso com prioridade
- aplica o prazo do dominio (contrato ou LGPD) no semaforo do console do time

Nao faz:

- executar exclusao, correcao ou exportacao de dados pessoais
- decidir sobre multa, penalidade ou interpretacao de contrato
- identificar pessoas, usar imagem ou reconhecimento facial
- fechar caso sem uma pessoa do time

## Dados pessoais tratados

| Dado | Onde | Tratamento | Base legal (LGPD art. 7) |
| --- | --- | --- | --- |
| Numero de telefone | identidade do canal, OTP | guardado como hash (HMAC) e ultimos 4 digitos; numero completo so quando o cidadao autoriza contato | execucao do contrato de concessao / politica publica; legitimo interesse |
| Texto das mensagens | conversas e tickets | mascarado antes de persistir (cartao, CNPJ, e-mail, telefone, IP); `app/core/persistence_sanitize.py` | idem |
| Identificador de sessao | historico curto | so o hash vai para banco e log | idem |
| Codigo OTP | verificacao de identidade | so o digest; expira | cumprimento de obrigacao legal (atender o titular com seguranca) |
| Codigo do ativo e endereco | ticket de manutencao | dado operacional, nao pessoal | — |

Dados sensiveis (art. 11): nao sao coletados. Dados de criancas: nao sao coletados de proposito.

Transferencia internacional: o texto mascarado da pergunta (o mesmo mascaramento
da persistencia) e o contexto recuperado vao ao provedor de LLM e de embeddings. Numa operacao real, isso exige clausula
contratual com o fornecedor e registro no inventario (art. 33).

## Criticidade

| Dimensao | Avaliacao | Por que |
| --- | --- | --- |
| Impacto de erro na resposta | medio | resposta errada pode informar prazo errado; mitigado porque o prazo do console vem do `domain.yaml`, nao do texto do LLM |
| Impacto de erro na classificacao | medio-alto | classificar risco a pessoas como limpeza atrasa o atendimento; mitigado por evals com `required_handoff_reasons` e por escalonamento sempre humano |
| Dado pessoal | baixo-medio | telefone e texto livre, mascarados antes de persistir |
| Autonomia | baixa | todo pedido que exige acao vira caso para uma pessoa |
| Exposicao publica | alta | canal aberto ao cidadao; rate limit, confinamento e fallback seguro |

Classificacao sugerida: **risco medio**, com revisao humana obrigatoria.

## Controles

| Controle | Onde | Evidencia |
| --- | --- | --- |
| Confinamento de escopo, prompt e segredo | `docs/security/llm-confinement.md`, `domains/*/evals/confinement/` | evals de confinamento 33/33 |
| Classificacao testada | `domains/*/evals/cases.yaml` (`required_handoff_reasons`) | evals base 20/20 nos dois dominios |
| Prazo deterministico | `domain.yaml` bloco `sla`, `app/support/sla.py` | `tests/test_support_sla.py`, `tests/test_concessoes_domain.py` |
| Mascaramento antes de persistir | `app/core/persistence_sanitize.py` | `tests/test_pii_card.py`, `tests/test_privacy.py` |
| Mascaramento antes do provedor | a pergunta passa pelo mesmo mascaramento antes da consulta de embeddings e do prompt do LLM; a deteccao local (cartao, segredo) usa o texto original | `tests/test_provider_masking.py` |
| Logs sem PII, token ou `session_id` bruto | `app/core/logging.py`, `docs/architecture/observability.md` | `tests/test_observability_hardening.py` |
| Consentimento antes de contato direto | gate de consentimento no ticket | testes de handoff web |
| Rastreabilidade | `request_id` em toda resposta; eventos de caso auditados | `tests/test_request_observability.py` |
| Fallback seguro | provider ou retrieval falha -> resposta padrao e escalonamento | `tests/test_chat_flow_errors.py` |
| Desenvolvimento com agente de IA | `CLAUDE.md`, `.agents/skills/`, trailer de coautoria, testes e evals antes do commit | historico de commits |

## Limites conhecidos

- Sem chave de LLM, os evals validam retrieval, classificacao e escalonamento, mas nao a qualidade do texto gerado.
- Classificacao por termos (substring): sinonimos nao previstos caem em `low_confidence` e vao para uma pessoa; isso e seguro, mas pode gerar fila.
- CPF nao tem detector proprio com digito verificador.
- A gravacao da prioridade no PostgreSQL real nao foi verificada nesta copia.
- Nao existe tela web do console; o console e uma API.

## Revisao

| Data | Quem | O que |
| --- | --- | --- |
| 2026-11-26 | TI (desenvolvimento de IA) | primeira versao da ficha |
