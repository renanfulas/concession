# Demo publica (subdominio do portfolio)

Como colocar o concession no ar como demonstracao publica, por exemplo em
`concession.renanfulas.com.br`, na mesma VPS do portfolio (Ubuntu 22.04,
Caddy). Arquivos em `deploy/public-demo/`.

> **E uma demo, nao um atendimento.** Contrato, prazos, ativos e casos sao
> ficticios. Qualquer visitante entra na `/team` como o operador ficticio do
> seed e ve todos os casos, inclusive os abertos por outros visitantes. Por
> isso o chat avisa para nao enviar dados pessoais reais, o texto e mascarado
> antes de gravar e o banco e recriado todo dia.

## O que fica no ar

| Caminho | O que e |
| --- | --- |
| `/` | redireciona para `/chat-ui/` |
| `/chat-ui/` | tela do cidadao (defeito, risco a pessoas, pedido LGPD) |
| `/team/`, `/team/intake` | fila do time e intake de solucoes de IA, com o botao de entrada da demo |
| `/web/*` | APIs que as duas telas usam |
| `/health` | liveness |

O Caddy bloqueia o resto (`/chat`, `/domains`, `/ingestion`, `/internal`,
`/integrations`, `/docs`, `/openapi.json`) com `404`.

## Travas

- `ENABLE_PUBLIC_DEMO_LOGIN=true` libera o login do operador ficticio atras do
  proxy (`app/support/dev_login.py`). A aplicacao **nao sobe** com a flag sem
  `PERSISTENCE_BACKEND=postgres` e `ENABLE_SUPPORT_CONSOLE=true`, ou com
  qualquer canal de saida ligado: WhatsApp (Meta, Hermes, OTP web, aviso ao
  time, numero de suporte), outbox ingress, arquivo de conversas, webhooks
  verificados e transporte de OTP diferente de `memory`
  (`Settings._require_public_demo_isolation`, `tests/test_public_demo.py`).
- O dispatcher do outbox (`scripts/dispatch_outbox.py`) **nunca** roda na demo.
  O reset diario apaga o que o `record_chat` enfileira.
- Banco dedicado (`concession_demo`), so em `127.0.0.1`, sem outra aplicacao.
- Um worker do uvicorn com `--proxy-headers`: o rate limit do chat
  (`WEB_CHAT_RATE_LIMIT_PER_MINUTE=6`) vale por IP real do visitante, e o log
  guarda so o hash do IP. O access log do uvicorn fica desligado
  (`--no-access-log`): com `--proxy-headers` ele gravaria esse IP em claro.
  Conferir depois de cada mudanca na unidade:
  `journalctl -u concession-demo --since "-10 min" | grep -cE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:'`
  deve dar `0`.
- LLM: a chave fica so em `/etc/concession-demo/demo.env`, colocada pelo dono
  da conta. Antes de colocar, configure um limite de gasto no projeto da OpenAI.
  Sem chave, a demo continua classificando, priorizando, dando prazo e o aviso
  de seguranca; so o texto vira o fallback seguro.
- Systemd com sandbox (`ProtectSystem=strict`, sem capabilities, sem home).

## Primeira instalacao (root na VPS)

1. **DNS**: registro `A` de `concession` para o IP da VPS. Conferir com
   `nslookup concession.renanfulas.com.br` antes de mexer no Caddy (o Caddy
   tenta emitir o certificado assim que o bloco entra).
2. **Pacotes** (Python 3.11 e PostgreSQL 16 com pgvector, repositorios
   oficiais):

   ```bash
   add-apt-repository -y ppa:deadsnakes/ppa
   install -d /usr/share/postgresql-common/pgdg
   curl -fsSo /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
     https://www.postgresql.org/media/keys/ACCC4CF8.asc
   echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
     https://apt.postgresql.org/pub/repos/apt jammy-pgdg main" \
     > /etc/apt/sources.list.d/pgdg.list
   apt-get update
   apt-get install -y python3.11 python3.11-venv postgresql-16 postgresql-16-pgvector
   ```

   O PostgreSQL do Ubuntu escuta so em `localhost` por padrao; confira
   `listen_addresses` em `/etc/postgresql/16/main/postgresql.conf`.
