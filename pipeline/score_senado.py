"""Transforma os dados brutos do Senado em métricas, score, votações e temas para o app.

Entrada: data/raw/senado (gerado por coleta_senado.py)
Saída em data/gold/senado, no mesmo formato da Câmara:
    meta.json, parlamentares.parquet, projetos.parquet, votacoes.parquet, votos.parquet

Metodologia completa em METODOLOGIA.md. Pesos e pontos são os mesmos da Câmara.
"""
import json
import re
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from score_camara import PESOS, PESO_COAUTOR, PESO_HONORARIA, PONTOS_ESTAGIO, RE_HONORARIA

RAIZ = Path(__file__).resolve().parent.parent
RAW = RAIZ / "data" / "raw" / "senado"
GOLD = RAIZ / "data" / "gold" / "senado"
LINK = "https://www25.senado.leg.br/web/atividade/materias/-/materia/"
FOTO = "https://www.senado.leg.br/senadores/img/fotos-oficiais/senador{}.jpg"

SIGLAS_PROJETO = ("PL", "PLP", "PEC", "PDL")
# O Senado tem menos votações nominais que a Câmara (boa parte é simbólica)
MIN_VOTACOES = 30
INICIO = date(2023, 2, 1)

# Situação atual do projeto → estágio. A ordem importa: a primeira regra que casar vale.
ESTAGIOS = [
    ("lei", r"NORMA JUR[IÍ]DICA|SANÇÃO|PROMULGA"),
    ("encerrada", r"ARQUIVAD|RETIRAD|PREJUDICAD|REJEITAD|VETAD[AO] TOTAL|DECLARADA? EXTINT"),
    ("aprovada_casa", r"REMETIDA À CÂMARA|ENVIADA À CÂMARA|APROVAD"),
    ("avancou", r"PRONT[OA]|PAUTA|RELATORIA|AUDIÊNCIA|AGUARDANDO (VOTAÇÃO|LEITURA DE PARECER)|EM APRECIAÇÃO"),
]
# Códigos de voto do Senado agrupados no vocabulário do app
PRESENTE = {"Sim", "Não", "Abstenção", "Votou", "P-NRV", "Presidente (art. 51 RISF)", "NA", "Obstrução"}
JUSTIFICADA = {"AP", "MIS"}
LICENCA_PREFIXO = "L"  # LS (saúde), LP (particular) e outras licenças: saem da conta de presença
VOTO_APP = {"P-NRV": "Presente, não votou", "Presidente (art. 51 RISF)": "Presidente", "NA": "Presente, não votou",
            "NCom": "Ausente", "AP": "Ausência justificada", "MIS": "Ausência justificada"}
# Votação sobre o texto do projeto em si (e não destaque ou emenda avulsa)
RE_TEXTO_PRINCIPAL = re.compile(
    r"^vota[cç][aã]o( nominal)? d[oa]s? (projeto|proposta de emenda|pec|plv|pl |plp|substitutivo"
    r"|emenda (n[ºo°.]* ?)?\d+ \(substitutivo\))", re.I)


def ler(nome: str):
    return json.loads((RAW / nome).read_text(encoding="utf-8"))


def estagio(situacao: str | None, norma: dict | None) -> str:
    if norma:
        return "lei"
    s = (situacao or "").upper()
    for nome, rx in ESTAGIOS:
        if re.search(rx, s):
            return nome
    return "parada"


def temas(classificacoes: list | None) -> list[str]:
    """Usa o 2º nível da hierarquia oficial (ex.: "Política Social / Educação / ..." → "Educação")."""
    saida = []
    for c in classificacoes or []:
        partes = [p.strip() for p in (c.get("descricaoHierarquia") or c.get("descricao") or "").split("/")]
        tema = partes[1] if len(partes) > 1 else partes[0]
        if tema and tema not in saida:
            saida.append(tema)
    return sorted(saida)


