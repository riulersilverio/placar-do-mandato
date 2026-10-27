# Placar do Mandato

Painel público e apartidário que mostra, em linguagem simples, o que cada político fez no mandato:
projetos por tema, como votou, presença e uma nota de 0 a 100.

## Como rodar

```bash
pip install -r requirements.txt
python pipeline/coleta_camara.py      # Câmara: baixa os dados (≈1 GB; retoma se a conexão cair)
python pipeline/score_camara.py       # Câmara: notas, votações e temas em data/gold/camara
python pipeline/coleta_senado.py      # Senado: API de dados abertos (reaproveita o que já baixou)
python pipeline/score_senado.py       # Senado: mesmo formato, em data/gold/senado
python pipeline/coleta_presidencia.py # Presidência: medidas provisórias e vetos (API do Congresso)
python pipeline/score_presidencia.py  # Presidência: MPs, vetos, projetos do Executivo e apoio no Congresso
python pipeline/coleta_governadores.py # Governadores: candidatos e planos do TSE (rode de novo após o 2º turno)
python pipeline/score_governadores.py  # Governadores: lista dos eleitos e texto dos planos
streamlit run app.py
```

Atualização diária: `python pipeline/coleta_camara.py --anos 2026 --forcar && python pipeline/score_camara.py`.

## O que o app mostra (Câmara e Senado)

- **Deputados federais / Senadores** (escolha a Casa no topo): ranking com filtros. A ficha de cada um tem a nota
  explicada, os projetos por tema oficial com andamento e a lista de como votou em cada projeto.
- **Votações**: cada votação nominal aberta do plenário, com o autor do projeto, o resultado, a orientação do
  governo, o voto de cada partido e o de cada parlamentar. Dá para escolher um político e ver o voto dele em
  cada projeto, ou filtrar quem votou a favor ou contra.
- **Temas**: a classificação oficial de cada Casa, quem mais trabalha em cada tema e quais projetos viraram lei.

## Estrutura

```
pipeline/   coleta (raw) e cálculo (gold)
data/raw/   arquivos oficiais, sem alteração
data/gold/  Parquet prontos para o app
app.py      app Streamlit
```

## Cobertura

| Quem | Status | Fonte |
|---|---|---|
| Deputados federais | ✅ | dadosabertos.camara.leg.br |
| Senadores | ✅ | legis.senado.leg.br/dadosabertos |
| Presidente | ✅ (promessas aguardando revisão) | MPs, projetos enviados, vetos e apoio nas votações (APIs da Câmara e do Senado) + plano de governo 2022 (TSE) |
| Governadores | ✅ eleitos e planos; promessas a partir da posse (06/01/2027) | Dados abertos do TSE (candidatos e planos de governo 2026) |
| Deputados estaduais | Planejado | Começando por MG (dadosabertos.almg.gov.br); as outras 26 assembleias variam em qualidade |

Metodologia completa em [METODOLOGIA.md](METODOLOGIA.md).

## Promessas (curadoria)

As promessas ficam em `data/curadoria/*.csv` e só aparecem no site depois de revisadas por uma pessoa.
Veja [data/curadoria/COMO_REVISAR.md](data/curadoria/COMO_REVISAR.md).