3. **Usuario e pastas**:

   ```bash
   useradd --system --no-create-home --shell /usr/sbin/nologin concession-demo
   install -d -m 755 /opt/concession-demo /opt/concession-demo/releases /opt/concession-demo/bin
   install -d -m 700 /etc/concession-demo
   ```

4. **Papel e banco** com senha gerada na hora (nunca ecoada). As extensoes
   exigem superusuario; a migration 001 usa `IF NOT EXISTS`:

   ```bash
   db_password="$(openssl rand -hex 24)"
   runuser -u postgres -- psql --quiet \
     --command "CREATE ROLE concession_demo LOGIN PASSWORD '$db_password'"
   runuser -u postgres -- createdb --owner concession_demo concession_demo
   runuser -u postgres -- psql --quiet --dbname concession_demo \
     --command 'CREATE EXTENSION IF NOT EXISTS pgcrypto' \
     --command 'CREATE EXTENSION IF NOT EXISTS vector'
   ```

5. **Ambiente**: copiar `deploy/public-demo/demo.env.example` para
   `/etc/concession-demo/demo.env` (`chmod 600`), trocar a senha do banco pela
   `$db_password` e cada `<gerar>` por um `openssl rand -hex 32` diferente.
   A `OPENAI_API_KEY` o dono da conta coloca a mao.
6. **Scripts e unidades**:

   ```bash
   install -m 755 deploy/public-demo/release.sh deploy/public-demo/reset-demo.sh \
     deploy/public-demo/migrate-demo.sh /opt/concession-demo/bin/
   install -m 644 deploy/public-demo/concession-demo.service \
     deploy/public-demo/concession-demo-reset.service \
     deploy/public-demo/concession-demo-reset.timer /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable concession-demo concession-demo-reset.timer
   ```

7. **Primeira release e seed**: gerar o tarball no repositorio
   (`git archive --format=tar.gz -o concession-<id>.tar.gz HEAD`), enviar para
   `/tmp`, rodar `/opt/concession-demo/bin/release.sh /tmp/concession-<id>.tar.gz <id>`
   (cria o venv, aplica as migrations na ordem da CI com `migrate-demo.sh`,
   liga o servico e confere `/health`) e depois
   `systemctl start concession-demo-reset` para carregar os casos do seed.
8. **Caddy**: copia datada do Caddyfile em `/etc/caddy/backups/`, colar
   `deploy/public-demo/Caddyfile.snippet` no fim, `caddy validate --config
   /etc/caddy/Caddyfile --adapter caddyfile` e `systemctl reload caddy` so se
   for valido. Se o reload falhar, restaurar a copia.
9. **Conferir**: `https://concession.renanfulas.com.br/` abre o chat; a `/team`
   mostra "Entrar" e, depois, a fila com os 13 casos do seed; mandar "fio
   exposto" no chat abre um caso urgente na fila.

## Nova release

```bash
git archive --format=tar.gz -o concession-<id>.tar.gz HEAD   # no repositorio
scp concession-<id>.tar.gz <vps>:/tmp/
/opt/concession-demo/bin/release.sh /tmp/concession-<id>.tar.gz <id>   # root na VPS
```

O `release.sh` cria um venv proprio da release, aplica as migrations
(`migrate-demo.sh`), troca o
link `current` de forma atomica, reinicia e confere `/health`; se falhar, volta
para a release anterior.

## Reset

O timer `concession-demo-reset` roda todo dia as 04:00 de Sao Paulo. Para
rodar na hora: `systemctl start concession-demo-reset`. Logs:
`journalctl -u concession-demo -u concession-demo-reset`.

## Desligar

`systemctl disable --now concession-demo concession-demo-reset.timer`, tirar o
bloco do Caddyfile (com backup e `caddy validate`) e, se quiser, apagar o banco
(`runuser -u postgres -- dropdb concession_demo`).
