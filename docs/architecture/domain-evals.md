# Calibragem de Dominio

Evals sao casos pequenos que ajudam a medir se o agente esta respondendo e escalando como esperado para um dominio.

Eles nao substituem teste unitario. Eles servem como um termometro de produto.

## Onde ficam

```text
domains/
  suporte-vps-whatsapp/
    evals/
      cases.yaml
      pgvector_gate.yaml
      pgvector_curated.yaml
      intake/
```

## Como rodar

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp
```

Dominios da demo de concessao (manutencao do mobiliario urbano e canal do
titular LGPD). Alem do cenario base, cada um tem suites de confinamento:

```bash
python -m app.evals.run_domain_eval concessoes-manutencao
python -m app.evals.run_domain_eval lgpd-titular
python -m app.evals.run_domain_eval concessoes-manutencao --file evals/confinement/out_of_scope.yaml
python -m app.evals.run_domain_eval lgpd-titular --file evals/confinement/out_of_scope.yaml
```

Nesses dominios, `required_handoff_reasons` prova a classificacao: um defeito
com risco precisa levantar `risco_seguranca`, que abre caso `urgent`, e o
prazo do console sai do bloco `sla` do `domain.yaml`. Sem chave de LLM, o
provider cai no fallback seguro (`provider_error`): os evals continuam
validando retrieval, referencias, classificacao e escalonamento, mas nao a
qualidade do texto gerado pelo modelo.

Para suites dedicadas de confinamento:

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/confinement/out_of_scope.yaml
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/confinement/redefinition.yaml
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/confinement/secrets.yaml
```

Para a futura suite opt-in de calibragem com `pgvector` e provider real:

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_real.yaml
```

Para as suites atuais de calibragem com `pgvector`:

```bash
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_gate.yaml
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/pgvector_curated.yaml
```

Essa suite nao deve entrar como gate obrigatorio de CI enquanto depender de
`DATABASE_URL`, provider externo e dados ingeridos no pgvector.

Para a suite opt-in do recall de resumo (tiering Fase 4; precisa de provider
real e `ENABLE_SUMMARY_RECALL=true` — o resumo do caso e injetado pelo runner,
sem depender do warehouse):

```bash
ENABLE_SUMMARY_RECALL=true \
python -m app.evals.run_domain_eval suporte-vps-whatsapp --file evals/summary_recall.yaml
```

O comando retorna JSON com:

- total de casos
- quantidade aprovada
- quantidade com falha
- falhas por caso
- confianca
- motivos de escalonamento
- referencias usadas

## Contrato de um caso

```yaml
domain: suporte-vps-whatsapp
cases:
  - id: qrcode-whatsapp-nao-conecta
    category: operacao_whatsapp
    question: Quando tento conectar meu WhatsApp na Evolution, o QR Code nao abre.
    expectation:
      should_escalate: false
      required_terms:
        - mock provider
      expected_references:
        - qrcode-whatsapp.md
      allowed_handoff_reasons:
        - sensitive_topic
```

## Campos

- `id`: identificador curto e estavel.
- `category`: frente do produto, como `setup_tecnico`, `operacao_whatsapp`, `integracoes`.
- `question`: pergunta real ou adaptada de usuario.
- `customer_summary` (opcional): resumo de atendimentos anteriores injetado
  pelo runner como o resumo recuperado deste caso (formato
  `Problema: ... | Solucao: ... | Status: ...`). Exercita o caminho real do
  recall (`ENABLE_SUMMARY_RECALL` + bloco nao-confiavel do prompt) sem
  precisar de linha no warehouse. Ver `evals/summary_recall.yaml`.
- `should_escalate`: se o caso deve ir para humano.
- `required_terms`: termos que precisam aparecer na resposta.
- `forbidden_terms`: termos que NAO podem aparecer na resposta — e como um
  caso prova o lado negativo de um gate (ex.: canario de injecao dentro do
  resumo recuperado, assunto antigo que nao pode contaminar a resposta nova).
- `expected_references`: trechos esperados nas fontes recuperadas.
- `allowed_handoff_reasons`: motivos de escalonamento aceitos, quando aplicavel.
- `llm_expectation` (opcional): checagens usadas so pelo modo LLM real. O
  modo deterministico ignora este bloco. Ver
  [Modo LLM real](#modo-llm-real-opt-in-nao-e-gate).

## Como usar no MVP

No estado atual, os evals locais devem continuar deterministas e nao depender de provider real ou credenciais privadas. Por isso alguns casos validam comportamento estrutural:

- se recuperou a referencia correta
- se escalou quando deveria
- se manteve motivo de handoff esperado
- se preservou fallback seguro quando o provider real nao pode responder

Como o retrieval lexical ainda e simples, alguns casos podem esperar `low_confidence` mesmo quando ha documentos relacionados. Isso e uma linha de base do MVP, nao o comportamento final desejado.

Quando provider real e pgvector estiverem calibrados em ambiente privado, estes casos devem evoluir para validar conteudo mais forte sem quebrar o gate deterministico local.

## Modo LLM real (opt-in, nao e gate)

O modo padrao (`--provider-mode deterministic`) continua sendo o gate de CI.
Ele nunca chama provedor, mesmo com chave no `.env`: o `ChatFlowService` do
gate usa `OfflineLLMService` (`app/evals/runner.py`), que segue o mesmo
caminho de credencial ausente. Todo caso nao bloqueado termina em
`provider_error` e a resposta e o `provider_error_message` do dominio; o termo
`atendimento humano` exigido nos casos esta nesse texto. Por isso o modo
deterministico nao mede o texto do modelo, e uma chave invalida passaria nele.
Antes disso, uma chave no `.env` fazia o gate chamar o provedor em silencio:
manutencao caia para 1/13 e LGPD para 2/13, gastando credito
(`tests/test_domain_evals.py::test_deterministic_cli_never_builds_a_provider_even_with_a_key`).

O modo real mede o texto do modelo e nao pode ser enganado pelo fallback.
Comando (rode voce mesmo, com `OPENAI_API_KEY` no ambiente ou no `.env`):

```bash
python -m app.evals.run_domain_eval concessoes-manutencao lgpd-titular \
  --provider-mode real --runs 3 --report reports/eval-real.json
