"""Placar do Mandato — app Streamlit.

Lê os arquivos gerados por pipeline/score_camara.py e pipeline/score_senado.py em data/gold/{casa}.
Rodar: streamlit run app.py
"""
import json
import os
import unicodedata
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

GOLD = Path(__file__).resolve().parent / "data" / "gold"

CASAS = {
    "Câmara dos Deputados": {
        "pasta": "camara", "cargo": "deputado", "cargos": "deputados", "aba": "Deputados federais",
        "titulo": "deputado federal", "aprovada": "Aprovados na Câmara", "aprovada_ajuda": "Aguardando o Senado",
        "fonte": "[Dados Abertos da Câmara dos Deputados](https://dadosabertos.camara.leg.br)",
        "presidiu": "Pelo Regimento (art. 17), quem preside não vota, salvo para desempatar, e não apresenta projetos.",
        "temas": "Os temas são os oficiais da Câmara, definidos pela equipe técnica da Casa.",
        "fiscalizacao": "Pedidos formais de informação a ministérios e propostas de fiscalização.",
    },
    "Senado Federal": {
        "pasta": "senado", "cargo": "senador", "cargos": "senadores", "aba": "Senadores",
        "titulo": "senador", "aprovada": "Aprovados no Senado", "aprovada_ajuda": "Aguardando a Câmara",
        "fonte": "[Dados Abertos do Senado Federal](https://www12.senado.leg.br/dados-abertos)",
        "presidiu": "Pelo Regimento do Senado (art. 51), quem preside a sessão só vota em caso de empate ou em votação secreta.",
        "temas": "Os temas são a classificação oficial do Senado, feita pela equipe técnica da Casa.",
        "fiscalizacao": "Requerimentos de informação enviados a ministros e órgãos do governo.",
    },
}
COMPONENTES = [
    ("p_resultado", "resultado", "Resultados", "Projetos que avançaram, foram aprovados na Casa ou viraram lei."),
    ("p_presenca", "presenca", "Presença", "Participação nas votações nominais do plenário enquanto estava no cargo."),
    ("p_producao", "producao", "Projetos apresentados", "Projetos de lei de sua autoria, sem contar homenagens."),
    ("p_fiscalizacao", "fiscalizacao", "Fiscalização", None),
]
ORDENS = {
    "Nota geral": "score",
    "Projetos que viraram lei": "viraram_lei",
    "Presença nas votações": "presenca",
    "Projetos apresentados": "projetos_autor",
    "Pedidos de fiscalização": "pedidos_fiscalizacao",
    "Votou com o governo": "alinh_governo",
}
# Em votações do texto principal, "Sim" é a favor do projeto
VOTO_TEXTO = {"Sim": "A favor", "Não": "Contra", "Abstenção": "Absteve-se", "Obstrução": "Obstrução",
              "Artigo 17": "Presidindo a sessão", "Presidente": "Presidindo a sessão",
              "Ausente": "Não votou", "Ausência justificada": "Ausência justificada",
              "Presente, não votou": "Presente, não votou", "Licença": "Licença"}
GRUPO_VOTO = {"Sim": "A favor", "Não": "Contra", "Ausente": "Não votou", "Ausência justificada": "Não votou",
              "Licença": "Não votou"}
CORES_VOTO = {"A favor": "#1f7a8c", "Contra": "#c4622d", "Outros": "#9aa3ab", "Não votou": "#d4d8d3"}
COR = "#0d6b70"
COL_LINK = st.column_config.LinkColumn("Projeto", display_text=r"[#/](\d+)$", width="small")

st.set_page_config(page_title="Placar do Mandato", page_icon="🗳️", layout="wide")


@st.cache_data
def carregar(pasta: str):
    g = GOLD / pasta
    meta = json.loads((g / "meta.json").read_text(encoding="utf-8"))
    parl = pd.read_parquet(g / "parlamentares.parquet")
    projs = pd.read_parquet(g / "projetos.parquet")
    vots = pd.read_parquet(g / "votacoes.parquet")
    votos = pd.read_parquet(g / "votos.parquet")
    for df in (projs, vots):
        df["temas"] = df["temas"].map(list)
    vots["resultado"] = vots["aprovada"].map({True: "Aprovado", False: "Rejeitado"})
    vots["governo"] = vots["orientacao_governo"].map({"Sim": "A favor", "Não": "Contra", "Liberado": "Liberou"}).fillna("—")
    return meta, parl, projs, vots, votos