def senadores() -> tuple[pd.DataFrame, pd.DataFrame]:
    atuais = {p["IdentificacaoParlamentar"]["CodigoParlamentar"]: p["IdentificacaoParlamentar"]
              for p in ler("senadores_atuais.json")}
    leg = {p["IdentificacaoParlamentar"]["CodigoParlamentar"]: p["IdentificacaoParlamentar"]
           for p in ler("senadores_legislatura.json")}
    linhas, exercicios = [], []
    for m in ler("mandatos.json"):
        cod = m["codigo"]
        ident = atuais.get(cod) or leg.get(cod) or {}
        mandatos = m["dados"]["MandatoParlamentar"]["Parlamentar"].get("Mandatos", {}).get("Mandato", [])
        uf = None
        for mand in mandatos if isinstance(mandatos, list) else [mandatos]:
            legs = {mand.get(k, {}).get("NumeroLegislatura") for k in ("PrimeiraLegislaturaDoMandato",
                                                                       "SegundaLegislaturaDoMandato")}
            if "57" not in legs:
                continue
            uf = mand.get("UfParlamentar") or uf
            ex = mand.get("Exercicios", {}).get("Exercicio", [])
            for e in ex if isinstance(ex, list) else [ex]:
                fim = e.get("DataFim")
                if fim and date.fromisoformat(fim[:10]) < INICIO:
                    continue
                exercicios.append({"parl_id": int(cod), "ini": max(date.fromisoformat(e["DataInicio"][:10]), INICIO),
                                   "fim": date.fromisoformat(fim[:10]) if fim else date.today()})
        linhas.append({"id": int(cod), "nome": ident.get("NomeParlamentar") or m["dados"]["MandatoParlamentar"]["Parlamentar"]["Nome"],
                       "partido": ident.get("SiglaPartidoParlamentar"), "uf": ident.get("UfParlamentar") or uf,
                       "foto": FOTO.format(cod), "em_exercicio": cod in atuais})
    exercicios = pd.DataFrame(exercicios)
    # A lista da legislatura inclui suplentes que nunca assumiram
    sen = pd.DataFrame(linhas)
    sen = sen[sen["em_exercicio"] | sen["id"].isin(exercicios["parl_id"])]
    return sen.reset_index(drop=True), exercicios


def votacoes() -> tuple[pd.DataFrame, pd.DataFrame]:
    vs, ors = [], {}
    for arq in sorted((RAW / "votacoes").glob("*.json")):
        x = json.loads(arq.read_text(encoding="utf-8"))
        vs += x["votacoes"]
        for o in x["orientacoes"]:
            gov = [l["voto"] for l in o["orientacoesLideranca"] if l["partido"] == "Governo"]
            if gov:
                ors[str(o["sequencialVotacao"])] = {"SIM": "Sim", "NÃO": "Não", "LIVRE": "Liberado"}.get(gov[0], gov[0])
    linhas, votos = [], []
    for v in vs:
        vid = f"{v['codigoSessaoVotacao']}-{v['sequencialVotacao']}"
        linhas.append({
            "votacao_id": vid, "data": date.fromisoformat(v["dataSessao"][:10]), "descricao": v["descricaoVotacao"],
            "aprovada": v.get("resultadoVotacao") == "A", "sim": int(v.get("totalVotosSim") or 0),
            "nao": int(v.get("totalVotosNao") or 0), "prop_id": int(v["idProcesso"]) if v.get("idProcesso") else None,
            "codigo_materia": v.get("codigoMateria"), "sigla": v.get("identificacao"), "tipo": v.get("sigla"),
            "ementa": re.sub(r"\s+", " ", v.get("ementa") or ""), "secreta": v.get("votacaoSecreta") == "S",
            "orientacao_governo": ors.get(str(v["sequencialVotacao"]), ""),
        })
        for t in v["votos"]:
            votos.append({"votacao_id": vid, "parl_id": int(t["codigoParlamentar"]), "codigo": t["siglaVotoParlamentar"],
                          "partido": t.get("siglaPartidoParlamentar")})
    return pd.DataFrame(linhas), pd.DataFrame(votos)