```

- Aceita varios dominios no mesmo relatorio; `--file` vale para todos.
- Sem chave do provider do dominio (`OPENAI_API_KEY` ou `ANTHROPIC_API_KEY`),
  aborta com codigo de saida 3 antes de chamar qualquer coisa. So a presenca
  da chave e verificada; o valor nunca e impresso.
- Saida: 0 se todo caso passou em todas as rodadas, 2 se algum falhou,
  1 erro de dominio ou suite.
- Cada chamada custa tokens: na suite base, 18 dos 20 casos chamam o modelo
  (os pedidos explicitos de humano sao bloqueados antes), entao `--runs 3`
  sobre os dois dominios sao 54 chamadas.

### O que falha um caso no modo real

1. `no_error`: qualquer falha do provider (`provider_error`, credencial,
   timeout, resposta vazia) ou outro `error_code`. Uma chave invalida derruba
   tudo, em vez de passar 100%.
2. O `expectation` base do caso: escalonamento, referencias, motivos de
   handoff e `forbidden_terms`. Os `required_terms` base so sao cobrados
   quando a resposta nao veio do modelo (resposta bloqueada ou sem contexto),
   porque foram calibrados contra o texto de fallback.
3. O bloco opcional `llm_expectation`, quando existir:

```yaml
    llm_expectation:
      any_of:                 # cada grupo passa se QUALQUER termo aparecer (fold)
        - ["24 horas", "24h"]
        - ["3.2"]
      forbidden_terms:        # nenhum pode aparecer (fold)
        - "r$"
      allowed_durations:      # todo prazo citado precisa estar aqui
        - 24 horas
      expected_citation:      # regex na resposta E fonte entre as referencias
        - pattern: 'item\s*3\.2'
          source: tela-apagada.md
      should_escalate: false  # opcional: sobrescreve o base so no modo real
