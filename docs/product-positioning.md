# Posicionamento Do Produto

## Proposta

O `concession` e um atendimento com RAG para operacao de concessoes de
mobiliario urbano e midia exterior. Ele registra defeitos e pedidos de
privacidade, informa o prazo citando a fonte (clausula do contrato ou artigo
da LGPD) e entrega cada caso ao time certo com o semaforo de SLA.

Ele nao substitui a equipe de manutencao, o encarregado de dados nem a equipe
de contrato. O valor esta em nao perder prazo, responder igual em todos os
canais e conseguir provar o que foi feito.

## Publico

- operacoes de manutencao de mobiliario urbano (relogios, abrigos, paineis)
- encarregado de dados (DPO) e time de privacidade
- times de TI que precisam avaliar, governar e inventariar solucoes de IA

## Dores Que Resolve

- prazo de contrato perdido porque o defeito chegou por um canal informal
- pedido de titular respondido fora do prazo da LGPD
- resposta diferente para a mesma pergunta em canais diferentes
- falta de prova de quando o pedido chegou, qual prazo valia e quem tratou
- bot que inventa resposta ou promete o que o contrato nao garante

## Promessas Do Produto

- responder com base em conhecimento versionado e devolver as fontes recuperadas
- classificar o pedido por regra declarada no dominio, testada por eval
- aplicar o prazo do dominio (contrato ou lei) no semaforo do console
- expor `request_id`, `references`, `confidence`, `handoff_reasons` e `error_code`
- falhar de forma segura quando provider, credencial ou retrieval falhar
- escalar para humano quando faltar contexto, o tema for sensivel ou o usuario pedir

## O Que Nao Prometer

- autonomia total sem supervisao
- execucao de exclusao de dados, decisao sobre multa ou interpretacao de contrato
- prazos reais de um contrato especifico (os desta demo sao ficticios)
- reconhecimento de pessoas ou uso de imagem
- substituicao do time de manutencao, do encarregado ou da equipe de contrato

## Tom De Comunicacao

Comercial tecnico: claro, confiavel, operacional e direto.

Prefira:

- "registra o pedido com o prazo do contrato e a fonte"
- "escala para o encarregado com o prazo legal"
- "cada prazo vem do `domain.yaml`, testado por eval"
- "ambiente de demonstracao com dados ficticios"

Evite:

- promessas absolutas ou linguagem de hype
- afirmar que o bot resolve sozinho
- esconder que contrato, prazos e ativos sao ficticios
- usar marca, nome, logo ou identidade visual de empresas reais (excecao: as
  telas usam so a paleta de cores do logotipo da JCDecaux; ver `CLAUDE.md`)
- sugerir vinculo, parceria ou aprovacao de empresa real
