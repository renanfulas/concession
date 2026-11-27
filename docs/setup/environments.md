# Mapa Oficial de Ambientes

Este documento define qual ambiente vale como referencia oficial para banco, pgvector, runtime e integracoes externas do `supportFAQagent`.

## Objetivo

Eliminar ambiguidade entre laboratorio local, ambientes externos nao oficiais e o ambiente oficial do projeto antes de ligar o backend ao PostgreSQL + pgvector.

## Regra principal

- Cada ambiente do `supportFAQagent` deve ter um PostgreSQL oficial.
- O backend deve acessar o banco apenas via `DATABASE_URL`.
- O `pgvector` fica no mesmo PostgreSQL da aplicacao, nao em banco separado.
- Nenhum segredo real deve aparecer em Git, PR, docs ou conversa.
- Credenciais ja expostas devem ser tratadas como comprometidas e rotacionadas.

## Ambientes

### Local dev

- Tipo: laboratorio de desenvolvimento e validacao tecnica.
- Banco: Docker com `pgvector/pgvector:pg16` ou PostgreSQL/pgvector
  descartavel em WSL1 quando virtualizacao nao estiver disponivel.
- Uso esperado:
  - validar o runner e migrations `001-008`
  - validar extensoes `vector` e `pgcrypto`
  - validar expand/contract, concorrencia, privacidade e readiness
  - validar inserts, query top-k e scripts em `tests/db/`
- Status: descartavel, pode ser recriado sem impacto operacional.

### Staging (a definir)

- Tipo: ambiente de homologacao quando houver um host corporativo definido.
- Banco: PostgreSQL com `pgvector` no mesmo banco da aplicacao.
- Retrieval default sugerido: `RETRIEVAL_BACKEND=pgvector`, com rollback para
  `RETRIEVAL_BACKEND=lexical` sem apagar dados.
- Valores recomendados para o chat publico:
  - `ENABLE_PUBLIC_CHAT_UI=true`
  - `ENABLE_CHAT_UI=false`
  - `WEB_CHAT_COOKIE_SECURE=true`
  - `WEB_CHAT_RATE_LIMIT_PER_MINUTE=10` como ponto inicial
- Status: nao provisionado nesta demo. O nucleo herdado ja operou em staging
  real (pgvector como default, readiness e smoke privados); esta copia roda
  localmente.

### Integracoes externas futuras

- Tipo: consumidores externos opcionais da API do backend.
- Interface oficial:
  - `POST /chat`
  - `POST /feedback`
  - futuros contratos HTTP do backend
- Regras:
  - deve preservar `X-Request-ID`, `request_id`, `handoff_reasons`, `references` e `error_code`
  - nao deve acessar diretamente as tabelas internas do RAG
  - nao deve carregar regra central de inteligencia
- Pode coexistir em Docker com `supportfaq_api`, desde que seja um servico
  separado e reversivel.
- `n8n` foi removido do projeto e nao faz parte do plano operacional do MVP.
- Desabilitar temporariamente a API nao deve apagar o PostgreSQL/pgvector nem os
  dados de qualquer consumidor externo futuro.

### Website chat publico

- Tipo: superficie publica controlada para a V0 do website.
- Interface oficial:
  - `POST /web/chat`
  - `POST /web/feedback`
- Regras:
  - nao envia `X-API-Key` pelo navegador
  - usa sessao anonima por cookie `HttpOnly`
  - em staging e producao, o cookie deve sair com `Secure=true`
  - nao escolhe `domain` livremente no V0; com `ENABLE_WEB_DOMAIN_ROUTER=true`
    (padrao) o backend roteia cada mensagem entre `WHATSAPP_ROUTER_DOMAINS`,
    com `false` responde sempre `DEFAULT_DOMAIN` (`concessoes-manutencao`)
  - preserva `X-Request-ID`, `request_id`, `handoff_reasons`, `references` e `error_code`
  - deve ficar atras de rate limit publico
  - `ENABLE_PUBLIC_CHAT_UI=true` e a flag explicita para expor a `chat-ui` fora do modo de desenvolvimento
- Tela da fila do time (`/team`, somente leitura):
  - `ENABLE_TEAM_UI` vazio liga a tela so em desenvolvimento; `true`/`false` explicito vale em qualquer ambiente
  - os dados continuam atras de `ENABLE_SUPPORT_CONSOLE` e da sessao staff; sem eles a tela mostra "Console indisponivel"
  - `ENABLE_TEAM_DEV_LOGIN=true` (padrao `false`) mostra "Entrar como atendente de demonstracao" na tela de login: sessao do operador ficticio do seed, sem OTP. A aplicacao nao sobe com a flag sem `APP_ENV=development` explicito (herdar o padrao nao vale); cada pedido exige peer TCP e `Host` de loopback e nenhum header de proxy (`Forwarded`, `X-Forwarded-*`, `X-Real-IP`, `Via`), senao `404`
- Baseline recomendado de hardening:
  - `WEB_CHAT_RATE_LIMIT_PER_MINUTE=10`
  - nome de cookie por ambiente, por exemplo `sfaq_web_session_staging`
  - reverse proxy com HTTPS obrigatorio antes de liberar acesso externo
- Status: pronto para validacao controlada da V0; nao substitui integracoes WhatsApp ou atendimento humano

## Responsabilidades por frente

- Renan: schema SQL, migrations, query vetorial, persistencia real, contratos,
  testes do backend, seguranca e integracao com `/chat`.
- Provisionamento oficial, runtime, secrets, conectividade, snapshots
  e recuperacao.

## Validacao esperada

Para gate de SQL e pgvector, usar ambiente deterministico sem depender de
provider real. Migrations novas devem ser aplicadas pelo runner, nao por
execucao manual isolada:

```powershell
python -m scripts.migrate status
python -m scripts.migrate apply --target 006_conversations_messages.sql
python -m scripts.backfill_conversation_privacy --verify-contract-ready
python -m scripts.migrate apply
python -m scripts.migrate verify
psql $env:DATABASE_URL -f tests/db/test_01_extensions.sql
psql $env:DATABASE_URL -f tests/db/test_02_schema.sql
psql $env:DATABASE_URL -f tests/db/test_03_idempotency.sql
psql $env:DATABASE_URL -f tests/db/test_04_vector_search.sql
psql $env:DATABASE_URL -f tests/db/test_05_isolation.sql
psql $env:DATABASE_URL -f tests/db/validate_pgvector_search.sql
```

Os domain evals usados como gate desta frente devem rodar com fallback deterministico, nao com provider real bloqueando a validacao de banco:

```powershell
python -m pytest
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

## Proximo encaixe

1. Preparar logs, alertas, snapshot e restore isolado.
2. Manter readiness, smoke privado e gate pgvector como
   validacoes recorrentes do staging.
3. Consumidores externos futuros devem consumir a API HTTP, nunca o banco do
   agente.