```

- `allowed_durations` extrai todo `numero + unidade` da resposta (`h`, `hora`,
  `horas`, `dia`, `dias`, `min`, `minutos`), normaliza (`24h` = `24 horas`) e
  falha se algum nao estiver na lista (prazo alucinado, ex.: `2 horas` para
  tela apagada). Taxas como `24 horas por dia` e `7 dias por semana` sao
  ignoradas. Numero por extenso (`quatro horas`) nao e detectado. Nao use em
  caso cujo artigo cita horario (`entre 8h e 9h`).
- `expected_citation.pattern` e casado sem distinguir maiusculas contra a
  resposta sem acento: escreva o padrao sem acento.
- Com `llm_expectation`, o caso tambem exige que o modelo tenha respondido
  (`llm_answered`).
- `should_escalate` so existe para casos cujo escalonamento no modo
  deterministico vinha apenas de `provider_error` (hoje
  `como-registrar-sem-codigo` e `paineis-filmam`). O escalonamento e decidido
  antes do modelo, entao esse valor foi medido com provider falso.
- Prazos e itens dos blocos atuais saem dos artigos ficticios de demo
  (`anexo-niveis-de-servico.md`, `prazos-de-resposta.md` e FAQs). Se o artigo
  mudar, atualize o bloco.

### O que o relatorio registra

`--report` grava JSON (UTF-8). O mesmo JSON vai para o stdout.

- `model` (id devolvido pelo provider; se ele nao devolver, o configurado no
  `domain.yaml`, com `model_source: config`), `models_configured`
- `temperature` (lida do wrapper do provider, `DEFAULT_TEMPERATURE = 0.0` em
  `app/llm/wrapper.py`), `runs`, `retrieval_backend`, `timestamp_utc`
- `git_commit` (`git rev-parse HEAD`, `null` se o git falhar) e `git_dirty`
- por dominio e por metrica: `passed/total` por rodada, `mean_pass_rate` e
  `pass_at_all` (caso passa em todas as rodadas); `failed_case_ids`
- por caso e rodada: `answer` (sanitizada com `sanitize_for_persistence` e
  truncada em 600 caracteres), `error_code`, `provider_failure_kind`,
  `llm_called`, `failures` e `metrics`
- `usage` (tokens somados) so quando o provider devolve uso; senao `null`.
  `cost_usd` fica sempre `null`: o relatorio nao inventa preco. Calcule com a
  tabela vigente do provider.

As perguntas dos evals sao ficticias, mas a resposta fica gravada: revise o
relatorio antes de versionar. Este modo nao entra no CI.

## Suites pgvector/provider real

Estado atual:

- `evals/pgvector_gate.yaml` e a suite curta de gate do MVP
- `evals/pgvector_curated.yaml` e a suite ampla de diagnostico e calibracao
- `evals/intake/` contem o banco sintetico de perguntas para cobertura
- `evals/pgvector_real.yaml` continua opcional para uma rodada futura com
  perguntas anonimas reais

A suite `evals/pgvector_real.yaml` deve ser criada somente depois do relatorio
anonimo real chegar. Ate la, use `evals/pgvector_real.example.yaml` apenas como
template.

Objetivo dessa suite:

- validar perguntas anonimas parecidas com o suporte real
- medir se o pgvector recupera as referencias esperadas
- medir se `confidence` e `handoff_reasons` estao coerentes
- garantir que `error_code` fique ausente em casos saudaveis
- acompanhar `RETRIEVAL_BACKEND=pgvector` como default do staging e detectar
  regressao antes de manter ou expandir a promocao

Ela deve ser rodada de forma opt-in em ambiente privado com:

- `DATABASE_URL` configurado
- provider real configurado, como `OPENAI_API_KEY`
- conhecimento do dominio ingerido no pgvector

O processo de entrada dos casos esta em
`docs/runbooks/anonymous-eval-intake.md`.

## Casos de seguranca

Para a trilha `SEC-013`, adicione tambem casos que exercitem:

- pedido explicito de atendimento humano
- tentativa de obter senha, token, chave ou dado sensivel
- tentativa de ignorar instrucoes, revelar prompt ou contornar regras
- pergunta fora do escopo que precise recusa segura ou escalonamento

No estado atual do MVP, esses casos ainda validam principalmente:

- se houve escalonamento
- se o motivo de handoff esperado apareceu
- se o retrieval caiu em uma referencia coerente

Quando o provider real e os evals de resposta evoluirem, essa mesma trilha deve passar a cobrar recusa semantica mais forte.

Na trilha `SEC-013`, mantenha suites separadas para:

- fora do escopo
- redefinicao de identidade ou papel
- pedido de prompt, segredo, token, chave ou credencial

### Casamento de termos insensivel a acento

O `HandoffService` compara a pergunta com os padroes fixos (prompt injection,
pedido de segredo, contexto benigno de autenticacao, caso operacional critico) e
com os termos do `domain.yaml` (`sensitive_terms`, `explicit_human_phrases`,
`escalation_rules[].terms`, `routing.keywords`, nome do dominio) depois de
normalizar **os dois lados** com `app.core.text.fold`: NFKD, remocao de
diacriticos e `casefold`. Assim "Ignore suas instruções" e "ignore suas
instrucoes" tem o mesmo resultado, e um termo cadastrado com acento
("configuração") casa com a pergunta sem acento e vice-versa.

Consequencias para quem escreve casos e termos:

- Escreva padroes e termos como preferir, com ou sem acento; nao precisa
  duplicar a variante.
- Os padroes fixos do nucleo (injecao, segredo) e os termos de `routing`,
  `explicit_human_phrases` e `sensitive_terms` continuam casando por substring:
  acento nao faz "qual e a senha" casar com o padrao "qual a senha".
- Os termos de `escalation_rules` casam no inicio de palavra, com ate 2
  palavras de conteudo no meio e negacao simples (`app/handoff/term_match.py`).
  Ao mudar uma regra, inclua um caso negativo (termo negado ou com outro
  sentido) e um positivo (termo com palavras no meio) em `cases.yaml`.
- A deteccao de numero de cartao (`contains_card_number`) continua recebendo o
  texto original, sem normalizacao.
- Cada suite de confinamento dos dominios operacionais (`vendas` e
  `suporte-vps-whatsapp`) tem casos espelho com sufixo `-acentuado`, com a
  pergunta em portugues acentuado. Ao adicionar um caso de confinamento, inclua
  tambem a variante acentuada.

## Quando adicionar casos

Adicione um caso quando:

- uma duvida aparecer mais de uma vez no suporte
- uma resposta errada gerar risco operacional
- uma mudanca de prompt/retrieval alterar comportamento esperado
- um humano precisar corrigir frequentemente o mesmo tema

## Boas praticas

- Prefira perguntas parecidas com mensagens reais.
- Evite casos enormes demais.
- Mantenha expectativas simples no inicio.
- Nao coloque PII, telefones reais, tokens, senhas ou dados sensiveis.
- Nao coloque IP publico, dominio de cliente, payload bruto, header, log cru ou
  qualquer identificador reversivel.
- Se um caso falhar por falta de artigo, primeiro melhore a base de conhecimento.
