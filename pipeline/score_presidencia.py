"""Monta os dados da Presidência da República para o app.

Entradas: data/raw/presidencia (coleta_presidencia.py), data/raw/camara (projetos do Executivo) e
          data/gold/{camara,senado}/votacoes.parquet (orientação do governo e resultado de cada votação)
Saída em data/gold/presidencia:
    meta.json
    mpv.parquet        medidas provisórias e o que aconteceu com cada uma
    vetos.parquet      vetos e a decisão do Congresso
    projetos.parquet   projetos de lei e PECs enviados pelo Executivo
    apoio.parquet      votações em que o governo orientou, e se ele venceu
"""
import json
import re
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from score_camara import ESTAGIOS, RAW as RAW_CAMARA, LINK as LINK_CAMARA
from score_senado import LINK as LINK_SENADO, temas

RAIZ = Path(__file__).resolve().parent.parent
RAW = RAIZ / "data" / "raw" / "presidencia"
GOLD = RAIZ / "data" / "gold" / "presidencia"
INICIO = date(2023, 1, 1)

RESULTADO_MPV = {
    "Aprovada na íntegra": "Virou lei",
    "Aprovada na forma de Projeto de Lei de Conversão": "Virou lei com mudanças",
    "Perda de eficácia, em decorrência do término do prazo para sua votação no Congresso": "Perdeu a validade",
    "Revogada": "Revogada pelo governo",
}
RESULTADO_VETO = {
    "Mantida": "Veto mantido",
    "Mantida parcialmente": "Veto derrubado em parte",
    "Rejeitada pelo Plenário": "Veto derrubado",
    "Prejudicada": "Prejudicado",
}


def ler(nome: str) -> dict:
    return json.loads((RAW / nome).read_text(encoding="utf-8"))


def mpvs() -> pd.DataFrame:
    x = ler("MPV.json")
    linhas = []
    for p in x["lista"]:
        d = x["detalhes"].get(str(p["id"]), {})
        delib = (d.get("deliberacao") or {}).get("tipoDeliberacao")
        ementa = re.sub(r"\s+", " ", p.get("ementa") or "")
        linhas.append({
            "id": p["id"], "sigla": p["identificacao"], "data": date.fromisoformat(p["dataApresentacao"][:10]),
            "ementa": ementa,
            # Crédito extraordinário libera dinheiro na hora; perder a validade depois é o caminho normal
            "tipo": "Crédito extraordinário" if ementa.lower().startswith("abre crédito extraordinário") else "Muda leis",
            "resultado": RESULTADO_MPV.get(delib, "Em análise no Congresso"),
            "situacao": (d.get("situacaoAtual") or "").capitalize(),
            "temas": temas(d.get("classificacoes")),
            "link": LINK_SENADO + str(p["codigoMateria"]),
        })
    return pd.DataFrame(linhas)


def vetos() -> pd.DataFrame:
    x = ler("VET.json")
    linhas = []
    for p in x["lista"]:
        d = x["detalhes"].get(str(p["id"]), {})
        delib = (d.get("deliberacao") or {}).get("tipoDeliberacao")
        ementa = re.sub(r"\s+", " ", p.get("ementa") or "")
        projeto = re.search(r"aposto ao (.+?)(?:, que| \(|$)", ementa)
        assunto = re.search(r"que [\"“](.+?)[\"”]", ementa)
        linhas.append({
            "id": p["id"], "sigla": p["identificacao"], "data": date.fromisoformat(p["dataApresentacao"][:10]),
            "tipo": "Total" if "veto total" in ementa.lower() else "Parcial",
            "projeto": projeto.group(1) if projeto else "",
            "assunto": assunto.group(1) if assunto else ementa,
            "resultado": RESULTADO_VETO.get(delib, "Aguardando o Congresso"),
            "norma": p.get("normaGerada") or "",
            "link": LINK_SENADO + str(p["codigoMateria"]),
        })
    return pd.DataFrame(linhas)


