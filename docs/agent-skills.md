# Agent Skills Universais

Este repositorio possui instrucoes reutilizaveis versionadas para agentes de IA em:

```text
.agents/
  skills/
    concession-project-navigator/
      SKILL.md
    concession-git-flow/
      SKILL.md
    concession-next-step-planner/
      SKILL.md
```

Elas foram escritas em Markdown para funcionar em diferentes ferramentas, como Codex, Claude, Antigravity ou qualquer IDE/agente que aceite project rules, custom instructions, memories ou skills.

As skills tambem preservam o posicionamento do produto definido em `docs/product-positioning.md`: comercial tecnico, seguro, rastreavel e honesto sobre limites do MVP.

Outras skills locais podem existir no workspace, mas este documento cobre apenas as skills versionadas no repositorio.

## Skills disponiveis

## `concession-project-navigator`

Use antes de mexer no projeto.

Ajuda o agente a:

- ler `README.md` e `CONTRIBUTING.md` primeiro
- escolher quais docs abrir conforme a tarefa
- entender responsabilidades por frente
- evitar mexer em area de outro dev sem necessidade
- escolher testes e evals corretos
- reduzir alucinacao sobre arquitetura

## `concession-git-flow`

Use antes de testar, commitar, fazer push ou escrever PR.

Ajuda o agente a:

- revisar `git status` e `git diff --stat`
- rodar testes antes do commit
- decidir quando rodar evals
- criar commits pequenos e objetivos
- gerar descricao de PR consistente
- seguir `CONTRIBUTING.md`

## `concession-next-step-planner`

Use quando alguem perguntar "o que faco agora?", quiser iniciar uma tarefa ou validar se uma mudanca esta alinhada ao plano tecnico.

Ajuda o agente a:

- verificar estado atual da `main`
- olhar commits/PRs recentes
- ler o plano tecnico
- perguntar apenas o que a pessoa pretende mexer e qual o nome/responsavel
- apontar risco de atropelar outra frente
- sugerir o menor proximo passo seguro
- indicar docs, arquivos e validacoes esperadas

## Instalacao Universal

Escolha a forma que sua ferramenta suporta.

## Opcao A: Project Instructions

Use quando a ferramenta tiver um campo de instrucoes do projeto.

1. Abra `.agents/skills/concession-project-navigator/SKILL.md`.
2. Copie o conteudo para as instrucoes do projeto.
3. Abra `.agents/skills/concession-git-flow/SKILL.md`.
4. Copie o conteudo para as instrucoes do projeto ou deixe como segunda regra.
5. Abra `.agents/skills/concession-next-step-planner/SKILL.md`.
6. Copie o conteudo para as instrucoes do projeto ou deixe como terceira regra.

Uso recomendado:

```text
Antes de alterar este projeto, siga a skill concession-project-navigator.
Antes de commitar, pushar ou abrir PR, siga a skill concession-git-flow.
Quando alguem perguntar o que fazer agora, siga a skill concession-next-step-planner.
```

## Opcao B: Rules do repositorio

Use quando a ferramenta suporta arquivos de rules no workspace.

1. Crie o arquivo de rules esperado pela sua IDE/agente.
2. Aponte para os arquivos em `.agents/skills/`.
3. Se a ferramenta nao suporta referencias, copie o conteudo dos `SKILL.md`.

Modelo generico:

```md
# Project Rules

When navigating or modifying this repository, follow:
- `.agents/skills/concession-project-navigator/SKILL.md`

Before testing, committing, pushing, or creating PRs, follow:
- `.agents/skills/concession-git-flow/SKILL.md`

When deciding the next task or checking ownership alignment, follow:
- `.agents/skills/concession-next-step-planner/SKILL.md`
```

## Opcao C: Codex

Opcoes:

1. Usar os arquivos direto do repositorio mencionando o caminho no prompt.
2. Copiar cada pasta de `.agents/skills/` para o diretorio local de skills do Codex.

Exemplo de uso no prompt:

```text
Use .agents/skills/concession-project-navigator/SKILL.md antes de planejar esta mudanca.
Use .agents/skills/concession-git-flow/SKILL.md antes de commitar e abrir PR.
```

Se quiser instalar como skill local do Codex, copie as pastas:

```text
.agents/skills/concession-project-navigator
.agents/skills/concession-git-flow
.agents/skills/concession-next-step-planner
```

para o diretorio de skills usado pelo seu ambiente Codex.

## Opcao D: Claude

Use como Project Instructions ou arquivo de contexto do projeto.

Sugestao:

1. Adicione uma instrucao fixa dizendo para Claude consultar `.agents/skills/`.
2. Cole o conteudo dos dois `SKILL.md` nas instrucoes do projeto, se a ferramenta nao conseguir ler arquivos diretamente.

Prompt curto:

```text
Antes de editar, leia e siga .agents/skills/concession-project-navigator/SKILL.md.
Antes de commit/push/PR, leia e siga .agents/skills/concession-git-flow/SKILL.md.
```

## Opcao E: Antigravity

Use como rules/instructions do workspace.

Sugestao:

1. Configure uma regra do projeto apontando para `.agents/skills/concession-project-navigator/SKILL.md`.
2. Configure outra regra para `.agents/skills/concession-git-flow/SKILL.md`.
3. Se a ferramenta nao resolver caminhos automaticamente, cole o conteudo dos arquivos nas rules.

Prompt curto:

```text
Siga as agent skills em .agents/skills/ para navegar, alterar, testar, commitar e abrir PR neste projeto.
```

## Como usar no dia a dia

Para tarefas de codigo:

```text
Use concession-project-navigator para identificar docs, arquivos e testes antes de implementar.
```

Para tarefas de Git:

```text
Use concession-git-flow para validar, commitar, pushar e escrever a descricao do PR.
```

Para decidir o que fazer agora:

```text
Use concession-next-step-planner para cruzar main, ultimos PRs, plano tecnico, intencao e responsavel.
```

Para tarefas de conhecimento/RAG:

```text
Use concession-project-navigator e leia tambem docs/architecture/knowledge-authoring.md e docs/architecture/domain-evals.md.
```

## Manutencao

Atualize as skills quando:

- a arquitetura mudar
- novos endpoints ou contratos forem criados
- novos diretorios ou scripts operacionais forem adicionados
- novas fontes de conhecimento, loaders ou adapters forem criados
- regras de dependencia, extras ou auditoria mudarem
- novos dominios forem adicionados
- o fluxo de testes/evals mudar
- o processo de PR mudar

As skills devem continuar curtas. Se ficarem grandes demais, mova detalhes para docs do projeto e deixe a skill apenas apontar o caminho certo.
