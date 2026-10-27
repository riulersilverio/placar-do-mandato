# Metodologia do Placar do Mandato

Versão 2 — Câmara dos Deputados e Senado Federal, 57ª legislatura (fev/2023 em diante).

## Fontes

| Dado | Origem |
|---|---|
| Deputados e histórico de mandato (posse, licença, suplência) | API `dadosabertos.camara.leg.br/api/v2/deputados` |
| Proposições e situação atual | Arquivos `proposicoes-{ano}.csv` |
| Autores de cada proposição | Arquivos `proposicoesAutores-{ano}.csv` |
| Votações e votos nominais | Arquivos `votacoes-{ano}.csv` e `votacoesVotos-{ano}.csv` |

## Os quatro componentes

Cada componente vira um **percentil** entre os deputados elegíveis: 70 significa "melhor que 70% dos colegas".
A nota final é a média ponderada dos percentis.

| Componente | Peso | Como é medido |
|---|---|---|
| Resultados | 35% | Soma de pontos dos projetos (PL, PLP, PEC, PDL) conforme o estágio |
| Presença | 30% | Votos dados ÷ votações nominais do plenário nos períodos em exercício |
| Projetos apresentados | 20% | Projetos de autoria principal, sem homenagens |
| Fiscalização | 15% | Requerimentos de informação (RIC) e propostas de fiscalização (PFC) de autoria principal |

### Pontos por estágio do projeto

| Estágio | Situações da Câmara | Pontos |
|---|---|---|
| Virou lei | Transformado em Norma Jurídica, Aguardando Sanção, Aguardando Apreciação do Veto | 10 |
| Aprovado na Câmara | Aguardando Apreciação pelo Senado, Aguardando Redação Final etc. | 5 |
| Avançou | Pronta para Pauta, Aguardando Parecer, Aguardando Deliberação | 2 |
| Parado | Aguardando Relator, Tramitando em Conjunto e demais | 0,5 |
| Encerrado | Arquivada, Retirado, Devolvida | 0 |

Multiplicadores: coautor vale 0,25 do autor principal; homenagens (nomes de rua, datas comemorativas,
títulos, patronos) valem 0,1. A lista de termos de homenagem está em `pipeline/score_camara.py` (`RE_HONORARIA`).

## Temas

Usamos os temas oficiais da Câmara (arquivos `proposicoesTemas-{ano}.csv`), atribuídos pela equipe técnica
da Casa. Um projeto pode ter mais de um tema. É homenagem quem tem o tema oficial
"Homenagens e Datas Comemorativas" ou termos de homenagem na ementa.

## Votações e alinhamento (fora da nota)

- **Votações listadas**: votações nominais do plenário ligadas a PEC, PLP, MPV, PLV, PL ou PDL.
  O filtro "texto principal" mostra só as que decidem o texto do projeto (projeto, substitutivo, PEC em
  1º/2º turno, emendas do Senado), sem destaques, emendas avulsas e requerimentos.
- **Votou com o governo**: votos iguais à orientação oficial do governo, nas votações em que ela foi Sim ou Não.
- **Votou com a maioria do partido**: votos iguais à posição da maioria dos colegas de partido naquela
  votação. Não usamos a orientação oficial dos partidos porque quase todos orientam por bloco, e os nomes
  dos blocos vêm truncados nos dados. Em partidos muito pequenos esse número tende a 100%.
- Esses números descrevem o perfil do deputado e **não entram na nota**.

## Regras de justiça

- **Licenças não contam como falta.** A presença só considera votações ocorridas nos períodos com situação
  "Exercício" no histórico do deputado.
- **Elegibilidade.** Entra no ranking quem está em exercício e teve pelo menos 50 votações nominais no período.
- **Presidência da sessão.** Voto registrado como "Artigo 17" conta como presença. Quem presidiu a Câmara
  recebe uma observação na ficha, porque por regra não vota nem apresenta projetos.

## Senado Federal

Mesmos pesos, pontos e regras da Câmara, com estas diferenças:

- **Fontes**: API `legis.senado.leg.br/dadosabertos` — `senador/lista`, `senador/{cod}/mandatos` (períodos em
  exercício), `votacao` (voto de cada senador), `plenario/votacao/orientacaoBancada` e `processo` (projetos).
