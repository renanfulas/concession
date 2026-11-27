# concession — instrucoes para agentes de codigo

Este arquivo vale para Claude Code e para qualquer agente que leia
instrucoes de projeto (AGENTS.md, regras de IDE). As skills completas ficam
versionadas em `.agents/skills/` e sao a fonte unica; este arquivo nao as
duplica.

## Antes de agir

| Situacao | Siga |
| --- | --- |
| Vai ler, planejar ou editar qualquer coisa | `.agents/skills/concession-project-navigator/SKILL.md` |
| Vai testar, commitar, fazer push ou abrir PR | `.agents/skills/concession-git-flow/SKILL.md` |
| Alguem pergunta "o que fazer agora?" | `.agents/skills/concession-next-step-planner/SKILL.md` |

Comece sempre por `README.md` e `docs/project-map.md`. Leia so os docs da area
que vai mexer (`docs/navigation.md` diz quais).

## Regras do projeto

- O nucleo em `app/` e reutilizavel entre dominios. Comportamento de um setor
  (persona, termos, prioridade, prazo, conhecimento) vai em `domains/<dominio>/`.
- Rotas validam e orquestram; regra de negocio fica nos servicos.
- Transporte externo (Meta WhatsApp, Hermes) e adapter: nao mover inteligencia
  para la.
- `pyproject.toml` e a unica fonte de dependencias.
- PostgreSQL + pgvector e o vector store de producao; Chroma e so prototipo.
- Conteudo ficticio (contrato, prazos, ativos, aviso de privacidade) continua
  marcado como demo. Nunca apresente como real.
- Nao use marca, logo ou identidade visual de empresas reais.

## Regras de governanca para agentes

1. **Revisao humana.** Agente propoe; uma pessoa aprova o commit, o push e o PR.
   Nao faca commit ou push sem pedido explicito.
2. **Rastreabilidade.** Commit feito com agente leva o trailer
   `Co-Authored-By:` do agente. A mensagem diz a intencao, nao a lista de arquivos.
3. **Prova antes de entregar.** Mudanca de codigo roda `python -m pytest`. Mudanca
   em dominio, prompt, retrieval ou handoff roda os evals dos dominios afetados.
   Se nao rodou, diga que nao rodou e por que.
4. **Prazo e prioridade so com eval.** Mudou `sla:` ou `escalation_rules` num
   `domain.yaml`? Atualize o eval que prova a classificacao
   (`required_handoff_reasons`) e `tests/test_concessoes_domain.py` quando for o
   dominio de manutencao.
5. **Dados pessoais.** Nunca registre em log, teste, fixture ou commit:
   telefone, CPF, e-mail, token, segredo, `session_id` bruto ou prompt com dado
   sensivel. Use valores ficticios.
6. **Segredos.** Nunca leia nem commite `.env`, chaves ou credenciais. Use
   `.env.example` para documentar variaveis.
7. **Escopo.** Um commit, uma intencao. Nao misture refatoracao com mudanca de
   comportamento.
8. **Ficha do sistema.** Mudou dado tratado, base legal, controle ou limite?
   Atualize `docs/ficha-do-sistema.md` e `docs/system-card.md`.

## Validacao rapida

```bash
python -m ruff check app tests scripts
python -m compileall app tests scripts
python -m pytest
python -m app.evals.run_domain_eval concessoes-manutencao
python -m app.evals.run_domain_eval lgpd-titular
```

Dependencia mudou: `python -m pip check` e `python -m pip_audit .`.