def projetos(senadores_ids: set[int]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    det = ler("detalhes.json")
    lista = {}
    for sigla in SIGLAS_PROJETO:
        for arq in (RAW / "processos").glob(f"{sigla}-*.json"):
            for p in json.loads(arq.read_text(encoding="utf-8")):
                lista[str(p["id"])] = p
    autorias, projs = [], []
    for id_, p in lista.items():
        d = det.get(id_)
        if not d or p.get("casaIdentificadora") != "SF" or p.get("objetivo") != "Iniciadora":
            continue
        ts = temas(d.get("classificacoes"))
        ementa = p.get("ementa") or ""
        hom = bool(re.search(RE_HONORARIA, ementa.lower())) or any(
            re.search(r"homenage|comemorativ|honor[ií]f", t, re.I) for t in ts)
        projs.append({"id": int(id_), "sigla": p["identificacao"], "tipo": p["identificacao"].split()[0],
                      "data": date.fromisoformat(p["dataApresentacao"][:10]), "texto": ementa,
                      "situacao": (d.get("situacaoAtual") or "").capitalize(),
                      "estagio": estagio(d.get("situacaoAtual"), d.get("normaGerada")),
                      "homenagem": hom, "temas": ts, "link": LINK + str(p["codigoMateria"])})
        for a in d.get("autoriaIniciativa") or []:
            if a.get("siglaTipo") == "SENADOR" and a.get("codigoParlamentar") in senadores_ids:
                autorias.append({"id": int(id_), "parl_id": int(a["codigoParlamentar"]), "principal": a.get("ordem") == 1})
    por_processo = {int(k): {"temas": temas(v.get("classificacoes")), "autor": autor_texto(v.get("autoriaIniciativa"))}
                    for k, v in det.items()}
    return pd.DataFrame(projs), pd.DataFrame(autorias).drop_duplicates(["id", "parl_id"]), por_processo


def autor_texto(autoria: list | None) -> str:
    """"Sen. Nome (PARTIDO-UF)", "Dep. Nome (PARTIDO-UF)", "Presidência da República" etc."""
    autoria = sorted(autoria or [], key=lambda a: a.get("ordem") or 99)
    if not autoria:
        return ""
    a = autoria[0]
    prefixo = {"SENADOR": "Sen. ", "DEPUTADO": "Dep. "}.get(a.get("siglaTipo"), "")
    nome = a.get("autor") or a.get("ente") or ""
    if prefixo and a.get("siglaPartido"):
        nome += f" ({a['siglaPartido']}-{a.get('uf', '')})"
    if a.get("siglaTipo") == "PRESIDENTE_REPUBLICA":
        nome = "Presidência da República"
    outros = len(autoria) - 1
    return prefixo + nome + (f" e mais {outros}" if outros else "")


def fiscalizacao(nomes: dict[str, int]) -> pd.DataFrame:
    """Requerimentos de informação: autor = primeiro nome na autoria."""
    linhas = []
    for arq in (RAW / "processos").glob("RQS-*.json"):
        for p in json.loads(arq.read_text(encoding="utf-8")):
            if "informa" not in (p.get("tipoConteudo") or "").lower():
                continue
            m = re.match(r"Senador[a]? (.+?) \(", p.get("autoria") or "")
            if m and m.group(1) in nomes:
                linhas.append({"parl_id": nomes[m.group(1)], "id": p["id"]})
    return pd.DataFrame(linhas, columns=["parl_id", "id"])


def main() -> None:
    GOLD.mkdir(parents=True, exist_ok=True)
    sen, exerc = senadores()
    vot, votos = votacoes()
    projs, autoria, por_processo = projetos(set(sen["id"]))
    fisc = fiscalizacao(dict(zip(sen["nome"], sen["id"])))
    vazio = {"temas": [], "autor": ""}
    vot["temas"] = vot["prop_id"].map(lambda i: por_processo.get(i, vazio)["temas"] if pd.notna(i) else [])
    vot["autor"] = vot["prop_id"].map(lambda i: por_processo.get(i, vazio)["autor"] if pd.notna(i) else "")
    vot["texto_principal"] = vot["descricao"].map(lambda s: bool(RE_TEXTO_PRINCIPAL.match(s or ""))
                                                  and "destacad" not in (s or "").lower())
    vot["link"] = LINK + vot["codigo_materia"].astype(str)
    # Senador que saiu antes de hoje não aparece na lista atual: usa o último partido registrado nos votos
    ultimo_partido = votos.merge(vot[["votacao_id", "data"]]).sort_values("data").groupby("parl_id")["partido"].last()
    sen["partido"] = sen["partido"].fillna(sen["id"].map(ultimo_partido))

    con = duckdb.connect()
    for nome, df in [("sen", sen), ("exerc", exerc), ("vot", vot), ("voto", votos), ("proj", projs),
                     ("autoria", autoria), ("fisc", fisc)]:
        con.register(nome, df)

    # Votações durante o exercício de cada senador; licenças saem da conta
    con.execute(f"""
        create table periodo as
        select distinct e.parl_id, v.votacao_id, v.data, v.secreta,
               coalesce(vt.codigo, 'Ausente') codigo, coalesce(vt.partido, s.partido) partido
        from exerc e join vot v on v.data between e.ini and e.fim
        join sen s on s.id = e.parl_id
        left join voto vt on vt.votacao_id = v.votacao_id and vt.parl_id = e.parl_id
    """)
    presente = tuple(PRESENTE)
    con.execute(f"""
        create table m_pres as
        select parl_id,
               count(*) filter (where not starts_with(codigo, '{LICENCA_PREFIXO}')) votacoes_periodo,
               count(*) filter (where codigo in {presente}) votou,
               count(*) filter (where codigo in {tuple(JUSTIFICADA)}) ausencias_justificadas,
               count(*) filter (where codigo = 'Presidente (art. 51 RISF)') presidiu
        from periodo group by 1
    """)
    con.execute("""
        create table m_alinh as
        with abertos as (
            select p.*, v.orientacao_governo from periodo p join vot v using (votacao_id)
            where not p.secreta and p.codigo in ('Sim', 'Não', 'Abstenção')
        ), maioria as (
            select votacao_id, partido,
                   case when count(*) filter (where codigo = 'Sim') > count(*) filter (where codigo = 'Não') then 'Sim'
                        when count(*) filter (where codigo = 'Não') > count(*) filter (where codigo = 'Sim') then 'Não'
                   end orientacao
            from abertos group by 1, 2
        )
        select a.parl_id,
               count(*) filter (where a.orientacao_governo in ('Sim', 'Não')) n_governo,
               count(*) filter (where a.codigo = a.orientacao_governo) com_governo,
               count(m.orientacao) n_partido,
               count(*) filter (where a.codigo = m.orientacao) com_partido
        from abertos a left join maioria m on m.votacao_id = a.votacao_id and m.partido = a.partido
        group by 1
    """)
    pontos = " ".join(f"when '{k}' then {v}" for k, v in PONTOS_ESTAGIO.items())
    con.execute(f"""
        create table m_proj as
        select au.parl_id,
               sum((case p.estagio {pontos} end)
                   * (case when au.principal then 1 else {PESO_COAUTOR} end)
                   * (case when p.homenagem then {PESO_HONORARIA} else 1 end)) pts_resultado,
               count(*) filter (where au.principal and not p.homenagem) projetos_autor,
               count(*) filter (where not au.principal and not p.homenagem) projetos_coautor,
               count(*) filter (where au.principal and p.homenagem) homenagens,
               count(*) filter (where au.principal and p.estagio = 'lei') viraram_lei,
               count(*) filter (where au.principal and p.estagio = 'aprovada_casa') aprovadas_casa,
               count(*) filter (where au.principal and p.estagio = 'avancou') avancaram
        from autoria au join proj p using (id)
        group by 1
    """)
    parl = con.execute(f"""
        with m as (
            select s.*,
                   coalesce(pr.pts_resultado, 0) pts_resultado, coalesce(pr.projetos_autor, 0) projetos_autor,
                   coalesce(pr.projetos_coautor, 0) projetos_coautor, coalesce(pr.homenagens, 0) homenagens,
                   coalesce(pr.viraram_lei, 0) viraram_lei, coalesce(pr.aprovadas_casa, 0) aprovadas_casa,
                   coalesce(pr.avancaram, 0) avancaram,
                   (select count(*) from fisc f where f.parl_id = s.id) pedidos_fiscalizacao,
                   coalesce(ps.votou, 0) votou, coalesce(ps.votacoes_periodo, 0) votacoes_periodo,
                   coalesce(ps.presidiu, 0) presidiu, coalesce(ps.ausencias_justificadas, 0) ausencias_justificadas,
                   coalesce(ps.votou / nullif(ps.votacoes_periodo, 0), 0) presenca,
                   al.com_governo / nullif(al.n_governo, 0) alinh_governo, coalesce(al.n_governo, 0) n_governo,
                   al.com_partido / nullif(al.n_partido, 0) alinh_partido, coalesce(al.n_partido, 0) n_partido
            from sen s
            left join m_proj pr on pr.parl_id = s.id
            left join m_pres ps on ps.parl_id = s.id
            left join m_alinh al on al.parl_id = s.id
        ), elegiveis as (
            select id,
                   round(100 * percent_rank() over (order by pts_resultado)) p_resultado,
                   round(100 * percent_rank() over (order by presenca)) p_presenca,
                   round(100 * percent_rank() over (order by projetos_autor)) p_producao,
                   round(100 * percent_rank() over (order by pedidos_fiscalizacao)) p_fiscalizacao
            from m where em_exercicio and votacoes_periodo >= {MIN_VOTACOES}
        ), notas as (
            select m.*, e.p_resultado, e.p_presenca, e.p_producao, e.p_fiscalizacao,
                   round({PESOS['resultado']} * e.p_resultado + {PESOS['presenca']} * e.p_presenca
                         + {PESOS['producao']} * e.p_producao + {PESOS['fiscalizacao']} * e.p_fiscalizacao) score
            from m left join elegiveis e using (id)
        )
        select *, case when score is not null then rank() over (order by score desc nulls last) end posicao
        from notas order by score desc nulls last, nome
    """).fetchdf()

    # Lista de votos: só votações abertas sobre projetos (nas secretas o voto individual não é divulgado)
    vot_out = vot[~vot["secreta"] & vot["tipo"].isin(["PL", "PLP", "PEC", "PDL", "MPV", "PLV", "PLS", "PLC"])].copy()
    votos_out = con.execute("select votacao_id, parl_id, codigo voto, partido from periodo where not secreta").fetchdf()
    votos_out = votos_out[votos_out["votacao_id"].isin(vot_out["votacao_id"])]
    votos_out["voto"] = votos_out["voto"].map(lambda c: "Licença" if c.startswith(LICENCA_PREFIXO) and c not in VOTO_APP
                                              else VOTO_APP.get(c, c))
    projetos_out = autoria[autoria["principal"]].merge(projs, on="id").drop(columns="principal")

    vot_out.drop(columns=["secreta", "codigo_materia"]).to_parquet(GOLD / "votacoes.parquet", index=False)
    votos_out.to_parquet(GOLD / "votos.parquet", index=False)
    projetos_out.to_parquet(GOLD / "projetos.parquet", index=False)
    parl.to_parquet(GOLD / "parlamentares.parquet", index=False)
    (GOLD / "meta.json").write_text(json.dumps({
        "atualizado_em": str(vot["data"].max()), "pesos": PESOS, "pontos_estagio": PONTOS_ESTAGIO,
        "min_votacoes": MIN_VOTACOES}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(parl)} senadores ({parl['score'].notna().sum()} no ranking), {len(projetos_out)} projetos, "
          f"{len(vot_out)} votações abertas de {len(vot)}, {len(fisc)} pedidos de informação; dados até {vot['data'].max()}")


if __name__ == "__main__":
    main()
