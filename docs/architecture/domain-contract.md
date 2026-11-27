# Contrato de Dominio

Um dominio define como o agente deve atuar em uma area especifica, sem mudar o motor compartilhado em `app/`.

Exemplos de dominios futuros:

- `suporte-vps-whatsapp`
- `vendas`
- `onboarding`
- `financeiro`

## Arquivo principal

Cada dominio precisa ter:

```text
domains/
  nome-do-dominio/
    domain.yaml
    knowledge/
    prompts/
```

O `domain.yaml` e o contrato minimo do dominio.

## Campos principais

```yaml
contract_version: 1
name: vendas
display_name: Suporte de Vendas
description: Agente para duvidas comerciais e qualificacao inicial.
owner: Comercial
default_language: pt-BR

behavior:
  persona: consultor de vendas claro e consultivo
  primary_goal: ajudar leads com duvidas comerciais simples
  answer_guidelines:
    - qualifique antes de sugerir plano
    - seja objetivo e evite promessas comerciais absolutas
  out_of_scope:
    - suporte tecnico profundo
    - negociacoes contratuais sensiveis

routing:
  keywords:
    - preco
    - plano
    - contratar

response:
  tone: simples
  max_context_chunks: 5
  max_answer_length: short
  no_context_message: Nao encontrei contexto suficiente neste dominio. O ideal e escalar para humano.
  provider_error_message: Nao consegui gerar uma resposta automatica agora. Vou sinalizar escalonamento.

handoff:
  confidence_threshold: 0.7
  escalate_on:
    - low_confidence
    - explicit_human_request
  explicit_human_phrases:
    - falar com humano
    - atendente
  sensitive_terms:
    - contrato
    - reembolso
  escalation_rules:
    - reason: operational_risk
      priority: high        # opcional: low | normal | high | urgent
      terms:
        - bloqueio
        - banimento
      ignore_terms:         # opcional: frases tiradas do texto antes de casar
        - sem bloqueio

sla:                        # opcional: prazos do console para este dominio
  basis: "Anexo de SLA do contrato, item 3"
  urgent_minutes: 240
  high_minutes: 1440
  normal_minutes: 2880
  low_minutes: 7200

knowledge:
  sources:
    - knowledge/faqs
    - knowledge/articles

llm:
  provider: mock
  model: mock-model
  embedding_model: mock-embedding

embedding:
  provider: openai
  model: text-embedding-3-small
  dimensions: 1536

feature_flags:
  context_aware_scope: false
```

## Regras simples

- `name` deve ser igual ao nome da pasta do dominio.
- Dominios invalidos nao aparecem em `GET /domains`.
- Conteudo especifico do setor deve ficar em `domains/<dominio>/knowledge`.
- Regra reutilizavel entre setores deve ficar em `app/`.
- Comece com `provider: mock` antes de ligar provider real.
- Ajuste `confidence_threshold` so depois de observar conversas reais.
- `feature_flags` e um mapa opcional `nome -> on/off` por dominio, default vazio
  (toda flag desligada). Serve para ligar uma mudanca de comportamento atras de
  flag escopada a um dominio, sem variavel de ambiente global. Leia no codigo com
  `domain.is_flag_enabled("<flag>")`, que devolve `False` para flag nao declarada.
- `escalation_rules[].priority` (opcional) define a prioridade do caso que a
  regra abre no console. Quando varias regras casam, vale a maior; sem
  prioridade declarada o caso fica `normal`. Motivo de seguranca do nucleo
  (`sensitive_topic`, `secret_request`, `card_data`, `prompt_injection_attempt`)
  sobe o piso para `normal`: uma regra `low` nao rebaixa o caso. Codigo:
  `app.handoff.taxonomy.resolve_case_priority`.
- `escalation_rules[].ignore_terms` (opcional) sao frases removidas da mensagem
  antes de testar os `terms` daquela regra, para um termo com outro sentido nao
  disparar a regra ("sem risco" nao vira `risco_seguranca`). Remover a frase nao
  esconde outro termo da mesma mensagem ("fio exposto, sem risco?" continua
  urgente). Todo `ignore_terms` novo pede um caso negativo no eval do dominio.
- `sla` (opcional) sobrescreve, para os casos deste dominio, os minutos do SLA
  global (`SUPPORT_SLA_MINUTES_*`) nas prioridades declaradas; as demais herdam
  o global. `basis` diz de onde vem o prazo (clausula de contrato, artigo de lei)
  e aparece em `sla.basis` na resposta do console. Use quando o prazo vem de
  fora do time: contrato de concessao, LGPD art. 19. Codigo: `app/support/sla.py`.
  Na fila compartilhada do console (`sort=attention`) cada caso e ordenado pelo
  seu proprio prazo: semaforo (vermelho, amarelo, verde; pausados por ultimo),
  depois `deadline_at` mais proximo, depois prioridade, mais antigo e `case_id`.
  Um caso de manutencao a 1h do prazo de 48h passa na frente de um pedido LGPD
  com 12 dias de folga, mesmo que o pedido seja mais antigo.

## Como criar um novo dominio

1. Copie `domains/concessoes-manutencao` (ou `domains/suporte-vps-whatsapp`, o dominio de referencia) para uma nova pasta.
2. Renomeie a pasta e o campo `name` para o novo dominio.
3. Atualize `display_name`, `description`, `owner` e `behavior`.
4. Troque os artigos em `knowledge/`.
5. Rode `python -m pytest`.
6. Teste `GET /domains` e `POST /chat` usando o novo dominio.

## O que o contrato influencia hoje

- Prompt base do agente.
- Persona e objetivo principal.
- Diretrizes de resposta.
- Itens fora do escopo.
- Quantidade de chunks recuperados.
- Mensagens padrao de falta de contexto ou erro de provider.
- Threshold e gatilhos de escalonamento.
- Regras configuraveis de escalonamento por termos do dominio, sem hardcode no motor compartilhado.
- Prioridade do caso aberto no console e o prazo (SLA) que o semaforo usa.