- **Temas**: classificação oficial do Senado, usando o 2º nível da hierarquia (ex.: "Política Social / Educação /
  Educação Básica" vira "Educação").
- **Estágio**: lido da situação atual do projeto; "virou lei" quando há norma gerada.
- **Presença**: todas as votações nominais, inclusive secretas. Licenças (LS, LP) saem da conta. Missão oficial (MIS)
  e atividade parlamentar (AP) contam como ausência, mas aparecem como "ausência justificada".
- **Fiscalização**: requerimentos (RQS) do tipo "Informações", de autoria principal.
- **Elegibilidade**: pelo menos 30 votações nominais no período, porque o Senado vota muito mais de forma simbólica.
- **Lista de votos**: só votações abertas. Nas secretas (escolha de autoridades) o voto individual não é divulgado.

Senadores são comparados só com senadores, e deputados só com deputados.

## Autor dos projetos votados

Na Câmara, buscado na API (`/proposicoes/{id}/autores`) para cada projeto votado no plenário, já que muitos são
anteriores a 2023. No Senado, vem da autoria no detalhe do projeto. Mostra o primeiro autor e quantos assinaram junto.

## Limitações conhecidas

1. **Relatorias não entram ainda.** Relatar um projeto importante é uma das principais formas de influência.
2. **Comissões não entram na presença.** Só votações nominais do plenário.
3. **Votações simbólicas** (sem registro individual) não aparecem.
4. **Só entram proposições apresentadas a partir de 2023.** Um projeto de mandato anterior que virou lei
   nesta legislatura ainda não conta para o autor.
5. **Classificação de homenagem e tema** é feita por palavras-chave e pode errar em casos de borda.

## Próximas versões

- Relatorias (API `/proposicoes/{id}/tramitacoes`, campo relator).
- Resumo em linguagem simples de cada projeto com IA.
- Gastos da cota parlamentar (exibidos à parte, fora da nota).
- Senado, assembleias estaduais, governadores e Presidência (ver README).

## Presidência da República

O presidente não vota, então não recebe nota. A página mostra quatro coisas, todas a partir de jan/2023:

- **Medidas provisórias** (API do Senado, `processo?sigla=MPV`): resultado lido da deliberação do Congresso —
  virou lei (na íntegra ou com mudanças), perdeu a validade, revogada pelo governo ou em análise. Separamos as de
  **crédito extraordinário** (ementa "Abre crédito extraordinário"), porque nelas o dinheiro é usado na hora e perder a
  validade depois é o caminho normal.
- **Projetos enviados**: PL, PLP e PEC com autor "Órgão do Poder Executivo" nos arquivos da Câmara, com o mesmo
  critério de estágio usado para os deputados. Projetos de orçamento (PLN) ficam de fora.
- **Vetos** (`processo?sigla=VET`): total ou parcial, e a decisão do Congresso (mantido, derrubado, derrubado em
  parte, prejudicado ou ainda sem análise).
- **Apoio no Congresso**: votações em que o governo orientou Sim ou Não. O governo venceu quando o resultado foi o que
  ele orientou. Mostramos separado o texto principal, porque emendas e requerimentos são mais disputados.
- **Promessas**: em construção. Exigirá classificação manual com fonte e data de revisão para cada item.

## Promessas de governo

- **Fonte**: só o plano de governo registrado no TSE (arquivos `proposta_governo` dos dados abertos). Promessas feitas
  em debates, entrevistas ou redes sociais ficam de fora, porque não há registro oficial único.
- **Seleção**: entram compromissos concretos e verificáveis. Diretrizes genéricas ficam de fora.
- **Classificação**: Cumprida, Cumprida em parte, Em andamento, Não cumprida ou Não iniciada, sempre com justificativa,
  prova (lei, decreto, dado oficial ou reportagem) e data da verificação.
- **Revisão humana**: as sugestões só são publicadas depois que uma pessoa revisa cada linha
  (ver `data/curadoria/COMO_REVISAR.md`).

## Governadores

Lista oficial do TSE (`consulta_cand_2026`) com os eleitos no 1º turno e os finalistas do 2º turno. O resultado do
2º turno entra quando o TSE atualiza o arquivo. O plano de governo de cada eleito pode ser baixado no app. Os
governadores tomam posse em 06/01/2027 (Emenda Constitucional 111/2021); até lá as promessas aparecem como
"Não iniciada".