def sem_acento(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()


def fmt_pct(v) -> str:
    return "—" if pd.isna(v) else f"{v:.0%}"


def tem_tema(df: pd.DataFrame, escolha: list[str]) -> pd.Series:
    return df["temas"].map(lambda ts: any(t in ts for t in escolha))


def estagios(c: dict) -> dict:
    return {"lei": (4, "Virou lei"), "aprovada_casa": (3, c["aprovada"]), "avancou": (2, "Em análise nas comissões"),
            "parada": (1, "Aguardando andamento"), "encerrada": (0, "Arquivado ou retirado")}


def grafico_temas(projs: pd.DataFrame, titulo: str, limite: int = 15):
    """Barras horizontais: projetos por tema, com a parte que virou lei destacada."""
    ex = projs[~projs["homenagem"]].explode("temas").dropna(subset=["temas"])
    if ex.empty:
        return None
    cont = ex.groupby("temas").agg(projetos=("id", "count"), leis=("estagio", lambda s: (s == "lei").sum()))
    cont = cont.sort_values("projetos", ascending=False).head(limite).reset_index()
    base = alt.Chart(cont, title=titulo).encode(
        y=alt.Y("temas:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
        tooltip=[alt.Tooltip("temas:N", title="Tema"), alt.Tooltip("projetos:Q", title="Projetos"),
                 alt.Tooltip("leis:Q", title="Viraram lei")],
    )
    barras = base.mark_bar(color=COR, opacity=0.35, cornerRadiusEnd=4).encode(x=alt.X("projetos:Q", title="Projetos"))
    leis = base.mark_bar(color=COR, cornerRadiusEnd=4).encode(x="leis:Q")
    return (barras + leis).properties(height=max(120, 26 * len(cont)))


def ficha(d: pd.Series, c: dict, meta: dict, parl, projs, vots, votos) -> None:
    c1, c2 = st.columns([1, 6], vertical_alignment="center")
    if d["foto"]:
        c1.image(d["foto"], width=96)
    c2.subheader(d["nome"])
    c2.caption(f"{d['partido']} · {d['uf']} · {c['titulo']}")
    est = estagios(c)

    resumo, aba_proj, aba_votos = st.tabs(["Resumo", "Projetos por tema", "Como votou"])
    with resumo:
        total = int(parl["score"].notna().sum())
        if pd.isna(d["score"]):
            st.info(f"Ainda sem nota: participou de menos de {meta['min_votacoes']} votações no plenário durante o "
                    "mandato, geralmente por ter assumido há pouco tempo.")
        else:
            st.markdown(f"### {int(d['score'])} <small style='font-weight:400'>de 100 · "
                        f"{int(d['posicao'])}º lugar entre {total} {c['cargos']}</small>", unsafe_allow_html=True)
            for chave, peso, nome, texto in COMPONENTES:
                v = int(d[chave])
                st.markdown(f"**{nome}** · peso {round(meta['pesos'][peso] * 100)}% — melhor que **{v}%** dos {c['cargos']}")
                st.progress(v / 100, text=texto or c["fiscalizacao"])
        if d["presidiu"] > 0 and d["presidiu"] >= 0.3 * d["votou"]:
            st.warning(f"**Presidiu a Casa.** Em {int(d['presidiu'])} votações comandava a sessão. {c['presidiu']} "
                       "Por isso a nota subestima a influência, que está em decidir o que vai a votação.")
        m = st.columns(3)
        m[0].metric("Viraram lei", int(d["viraram_lei"]))
        m[1].metric(c["aprovada"], int(d["aprovadas_casa"]), help=c["aprovada_ajuda"])
        m[2].metric("Projetos de sua autoria", int(d["projetos_autor"]), help="Sem contar homenagens")
        m = st.columns(3)
        m[0].metric("Presença", fmt_pct(d["presenca"]), help=f"{int(d['votou'])} de {int(d['votacoes_periodo'])} votações")
        m[1].metric("Pedidos de fiscalização", int(d["pedidos_fiscalizacao"]))
        m[2].metric("Homenagens", int(d["homenagens"]), help="Nomes de rua, datas comemorativas, títulos")

    with aba_proj:
        meus = projs[projs["parl_id"] == d["id"]]
        if meus.empty:
            st.caption("Nenhum projeto de autoria principal nesta legislatura.")
        else:
            graf = grafico_temas(meus, "Projetos por tema (barra escura: viraram lei)")
            if graf is not None:
                st.altair_chart(graf, width="stretch")
            f1, f2 = st.columns([3, 1], vertical_alignment="bottom")
            temas = sorted({t for ts in meus["temas"] for t in ts})
            escolha = f1.multiselect("Filtrar por tema", temas, key=f"tp-{d['id']}", placeholder="Todos os temas")
            hom = f2.toggle("Incluir homenagens", key=f"hom-{d['id']}")
            lista = meus if hom else meus[~meus["homenagem"]]
            if escolha:
                lista = lista[tem_tema(lista, escolha)]
            lista = lista.assign(passo=lista["estagio"].map(lambda e: est[e][0]),
                                 andamento=lista["estagio"].map(lambda e: est[e][1]),
                                 temas_txt=lista["temas"].map(", ".join))
            lista = lista.sort_values(["passo", "data"], ascending=False)
            st.caption(f"{len(lista)} projetos · os mais avançados primeiro")
            st.dataframe(
                lista, hide_index=True, width="stretch",
                column_order=["link", "sigla", "data", "texto", "temas_txt", "passo", "andamento"],
                column_config={
                    "link": COL_LINK,
                    "sigla": st.column_config.TextColumn("Número", width="small"),
                    "data": st.column_config.DateColumn("Apresentado", format="DD/MM/YYYY"),
                    "texto": st.column_config.TextColumn("Do que trata", width="large"),
                    "temas_txt": "Temas",
                    "passo": st.column_config.ProgressColumn("Andamento", min_value=0, max_value=4, format=" "),
                    "andamento": "Situação",
                },
            )

    with aba_votos:
        meus = votos[votos["parl_id"] == d["id"]].merge(vots, on="votacao_id")
        if meus.empty:
            st.caption("Nenhuma votação registrada no período em que esteve no cargo.")
            return
        m = st.columns(3)
        m[0].metric("Votou com o governo", fmt_pct(d["alinh_governo"]),
                    help=f"Em {int(d['n_governo'])} votações em que o governo orientou Sim ou Não")
        m[1].metric("Votou com a maioria do partido", fmt_pct(d["alinh_partido"]),
                    help=f"Em {int(d['n_partido'])} votações. Em partidos muito pequenos esse número tende a 100%.")
        m[2].metric("Presença", fmt_pct(d["presenca"]))
        f1, f2, f3 = st.columns([2, 2, 1], vertical_alignment="bottom")
        temas = sorted({t for ts in meus["temas"] for t in ts})
        escolha = f1.multiselect("Tema", temas, key=f"tv-{d['id']}", placeholder="Todos os temas")
        tipos = f2.multiselect("Voto", sorted(set(VOTO_TEXTO.values())), key=f"vv-{d['id']}", placeholder="Todos os votos")
        so_principal = f3.toggle("Só o texto principal", value=True, key=f"sp-{d['id']}",
                                 help="Esconde votações de emendas, destaques e procedimentos")
        if so_principal:
            meus = meus[meus["texto_principal"]]
        if escolha:
            meus = meus[tem_tema(meus, escolha)]
        meus = meus.assign(voto_txt=meus["voto"].map(VOTO_TEXTO).fillna(meus["voto"]))
        if tipos:
            meus = meus[meus["voto_txt"].isin(tipos)]
        cont = meus["voto_txt"].value_counts()
        st.caption(" · ".join(f"**{n}** {k.lower()}" for k, n in cont.items()) or "Nenhuma votação nesse filtro.")
        st.dataframe(
            meus.sort_values("data", ascending=False), hide_index=True, width="stretch",
            column_order=["data", "link", "sigla", "ementa", "voto_txt", "governo", "resultado"],
            column_config={
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "link": COL_LINK,
                "sigla": st.column_config.TextColumn("Número", width="small"),
                "ementa": st.column_config.TextColumn("O que estava em votação", width="large"),
                "voto_txt": "Voto", "governo": "Governo orientou", "resultado": "Resultado",
            },
        )
        if not so_principal:
            st.caption("Em votações de emendas e destaques, \"A favor\" significa votar Sim ao que estava em votação, "
                       "que nem sempre é o projeto inteiro.")


def aba_parlamentares(c, meta, parl, projs, vots, votos) -> None:
    atuais = parl[parl["em_exercicio"]]
    f = st.columns([3, 1, 1, 2])
    busca = f[0].text_input(f"Buscar {c['cargo']}", placeholder="Nome", key=f"{c['pasta']}-busca")
    uf = f[1].selectbox("Estado", ["Todos"] + sorted(atuais["uf"].unique()), key=f"{c['pasta']}-uf")
    partido = f[2].selectbox("Partido", ["Todos"] + sorted(atuais["partido"].unique()), key=f"{c['pasta']}-partido")
    ordem = ORDENS[f[3].selectbox("Ordenar por", list(ORDENS), key=f"{c['pasta']}-ordem")]

    v = atuais
    if busca:
        v = v[v["nome"].map(sem_acento).str.contains(sem_acento(busca), regex=False)]
    if uf != "Todos":
        v = v[v["uf"] == uf]
    if partido != "Todos":
        v = v[v["partido"] == partido]
    v = v.sort_values([ordem, "score", "nome"], ascending=[False, False, True], na_position="last").reset_index(drop=True)

    st.caption(f"{len(v)} {c['cargos']} · clique em uma linha para ver a ficha completa")
    tabela = v.assign(presenca=v["presenca"] * 100, alinh_governo=v["alinh_governo"] * 100)
    sel = st.dataframe(
        tabela, hide_index=True, width="stretch", height=480, on_select="rerun", selection_mode="single-row",
        key=f"{c['pasta']}-lista",
        column_order=["posicao", "foto", "nome", "partido", "uf", "score", "viraram_lei", "presenca",
                      "projetos_autor", "pedidos_fiscalizacao", "alinh_governo"],
        column_config={
            "posicao": st.column_config.NumberColumn("#", format="%dº", width="small"),
            "foto": st.column_config.ImageColumn("", width="small"),
            "nome": st.column_config.TextColumn(c["cargo"].capitalize(), width="medium"),
            "partido": "Partido",
            "uf": st.column_config.TextColumn("UF", width="small"),
            "score": st.column_config.ProgressColumn("Nota", min_value=0, max_value=100, format="%d"),
            "viraram_lei": st.column_config.NumberColumn("Leis", help="Projetos que viraram lei"),
            "presenca": st.column_config.NumberColumn("Presença", format="%.0f%%"),
            "projetos_autor": st.column_config.NumberColumn("Projetos", help="Sem contar homenagens"),
            "pedidos_fiscalizacao": st.column_config.NumberColumn("Fiscalização"),
            "alinh_governo": st.column_config.NumberColumn("Com o governo", format="%.0f%%",
                                                           help="Votou igual à orientação do governo. Não entra na nota."),
        },
    )
    if sel.selection.rows:
        st.divider()
        ficha(v.iloc[sel.selection.rows[0]], c, meta, parl, projs, vots, votos)


def aba_votacoes(c, parl, vots, votos) -> None:
    st.markdown(f"Votações nominais abertas do plenário sobre projetos, da mais recente para a mais antiga. "
                f"Clique em uma para ver como cada partido e cada {c['cargo']} votou.")
    p = c["pasta"]
    f = st.columns([3, 2, 1], vertical_alignment="bottom")
    busca = f[0].text_input("Buscar no assunto ou autor", placeholder="Ex.: reforma tributária, aposentadoria, armas",
                            key=f"{p}-vbusca")
    temas = sorted({t for ts in vots["temas"] for t in ts})
    escolha = f[1].multiselect("Tema", temas, placeholder="Todos os temas", key=f"{p}-vtemas")
    so_principal = f[2].toggle("Só o texto principal", value=True, key=f"{p}-vprincipal")

    # Voto de um político específico em cada votação da lista
    opcoes = parl.sort_values(["em_exercicio", "nome"], ascending=[False, True])
    rotulos = {r.id: f"{r.nome} ({r.partido}-{r.uf})" for r in opcoes.itertuples()}
    f = st.columns([3, 3], vertical_alignment="bottom")
    quem = f[0].selectbox(f"Ver como um {c['cargo']} votou", list(rotulos), format_func=rotulos.get,
                          index=None, placeholder=f"Escolha um {c['cargo']}", key=f"{p}-vquem")
    filtro_voto = f[1].multiselect("Mostrar só quando ele votou", sorted(set(VOTO_TEXTO.values())),
                                   placeholder="Qualquer voto", key=f"{p}-vquemvoto", disabled=quem is None)

    v = vots[vots["texto_principal"]] if so_principal else vots
    if busca:
        alvo = sem_acento(busca)
        v = v[(v["ementa"].fillna("") + " " + v["sigla"].fillna("") + " " + v["autor"].fillna(""))
              .map(sem_acento).str.contains(alvo, regex=False)]
    if escolha:
        v = v[tem_tema(v, escolha)]
    colunas = ["data", "sigla", "ementa", "autor", "resultado", "sim", "nao", "governo"]
    if quem is not None:
        dele = votos[votos["parl_id"] == quem][["votacao_id", "voto"]]
        v = v.merge(dele, on="votacao_id", how="inner")
        v["voto_de"] = v["voto"].map(VOTO_TEXTO).fillna(v["voto"])
        if filtro_voto:
            v = v[v["voto_de"].isin(filtro_voto)]
        colunas.insert(4, "voto_de")
    v = v.sort_values("data", ascending=False).reset_index(drop=True)
    st.caption(f"{len(v)} votações" + (f" em que {rotulos[quem].split(' (')[0]} estava no cargo" if quem is not None else ""))
    sel = st.dataframe(
        v, hide_index=True, width="stretch", height=380, on_select="rerun", selection_mode="single-row",
        key=f"{p}-vlista", column_order=colunas,
        column_config={
            "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
            "sigla": st.column_config.TextColumn("Projeto", width="small"),
            "ementa": st.column_config.TextColumn("Assunto", width="large"),
            "autor": st.column_config.TextColumn("Autor do projeto", width="medium"),
            "voto_de": st.column_config.TextColumn(f"Voto de {rotulos[quem].split(' (')[0]}" if quem is not None else "Voto"),
            "resultado": "Resultado", "sim": "Sim", "nao": "Não", "governo": "Governo orientou",
        },
    )
    if not sel.selection.rows:
        return
    vt = v.iloc[sel.selection.rows[0]]
    st.divider()
    st.subheader(f"{vt['sigla']} · {vt['data']:%d/%m/%Y}")
    st.write(vt["ementa"])
    st.caption(f"Autor: {vt['autor'] or 'não informado'}  \n{vt['descricao']}  \n[Ver o projeto no site oficial]({vt['link']})")
    m = st.columns(4)
    m[0].metric("Resultado", vt["resultado"])
    m[1].metric("Sim", int(vt["sim"]))
    m[2].metric("Não", int(vt["nao"]))
    m[3].metric("Governo orientou", vt["governo"])

    vs = votos[votos["votacao_id"] == vt["votacao_id"]].merge(parl[["id", "nome", "uf"]], left_on="parl_id", right_on="id")
    vs["grupo"] = vs["voto"].map(GRUPO_VOTO).fillna("Outros")
    por_partido = vs.groupby(["partido", "grupo"]).size().rename("votos").reset_index()
    ordem_partidos = (vs.assign(f=vs["grupo"] == "A favor").groupby("partido")["f"].mean()
                      .sort_values(ascending=False).index.tolist())
    graf = alt.Chart(por_partido, title="Como cada partido votou").mark_bar().encode(
        y=alt.Y("partido:N", sort=ordem_partidos, title=None),
        x=alt.X("votos:Q", stack="normalize", title="Parte da bancada", axis=alt.Axis(format="%")),
        color=alt.Color("grupo:N", title="Voto", scale=alt.Scale(domain=list(CORES_VOTO), range=list(CORES_VOTO.values())),
                        legend=alt.Legend(orient="top")),
        order=alt.Order("ordem:Q"),
        tooltip=["partido", alt.Tooltip("grupo", title="Voto"), alt.Tooltip("votos", title=c["cargos"].capitalize())],
    ).transform_calculate(
        ordem="indexof(['A favor','Contra','Outros','Não votou'], datum.grupo)"
    ).properties(height=max(160, 22 * len(ordem_partidos)))
    st.altair_chart(graf, width="stretch")

    st.markdown(f"**Quem votou como**")
    vs = vs.assign(voto_txt=(vs["voto"].map(VOTO_TEXTO) if vt["texto_principal"] else vs["voto"]).fillna(vs["voto"]))
    f = st.columns([2, 2, 1, 1])
    nome = f[0].text_input("Buscar nome", key=f"{p}-dnome", placeholder=f"Nome do {c['cargo']}")
    tipos = f[1].multiselect("Voto", sorted(vs["voto_txt"].unique()), key=f"{p}-dvoto", placeholder="Todos os votos")
    partido = f[2].selectbox("Partido", ["Todos"] + sorted(vs["partido"].dropna().unique()), key=f"{p}-dpartido")
    uf = f[3].selectbox("Estado", ["Todos"] + sorted(vs["uf"].dropna().unique()), key=f"{p}-duf")
    lista = vs
    if nome:
        lista = lista[lista["nome"].map(sem_acento).str.contains(sem_acento(nome), regex=False)]
    if tipos:
        lista = lista[lista["voto_txt"].isin(tipos)]
    if partido != "Todos":
        lista = lista[lista["partido"] == partido]
    if uf != "Todos":
        lista = lista[lista["uf"] == uf]
    st.caption(" · ".join(f"**{n}** {k.lower()}" for k, n in lista["voto_txt"].value_counts().items()))
    st.dataframe(lista.sort_values(["voto_txt", "nome"]), hide_index=True, width="stretch",
                 column_order=["nome", "partido", "uf", "voto_txt"],
                 column_config={"nome": c["cargo"].capitalize(), "partido": "Partido", "uf": "UF", "voto_txt": "Voto"})


def aba_temas(c, parl, projs, vots) -> None:
    p = c["pasta"]
    st.markdown(f"{c['temas']} Um projeto pode ter mais de um tema.")
    graf = grafico_temas(projs, f"Projetos apresentados por {c['cargos']}, por tema (barra escura: viraram lei)", limite=32)
    if graf is not None:
        st.altair_chart(graf, width="stretch")
    temas = sorted({t for ts in projs[~projs["homenagem"]]["temas"] for t in ts})
    if not temas:
        return
    tema = st.selectbox("Escolha um tema para ver os detalhes", temas,
                        index=temas.index("Saúde") if "Saúde" in temas else 0, key=f"{p}-tema")
    no_tema = projs[tem_tema(projs, [tema]) & ~projs["homenagem"]]
    vt_tema = vots[vots["texto_principal"] & tem_tema(vots, [tema])]
    m = st.columns(4)
    m[0].metric("Projetos apresentados", len(no_tema))
    m[1].metric("Viraram lei", int((no_tema["estagio"] == "lei").sum()))
    m[2].metric(c["aprovada"], int((no_tema["estagio"] == "aprovada_casa").sum()))
    m[3].metric("Votações no plenário", len(vt_tema))

    nomes = parl.set_index("id")[["nome", "partido", "uf"]]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Quem mais trabalha em {tema}**")
        top = (no_tema.groupby("parl_id").agg(projetos=("id", "count"), leis=("estagio", lambda s: (s == "lei").sum()))
               .join(nomes).sort_values(["leis", "projetos"], ascending=False).head(15))
        st.dataframe(top, hide_index=True, width="stretch", column_order=["nome", "partido", "uf", "leis", "projetos"],
                     column_config={"nome": c["cargo"].capitalize(), "partido": "Partido", "uf": "UF",
                                    "leis": "Viraram lei", "projetos": "Projetos"})
    with c2:
        st.markdown(f"**Projetos que viraram lei em {tema}**")
        leis = no_tema[no_tema["estagio"] == "lei"].join(nomes, on="parl_id").sort_values("data", ascending=False)
        leis = leis.assign(autor=leis["nome"] + " (" + leis["partido"] + "-" + leis["uf"] + ")")
        st.dataframe(leis, hide_index=True, width="stretch", column_order=["link", "sigla", "texto", "autor"],
                     column_config={"link": COL_LINK, "sigla": st.column_config.TextColumn("Número", width="small"),
                                    "texto": st.column_config.TextColumn("Do que trata", width="large"), "autor": "Autor"})


def aba_metodo(c, meta) -> None:
    st.markdown(f"Usamos só dados oficiais. Cada {c['cargo']} recebe quatro notas parciais, e cada uma diz qual a "
                f"porcentagem de colegas da mesma Casa que ele supera naquele quesito. A nota geral é a média "
                f"ponderada. Deputados e senadores são comparados só com colegas da própria Casa.")
    cols = st.columns(4)
    for col, (_, peso, nome, texto) in zip(cols, COMPONENTES):
        col.metric(nome, f"{round(meta['pesos'][peso] * 100)}%")
        col.caption(texto or c["fiscalizacao"])
    st.markdown(f"""
- **Homenagens quase não contam.** Projetos que só dão nome a ruas, criam datas comemorativas ou concedem títulos valem 10% de um projeto comum.
- **Assinar junto vale menos.** O autor principal ganha o ponto inteiro. Quem só assinou como coautor ganha um quarto.
- **Licenças não prejudicam.** Quem se afastou só é cobrado pelas votações do período em que estava no cargo.
- **Só entra no ranking** quem está em exercício hoje e participou de pelo menos {meta['min_votacoes']} votações no plenário.
- **Votar com o governo ou com o partido não entra na nota.** Esses números mostram o perfil, sem dizer se isso é bom ou ruim.
""")
    if c["pasta"] == "senado":
        st.markdown("- **No Senado, votações secretas** (como a escolha de autoridades) contam para a presença, "
                    "mas não aparecem na lista de votos, porque o voto de cada senador não é divulgado.\n"
                    "- **Ausências justificadas** (missão oficial, atividade parlamentar) contam como ausência, "
                    "mas aparecem separadas na lista de votos.")
    st.info("A nota mede o trabalho individual no plenário e nos projetos. Ela ainda não capta poder político: "
            "quem preside a Casa, lidera partido ou relata projetos importantes pode ter muita influência e nota "
            "baixa. A presença conta só votações nominais no plenário, não comissões. "
            "Use a nota como ponto de partida, não como veredito.")


PRESIDENCIA = "Presidência da República"
# Cores por resultado: teal para o que virou lei ou foi mantido, laranja para o que perdeu a validade ou foi
# derrubado, cinza para o que ainda está em análise
CORES_MPV = {"Virou lei": "#0d6b70", "Virou lei com mudanças": "#5aa6a8", "Perdeu a validade": "#c4622d",
             "Revogada pelo governo": "#e0a47e", "Em análise no Congresso": "#c9cdc8"}
CORES_VETO = {"Veto mantido": "#0d6b70", "Veto derrubado em parte": "#e0a47e", "Veto derrubado": "#c4622d",
              "Prejudicado": "#9aa3ab", "Aguardando o Congresso": "#c9cdc8"}


@st.cache_data
def carregar_presidencia():
    g = GOLD / "presidencia"
    meta = json.loads((g / "meta.json").read_text(encoding="utf-8"))
    dados = {n: pd.read_parquet(g / f"{n}.parquet") for n in ("mpv", "vetos", "projetos", "apoio")}
    for n in ("mpv", "projetos", "apoio"):
        dados[n]["temas"] = dados[n]["temas"].map(list)
    return meta, dados


def barras_resultado(df: pd.DataFrame, grupo: str, cores: dict, titulo: str):
    cont = df.groupby([grupo, "resultado"]).size().rename("quantidade").reset_index()
    ordem = list(cores)
    return alt.Chart(cont, title=titulo).mark_bar().encode(
        y=alt.Y(f"{grupo}:N", title=None),
        x=alt.X("quantidade:Q", title="Quantidade"),
        color=alt.Color("resultado:N", title="Resultado", scale=alt.Scale(domain=ordem, range=list(cores.values())),
                        legend=alt.Legend(orient="top", columns=3)),
        order=alt.Order("ordem:Q"),
        tooltip=[alt.Tooltip(f"{grupo}:N", title="Tipo"), alt.Tooltip("resultado:N", title="Resultado"),
                 alt.Tooltip("quantidade:Q", title="Quantidade")],
    ).transform_calculate(ordem=f"indexof({ordem}, datum.resultado)").properties(height=60 * cont[grupo].nunique() + 40)


def filtrar(df: pd.DataFrame, chave: str, tipos: list, resultados: list, coluna_texto: str) -> pd.DataFrame:
    f = st.columns([2, 2, 3])
    tipo = f[0].multiselect("Tipo", tipos, placeholder="Todos", key=f"{chave}-tipo")
    res = f[1].multiselect("Resultado", resultados, placeholder="Todos", key=f"{chave}-res")
    busca = f[2].text_input("Buscar no assunto", key=f"{chave}-busca")
    if tipo:
        df = df[df["tipo"].isin(tipo)]
    if res:
        df = df[df["resultado"].isin(res)]
    if busca:
        df = df[df[coluna_texto].map(sem_acento).str.contains(sem_acento(busca), regex=False)]
    return df


CURADORIA = Path(__file__).resolve().parent / "data" / "curadoria"
# PLACAR_REVISAO=1 mostra também as sugestões ainda não revisadas (para quem faz a curadoria)
MODO_REVISAO = os.environ.get("PLACAR_REVISAO") == "1"
STATUS_PROMESSA = {"Cumprida": "#0d6b70", "Cumprida em parte": "#5aa6a8", "Em andamento": "#c9cdc8",
                   "Não cumprida": "#c4622d", "Não iniciada": "#e6e8e4"}


def aba_promessas(arquivo: str, origem: str) -> None:
    arq = CURADORIA / arquivo
    if not arq.exists():
        st.info("Promessas ainda não cadastradas.")
        return
    p = pd.read_csv(arq, sep=";", encoding="utf-8-sig", dtype=str).fillna("")
    p["revisada"] = p["revisado"].str.strip().str.lower().isin(["sim", "s"])
    p["status"] = p["status_final"].where(p["status_final"].str.strip() != "", p["status_sugerido"])
    if not MODO_REVISAO:
        p = p[p["revisada"]]
    st.markdown(f"Compromissos concretos retirados de {origem}. Cada um tem o parágrafo de origem, a situação e a "
                "prova usada para classificar. Diretrizes genéricas, que não dá para verificar, ficaram de fora.")
    if MODO_REVISAO:
        st.warning(f"**Modo revisão.** Aparecem também as sugestões ainda não revisadas "
                   f"({int((~p['revisada']).sum())} de {len(p)}). Para publicar, marque `revisado = sim` na planilha "
                   f"`data/curadoria/{arquivo}`.")
    if p.empty:
        st.info("Nenhuma promessa revisada ainda. Elas aparecem aqui depois da revisão.")
        return
    presentes = [s for s in STATUS_PROMESSA if (p["status"] == s).any()]
    m = st.columns(max(len(presentes), 1))
    for col, s in zip(m, presentes):
        col.metric(s, int((p["status"] == s).sum()))
    f = st.columns(2)
    temas = f[0].multiselect("Tema", sorted(p["tema"].unique()), placeholder="Todos", key=f"{arquivo}-tema")
    status = f[1].multiselect("Situação", list(STATUS_PROMESSA), placeholder="Todas", key=f"{arquivo}-status")
    v = p
    if temas:
        v = v[v["tema"].isin(temas)]
    if status:
        v = v[v["status"].isin(status)]
    v = v.assign(situacao=v["status"] + v["revisada"].map({True: "", False: " (sugestão)"}),
                 paragrafo_txt=v["paragrafo"].map(lambda x: f"§ {x}, " if x else "") + "p. " + v["pagina"])
    st.dataframe(v, hide_index=True, width="stretch",
                 column_order=["compromisso", "tema", "situacao", "justificativa", "evidencia", "evidencia_url",
                               "paragrafo_txt", "trecho_original"],
                 column_config={"compromisso": st.column_config.TextColumn("Compromisso", width="medium"),
                                "tema": "Tema", "situacao": "Situação",
                                "justificativa": st.column_config.TextColumn("Por quê", width="large"),
                                "evidencia": "Prova",
                                "evidencia_url": st.column_config.LinkColumn("Link", display_text="abrir"),
                                "paragrafo_txt": st.column_config.TextColumn("No plano", width="small"),
                                "trecho_original": st.column_config.TextColumn("Texto do plano", width="large")})
    st.caption(f"Situação verificada em {p['verificado_em'].max()}. Uma promessa \"em andamento\" tem ação concreta "
               "(projeto enviado, programa criado) mas ainda sem resultado final.")


GOVERNADORES = "Governadores"


def pagina_governadores() -> None:
    g = GOLD / "governadores"
    meta = json.loads((g / "meta.json").read_text(encoding="utf-8"))
    gov = pd.read_parquet(g / "governadores.parquet")
    raiz = Path(__file__).resolve().parent
    st.caption(f"GOVERNADORES ELEITOS EM 2026 · MANDATO 2027–2030 · DADOS DO TSE DE {meta['tse_gerado_em']}")
    st.markdown("Os governadores eleitos em outubro de 2026 tomam posse em **6 de janeiro de 2027**. Até lá, mostramos "
                "quem foi eleito e o que prometeu no plano de governo registrado no TSE. Depois da posse, cada "
                "promessa passa a ser acompanhada com prova, como fazemos com a Presidência.")
    eleitos = gov[gov["eleito"]]
    pendentes = gov[~gov["eleito"]]
    m = st.columns(3)
    m[0].metric("Governadores eleitos", f"{len(eleitos)} de 27")
    m[1].metric("Estados aguardando o 2º turno oficial", pendentes["uf"].nunique())
    m[2].metric("Partidos com governador", eleitos["partido"].nunique())

    por_partido = eleitos.groupby("partido").size().rename("estados").reset_index()
    graf = alt.Chart(por_partido, title="Governadores eleitos por partido").mark_bar(color=COR, cornerRadiusEnd=4).encode(
        y=alt.Y("partido:N", sort="-x", title=None), x=alt.X("estados:Q", title="Estados", axis=alt.Axis(tickMinStep=1)),
        tooltip=[alt.Tooltip("partido:N", title="Partido"), alt.Tooltip("estados:Q", title="Estados")],
    ).properties(height=max(120, 26 * len(por_partido)))
    st.altair_chart(graf, width="stretch")
    if len(pendentes):
        st.info(f"Em {pendentes['uf'].nunique()} estados ({', '.join(sorted(pendentes['uf'].unique()))}) houve 2º turno "
                "em 25/10/2026. O resultado entra aqui assim que o TSE publicar os dados oficiais.")

    tabela = gov.assign(chapa=gov["nome"] + " / vice " + gov["vice"])
    st.dataframe(tabela, hide_index=True, width="stretch",
                 column_order=["uf", "nome", "partido", "vice", "coligacao", "situacao", "plano_paginas"],
                 column_config={"uf": st.column_config.TextColumn("UF", width="small"), "nome": "Governador(a)",
                                "partido": "Partido", "vice": "Vice", "coligacao": "Coligação", "situacao": "Situação",
                                "plano_paginas": st.column_config.NumberColumn("Plano (páginas)")})

    st.divider()
    ufs = sorted(gov["uf"].unique())
    uf = st.selectbox("Escolha um estado", ufs, index=ufs.index("MG") if "MG" in ufs else 0, key="gov-uf")
    for r in gov[gov["uf"] == uf].itertuples():
        st.subheader(f"{r.nome} ({r.partido}-{r.uf})")
        st.caption(f"{r.nome_completo} · vice: {r.vice} · {r.situacao}"
                   + (f" · coligação {r.coligacao}: {r.composicao}" if r.coligacao else ""))
        if r.plano_pdf and (raiz / r.plano_pdf).exists():
            st.download_button(f"Baixar o plano de governo ({r.plano_paginas} páginas, PDF oficial do TSE)",
                               (raiz / r.plano_pdf).read_bytes(), file_name=f"plano-governo-{r.uf}-{r.sq}.pdf",
                               mime="application/pdf", key=f"pdf-{r.sq}")
        elif r.plano_paginas:
            # No servidor público os PDFs não vão junto (135 MB); o link leva ao pacote oficial do estado no TSE
            st.link_button(f"Plano de governo no TSE ({r.plano_paginas} páginas, arquivo {Path(r.plano_pdf).name})",
                           f"https://cdn.tse.jus.br/estatistica/sead/odsele/proposta_governo/proposta_governo_2026_{r.uf}.zip")
        if r.eleito:
            aba_promessas(f"promessas_governador_{r.uf}_2027_2030.csv",
                          f"o plano de governo registrado no TSE por {r.nome} em 2026")


def pagina_presidencia() -> None:
    meta, d = carregar_presidencia()
    mpv, vetos, projs, apoio = d["mpv"], d["vetos"], d["projetos"], d["apoio"]
    atualizado = date.fromisoformat(meta["atualizado_em"]).strftime("%d/%m/%Y")
    st.caption(f"PRESIDÊNCIA DA REPÚBLICA · MANDATO 2023–2026 · DADOS ATÉ {atualizado}")
    st.markdown("O presidente não vota no Congresso. O trabalho dele aparece de quatro formas: as **medidas provisórias** "
                "que edita, os **projetos** que envia, os **vetos** que aplica e o **apoio** que consegue nas votações. "
                "Aqui não há nota de 0 a 100, porque não existe com quem comparar no mesmo período.")
    abas = st.tabs(["Resumo", "Medidas provisórias", "Projetos enviados", "Vetos", "Apoio no Congresso", "Promessas"])

    with abas[0]:
        leis_mpv = mpv["resultado"].str.startswith("Virou lei")
        derrubados = vetos["resultado"].isin(["Veto derrubado", "Veto derrubado em parte"])
        venc = apoio[apoio["texto_principal"]].groupby("casa")["vitoria"].mean()
        m = st.columns(4)
        m[0].metric("Medidas provisórias", len(mpv), help="Editadas desde jan/2023")
        m[1].metric("MPs que viraram lei", f"{leis_mpv.sum()} ({leis_mpv.mean():.0%})")
        m[2].metric("Projetos enviados", len(projs), help="Projetos de lei, de lei complementar e PECs")
        m[3].metric("Projetos que viraram lei", int((projs["estagio"] == "lei").sum()))
        m = st.columns(4)
        m[0].metric("Vetos", len(vetos))
        m[1].metric("Vetos derrubados", int(derrubados.sum()), help="Total ou em parte")
        m[2].metric("Vetos ainda sem análise", int((vetos["resultado"] == "Aguardando o Congresso").sum()))
        m[3].metric("Venceu no texto principal", " · ".join(f"{c} {venc[c]:.0%}" for c in venc.index),
                    help="Votações do texto dos projetos em que o governo orientou Sim ou Não")

    with abas[1]:
        st.markdown("A medida provisória vale como lei assim que é publicada, mas perde a validade se o Congresso não "
                    "aprovar em até 120 dias. Há dois tipos bem diferentes:\n"
                    "- **Crédito extraordinário** libera dinheiro para uma urgência. O dinheiro é usado na hora, então "
                    "perder a validade depois é o caminho normal.\n"
                    "- **As que mudam leis** dependem do Congresso. Perder a validade, nesse caso, geralmente significa "
                    "que o Congresso não quis votar, ou que o conteúdo foi incluído em outro projeto.")
        st.altair_chart(barras_resultado(mpv, "tipo", CORES_MPV, "O que aconteceu com as medidas provisórias"), width="stretch")
        v = filtrar(mpv, "mpv", sorted(mpv["tipo"].unique()), list(CORES_MPV), "ementa")
        st.caption(f"{len(v)} medidas provisórias")
        st.dataframe(v.sort_values("data", ascending=False), hide_index=True, width="stretch",
                     column_order=["link", "sigla", "data", "ementa", "tipo", "resultado"],
                     column_config={"link": COL_LINK, "sigla": st.column_config.TextColumn("Número", width="small"),
                                    "data": st.column_config.DateColumn("Editada em", format="DD/MM/YYYY"),
                                    "ementa": st.column_config.TextColumn("Do que trata", width="large"),
                                    "tipo": "Tipo", "resultado": "O que aconteceu"})

    with abas[2]:
        st.markdown("Projetos de lei, de lei complementar e propostas de emenda à Constituição que o governo enviou ao "
                    "Congresso. Eles começam pela Câmara e depois vão ao Senado.")
        est = estagios(CASAS["Câmara dos Deputados"])
        v = projs.assign(passo=projs["estagio"].map(lambda e: est[e][0]),
                         andamento=projs["estagio"].map(lambda e: est[e][1]),
                         temas_txt=projs["temas"].map(", ".join))
        st.caption(" · ".join(f"**{n}** {k.lower()}" for k, n in v["andamento"].value_counts().items()))
        st.dataframe(v.sort_values(["passo", "data"], ascending=False), hide_index=True, width="stretch",
                     column_order=["link", "sigla", "data", "texto", "temas_txt", "passo", "andamento"],
                     column_config={"link": COL_LINK, "sigla": st.column_config.TextColumn("Número", width="small"),
                                    "data": st.column_config.DateColumn("Enviado em", format="DD/MM/YYYY"),
                                    "texto": st.column_config.TextColumn("Do que trata", width="large"),
                                    "temas_txt": "Temas",
                                    "passo": st.column_config.ProgressColumn("Andamento", min_value=0, max_value=4, format=" "),
                                    "andamento": "Situação"})

    with abas[3]:
        st.markdown("Quando o Congresso aprova um projeto, o presidente pode vetar o texto inteiro (**veto total**) ou "
                    "trechos (**veto parcial**). O Congresso decide depois se mantém ou derruba o veto. Enquanto não "
                    "decide, o veto vale.")
        st.altair_chart(barras_resultado(vetos, "tipo", CORES_VETO, "O que o Congresso decidiu sobre os vetos"), width="stretch")
        v = filtrar(vetos, "veto", ["Total", "Parcial"], list(CORES_VETO), "assunto")
        st.caption(f"{len(v)} vetos")
        st.dataframe(v.sort_values("data", ascending=False), hide_index=True, width="stretch",
                     column_order=["link", "sigla", "data", "tipo", "projeto", "assunto", "resultado"],
                     column_config={"link": COL_LINK, "sigla": st.column_config.TextColumn("Veto", width="small"),
                                    "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                                    "tipo": "Tipo", "projeto": "Projeto vetado",
                                    "assunto": st.column_config.TextColumn("Do que trata", width="large"),
                                    "resultado": "Decisão do Congresso"})

    with abas[4]:
        st.markdown("Em cada votação, o líder do governo orienta os parlamentares a votar Sim ou Não. O governo **venceu** "
                    "quando o resultado foi o que ele orientou. Votações de emendas, destaques e requerimentos costumam "
                    "ser mais disputadas que as do texto principal.")
        so_principal = st.toggle("Só votações do texto principal", value=True, key="apoio-principal")
        v = apoio[apoio["texto_principal"]] if so_principal else apoio
        semestre = v["data"].map(lambda x: f"{x.year} · {1 if x.month <= 6 else 2}º sem")
        serie = v.assign(semestre=semestre).groupby(["casa", "semestre"]).agg(
            taxa=("vitoria", "mean"), votacoes=("vitoria", "size")).reset_index()
        graf = alt.Chart(serie, title="Parte das votações em que o governo venceu, por semestre").mark_line(
            point=alt.OverlayMarkDef(size=60, filled=True), strokeWidth=2).encode(
            x=alt.X("semestre:N", title=None, sort=sorted(serie["semestre"].unique())),
            y=alt.Y("taxa:Q", title=None, axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("casa:N", title=None, scale=alt.Scale(domain=["Câmara", "Senado"], range=[COR, "#c4622d"]),
                            legend=alt.Legend(orient="top")),
            tooltip=[alt.Tooltip("casa:N", title="Casa"), alt.Tooltip("semestre:N", title="Semestre"),
                     alt.Tooltip("taxa:Q", title="Venceu", format=".0%"), alt.Tooltip("votacoes:Q", title="Votações")],
        ).properties(height=280)
        st.altair_chart(graf, width="stretch")
        m = st.columns(2)
        for col, (casa, rotulo) in zip(m, [("Câmara", "Venceu na Câmara"), ("Senado", "Venceu no Senado")]):
            x = v[v["casa"] == casa]
            if len(x):
                col.metric(rotulo, f"{x['vitoria'].mean():.0%}", help=f"{int(x['vitoria'].sum())} de {len(x)} votações")
        st.markdown("**Derrotas do governo**")
        der = v[~v["vitoria"]].assign(orientou=lambda x: x["orientacao_governo"].map({"Sim": "A favor", "Não": "Contra"}),
                                      resultado=lambda x: x["aprovada"].map({True: "Aprovado", False: "Rejeitado"}))
        st.dataframe(der.sort_values("data", ascending=False), hide_index=True, width="stretch",
                     column_order=["data", "casa", "sigla", "ementa", "autor", "orientou", "resultado"],
                     column_config={"data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                                    "casa": "Casa", "sigla": st.column_config.TextColumn("Projeto", width="small"),
                                    "ementa": st.column_config.TextColumn("Assunto", width="large"),
                                    "autor": "Autor do projeto", "orientou": "Governo orientou", "resultado": "Resultado"})

    with abas[5]:
        aba_promessas("promessas_presidencia_2023_2026.csv",
                      "o plano de governo registrado no TSE pela chapa eleita em 2022 "
                      "(\"Diretrizes para o programa de reconstrução e transformação do Brasil\", agosto de 2022)")

    st.caption("Fontes: [Dados Abertos do Senado Federal](https://www12.senado.leg.br/dados-abertos) (medidas provisórias "
               "e vetos) e [Dados Abertos da Câmara dos Deputados](https://dadosabertos.camara.leg.br) (projetos e votações). "
               "Projeto independente e apartidário.")


def main() -> None:
    st.title("Placar do Mandato")
    disponiveis = [n for n, c in CASAS.items() if (GOLD / c["pasta"] / "parlamentares.parquet").exists()]
    if (GOLD / "presidencia" / "mpv.parquet").exists():
        disponiveis.append(PRESIDENCIA)
    if (GOLD / "governadores" / "governadores.parquet").exists():
        disponiveis.append(GOVERNADORES)
    if not disponiveis:
        st.error("Dados não encontrados. Rode os scripts de coleta e cálculo em `pipeline/` (veja o README).")
        return
    nome = st.segmented_control("Casa", disponiveis, default=disponiveis[0], label_visibility="collapsed") or disponiveis[0]
    if nome == PRESIDENCIA:
        pagina_presidencia()
        return
    if nome == GOVERNADORES:
        pagina_governadores()
        return
    c = CASAS[nome]
    meta, parl, projs, vots, votos = carregar(c["pasta"])
    atualizado = date.fromisoformat(meta["atualizado_em"]).strftime("%d/%m/%Y")
    st.caption(f"{nome.upper()} · 57ª LEGISLATURA · DADOS ATÉ {atualizado}")
    st.markdown(f"Veja o que cada {c['cargo']} fez desde 2023: quantos projetos viraram lei, como votou, quanto aparece "
                f"para votar e quanto fiscaliza o governo. A nota vai de 0 a 100 e compara cada {c['cargo']} com os colegas.")

    abas = st.tabs([c["aba"], "Votações", "Temas", "Como a nota é calculada"])
    with abas[0]:
        aba_parlamentares(c, meta, parl, projs, vots, votos)
    with abas[1]:
        aba_votacoes(c, parl, vots, votos)
    with abas[2]:
        aba_temas(c, parl, projs, vots)
    with abas[3]:
        aba_metodo(c, meta)

    st.caption(f"Fonte: {c['fonte']}. Projeto independente e apartidário. Em breve: governadores e Presidência.")


main()
