# Intake e inventario de solucoes de IA

> **Demonstracao.** Politica de criticidade, prazos e solucoes do seed sao
> ficticios. A politica real vem do comite de dados e IA e do encarregado.

## O que resolve

Uma unidade de negocio quer usar IA. Sem um fluxo de entrada, a iniciativa
chega por e-mail, ninguem sabe que dado ela trata e o inventario fica numa
planilha desatualizada. O intake padroniza a entrada:

```text
unidade de negocio submete (formulario /team/intake)
  -> regras deterministicas calculam a criticidade e os motivos
  -> prazo da analise gravado na submissao (como a migration 020)
  -> fila do revisor por pressao do prazo (mesmo motor de SLA do console)
  -> decisao auditada: aprovar, aprovar com condicoes, rejeitar
  -> inventario CSV e ficha por solucao, no formato da ficha deste sistema
```

O nucleo de prazo do console serve tres tipos de prazo: contrato (manutencao,
horas), lei (titular LGPD, dias) e governanca (analise de uma iniciativa de
IA, dias).

## Onde fica cada coisa

| Camada | Arquivo |
| --- | --- |
| Listas fechadas e modelo | `app/ai_intake/models.py` |
| Politica (criticidade e prazo) | `governance/ai-intake.yaml`, `app/ai_intake/policy.py` |
| Fluxo (quem pode o que) | `app/ai_intake/workflow.py` (`plan_transition`, funcao pura) |
| Persistencia | `app/ai_intake/repository.py` (PostgreSQL e memoria, mesma interface) |
| Servico (mascaramento, prazo, fila) | `app/ai_intake/service.py` |
| Inventario e ficha | `app/ai_intake/inventory.py` |
| Rotas | `app/api/routes/ai_intake.py` em `/web/support/intake` |
| Tela | `app/static/team/intake.html`, `intake.js`, `intake.css` em `/team/intake` |
| Banco | `migrations/021_ai_solution_intake.sql` |
| Seed ficticio | `scripts/seed_demo_ai_solutions.py` |

A rota fica sob `/web/support` de proposito: o cookie da sessao staff tem
`Path=/web/support`, entao a mesma sessao OTP do console vale no intake. Sobe
so com `ENABLE_SUPPORT_CONSOLE=true` e `ENABLE_AI_INTAKE` (padrao: ligado em
desenvolvimento, desligado fora dele).

## Criticidade

Regras em `governance/ai-intake.yaml`, ligadas por E. Quando varias casam, vale
o maior nivel e todos os motivos aparecem na ficha. Sem LLM: o nivel de risco
nao pode depender de um modelo estar no ar nem mudar entre duas execucoes.

| Regra (demo) | Nivel |
| --- | --- |
| dado sensivel, imagem de pessoas ou dado de crianca (LGPD art. 11 e 14) | alta |
| decisao automatizada sobre pessoas (art. 20) | alta |
| dado pessoal hospedado fora do Brasil (art. 33) | alta |
| dado pessoal com uso externo | media |
| dado pessoal | media |
| publico externo sem revisao humana | media |
| nenhuma das anteriores | baixa |

Prazo da analise (demo, dias corridos): baixa 5, media 10, alta 15. Aprovar uma
solucao de nivel alto exige a referencia do RIPD (art. 38).

## Fluxo

| De | Acao | Para | Quem |
| --- | --- | --- | --- |
| `submitted` | `claim` | `in_review` | qualquer pessoa da equipe, menos quem submeteu |
| `in_review` | `release` | `submitted` | o revisor |
| `in_review` | `request_info` (nota obrigatoria) | `needs_info` | o revisor; o prazo pausa |
| `needs_info` | `resume` | `in_review` | quem submeteu ou o revisor |
| `in_review` | `approve` | `approved` | o revisor; nota; RIPD se exigido |
| `in_review` | `approve_with_conditions` | `approved_conditional` | o revisor; nota, condicoes; RIPD se exigido |
| `in_review` | `reject` | `rejected` | o revisor; nota e motivo de lista fechada |
| `submitted`, `needs_info` | `withdraw` | `withdrawn` | quem submeteu |

No PostgreSQL a transicao le a linha com `FOR UPDATE`, chama `plan_transition`
e grava o plano mais o evento na mesma transacao.

## Dados tratados

Nome e papel do responsavel pela solucao (dado de funcionario, necessario ao
inventario). Nada de e-mail, telefone ou documento. Textos livres (finalidade,
notas, condicoes) passam por `sanitize_for_persistence` antes de gravar. Logs
levam so referencia, acao e status. Ver `docs/ficha-do-sistema.md`.

## Limites

- Nao ha papeis: toda pessoa da equipe do console pode revisar. A unica regra
  de autorizacao e a separacao de funcoes. Em producao, os papeis viriam de
  grupos do provedor de identidade corporativo.
- Prazo em dias corridos; o motor de SLA nao conhece calendario de trabalho.
- A criticidade e tao boa quanto a declaracao: quem submete pode marcar errado.
  O revisor ve as respostas e os motivos, e pode pedir informacao.
- Sem anexos (o RIPD e uma referencia, nao um arquivo).
- Sem notificacao: a fila e consultada na tela.