def projetos_executivo() -> pd.DataFrame:
    """PL, PLP e PEC de autoria do Poder Executivo apresentados na Câmara, onde começam esses projetos."""
    csv = "delim=';', all_varchar=true, quote='\"', escape='\"', union_by_name=true"
    casos = " ".join(f"when s in ({', '.join(repr(v) for v in vals)}) then '{nome}'" for nome, vals in ESTAGIOS.items())
    vago = r"^(altera|acrescenta|d[aá] nova reda|modifica|revoga)"
    return duckdb.sql(f"""
        with exec as (
            select distinct idProposicao id from read_csv('{RAW_CAMARA}/proposicoesAutores-*.csv', {csv})
            where tipoAutor = 'Órgão do Poder Executivo'
        ), temas as (
            select cast(regexp_extract(uriProposicao, '(\\d+)$') as varchar) id, list(distinct tema order by tema) temas
            from read_csv('{RAW_CAMARA}/proposicoesTemas-*.csv', {csv}) group by 1
        ), p as (
            select id, siglaTipo tipo, siglaTipo || ' ' || numero || '/' || ano sigla,
                   cast(substr(dataApresentacao, 1, 10) as date) as data,
                   case when regexp_matches(lower(ementa), '{vago}') and coalesce(ementaDetalhada, '') <> ''
                        then ementaDetalhada else ementa end texto,
                   coalesce(ultimoStatus_descricaoSituacao, '') s
            from read_csv('{RAW_CAMARA}/proposicoes-*.csv', {csv})
            where siglaTipo in ('PL', 'PLP', 'PEC') and id in (select id from exec)
        )
        select cast(p.id as bigint) id, tipo, sigla, data, texto, s situacao,
               case {casos} else 'parada' end estagio, coalesce(t.temas, []) temas,
               '{LINK_CAMARA}' || p.id link
        from p left join temas t using (id)
        where data >= '{INICIO}'
    """).fetchdf()


def apoio() -> pd.DataFrame:
    """Votações em que o governo orientou Sim ou Não. Vitória: o resultado foi o que o governo queria."""
    partes = []
    for casa, pasta in [("Câmara", "camara"), ("Senado", "senado")]:
        arq = RAIZ / "data" / "gold" / pasta / "votacoes.parquet"
        if not arq.exists():
            continue
        v = pd.read_parquet(arq)
        v = v[v["orientacao_governo"].isin(["Sim", "Não"])].copy()
        v["casa"] = casa
        v["vitoria"] = (v["orientacao_governo"] == "Sim") == v["aprovada"]
        partes.append(v[["casa", "votacao_id", "data", "sigla", "ementa", "autor", "descricao", "orientacao_governo",
                         "aprovada", "vitoria", "texto_principal", "temas", "link"]])
    return pd.concat(partes, ignore_index=True)


def main() -> None:
    GOLD.mkdir(parents=True, exist_ok=True)
    m, v, p, a = mpvs(), vetos(), projetos_executivo(), apoio()
    m.to_parquet(GOLD / "mpv.parquet", index=False)
    v.to_parquet(GOLD / "vetos.parquet", index=False)
    p.to_parquet(GOLD / "projetos.parquet", index=False)
    a.to_parquet(GOLD / "apoio.parquet", index=False)
    datas = [d for d in (m["data"].max(), v["data"].max(), a["data"].max()) if pd.notna(d)]
    (GOLD / "meta.json").write_text(json.dumps({"atualizado_em": str(max(datas))}, indent=1), encoding="utf-8")
    print(f"{len(m)} MPs, {len(v)} vetos, {len(p)} projetos do Executivo, {len(a)} votações com orientação do governo")
    print(m.groupby(["tipo", "resultado"]).size().to_string())
    print(v["resultado"].value_counts().to_string())
    print(p["estagio"].value_counts().to_string())
    print(a.groupby(["casa", "texto_principal"])["vitoria"].agg(["mean", "count"]).round(2).to_string())


if __name__ == "__main__":
    main()
