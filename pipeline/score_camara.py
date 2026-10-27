"""Transforma os dados brutos da Câmara em métricas, score, votações e temas para o app.

Entrada: data/raw/camara (gerado por coleta_camara.py)
Saída em data/gold/camara:
    meta.json           data de atualização, pesos e lista de temas
    parlamentares.parquet  métricas, score e alinhamento de cada deputado
    projetos.parquet    projetos de autoria principal, com estágio e temas oficiais
    votacoes.parquet    votações nominais do plenário sobre projetos, com orientação do governo
    votos.parquet       voto de cada deputado em cada uma dessas votações (inclui ausências)

Metodologia completa em METODOLOGIA.md.
"""
import argparse
import json
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent.parent
RAW = (RAIZ / "data" / "raw" / "camara").as_posix()
GOLD = RAIZ / "data" / "gold" / "camara"
LINK = "https://www.camara.leg.br/propostas-legislativas/"

# Projetos que podem virar lei ou mudar a Constituição
TIPOS_PROJETO = ("PL", "PLP", "PEC", "PDL")
# Instrumentos de fiscalização do Executivo
TIPOS_FISCALIZACAO = ("RIC", "PFC")
# Ao escolher o assunto de uma votação, a ordem define qual proposição ligada a ela é a principal
PRIORIDADE_VOTACAO = ["PEC", "PLP", "MPV", "PLV", "PL", "PDL"]

# Pesos do score (somam 1). Ver METODOLOGIA.md
PESOS = {"resultado": 0.35, "presenca": 0.30, "producao": 0.20, "fiscalizacao": 0.15}
PESO_COAUTOR = 0.25
PESO_HONORARIA = 0.1
PONTOS_ESTAGIO = {"lei": 10, "aprovada_casa": 5, "avancou": 2, "parada": 0.5, "encerrada": 0}
# Mínimo de votações nominais no período de mandato para entrar no ranking
MIN_VOTACOES = 50

ESTAGIOS = {
    "lei": ["Transformado em Norma Jurídica", "Aguardando Sanção", "Aguardando Apreciação do Veto",
            "Aguardando Promulgação"],
    "aprovada_casa": ["Aguardando Apreciação pelo Senado Federal", "Aguardando Envio ao Senado Federal",
                        "Aguardando Autógrafos na Mesa", "Aguardando Redação Final",
                        "Aguardando Envio à Redação Final", "Remetida ao Senado Federal"],
    "avancou": ["Pronta para Pauta", "Aguardando Deliberação", "Aguardando Deliberação de Recurso",
                "Aguardando Parecer", "Aguardando Recurso"],
    "encerrada": ["Arquivada", "Retirado pelo(a) Autor(a)", "Devolvida ao(à) Autor(a)",
                  "Vetado totalmente", "Perdeu a Eficácia", "Prejudicado"],
}

TEMA_HOMENAGEM = "Homenagens e Datas Comemorativas"
# Complementa o tema oficial, que nem sempre está preenchido em projetos recentes
RE_HONORARIA = (
    r"(denomina|inscreve o nome|livro dos her[oó]is|institui o dia|institui a semana|institui o m[eê]s"
    r"|dia nacional|semana nacional|m[eê]s nacional|declara patron|patrono|patrona"
    r"|capital nacional|t[ií]tulo de|confere ao munic[ií]pio|homenage|calend[aá]rio oficial"
    r"|data comemorativa|declara de utilidade|patrim[oô]nio cultural imaterial)"
)
# Votação sobre o texto do projeto em si (e não destaque, emenda ou requerimento de procedimento)
RE_TEXTO_PRINCIPAL = (
    r"^(aprovad|rejeitad)[oa]s?(, em (primeiro|segundo) turno,)? (o |a |os |as )?"
    r"(projeto|proposta de emenda|substitutivo|subemenda substitutiva global|medida provis"
    r"|parecer da comiss[aã]o mista|reda[cç][aã]o final|emenda aglutinativa substitutiva|emendas? do senado)"
)
# Ementas do tipo "Altera a Lei nº X" não dizem nada ao leigo; nesses casos usa a ementa detalhada
RE_EMENTA_VAGA = r"^(altera|acrescenta|d[aá] nova reda|modifica|revoga)"


def estagio_sql() -> str:
    casos = " ".join(
        f"when s in ({', '.join(repr(v) for v in valores)}) then '{nome}'" for nome, valores in ESTAGIOS.items()
    )
    return f"case {casos} else 'parada' end"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", nargs="+", type=int, default=[2023, 2024, 2025, 2026],
                    help="anos a usar; útil para rodar enquanto um ano ainda está baixando")
    anos = [a for a in ap.parse_args().anos if Path(f"{RAW}/votacoesVotos-{a}.csv").exists()]
    GOLD.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    csv = "delim=';', all_varchar=true, quote='\"', escape='\"', union_by_name=true"
    for view, nome in [("prop_raw", "proposicoes"), ("autor_raw", "proposicoesAutores"),
                       ("vot_raw", "votacoes"), ("voto_raw", "votacoesVotos"),
                       ("vprop_raw", "votacoesProposicoes"), ("orient_raw", "votacoesOrientacoes")]:
        arquivos = ", ".join(f"'{RAW}/{nome}-{a}.csv'" for a in anos if Path(f"{RAW}/{nome}-{a}.csv").exists())
        con.execute(f"create view {view} as select * from read_csv([{arquivos}], {csv})")
    con.execute(f"create table dep as select * from read_json('{RAW}/deputados.json')")
    con.execute(f"""
        create table tema as
        select distinct cast(regexp_extract(uriProposicao, '(\\d+)$') as bigint) id, tema
        from read_csv('{RAW}/proposicoesTemas-*.csv', {csv})
    """)
    # Votos ficam numa tabela física porque são lidos várias vezes
    con.execute("""
        create table voto as
        select idVotacao votacao_id, cast(deputado_id as bigint) dep_id, voto,
               deputado_siglaPartido partido
        from voto_raw
    """)

    projetos(con)
    votacoes(con)
    autores_votacoes(con)
    deps = deputados(con)

    ultima = con.execute("select max(data) from plen").fetchone()[0]
    temas = [t for (t,) in con.execute("select distinct tema from tema order by 1").fetchall()]
    (GOLD / "meta.json").write_text(json.dumps({
        "atualizado_em": str(ultima), "anos": anos, "pesos": PESOS, "pontos_estagio": PONTOS_ESTAGIO,
        "min_votacoes": MIN_VOTACOES,
        "temas": temas}, ensure_ascii=False, indent=1), encoding="utf-8")
    for tabela, arquivo in [("deputados_out", "parlamentares"), ("projetos_out", "projetos"),
                            ("votacoes_out", "votacoes"), ("votos_out", "votos")]:
        con.execute(f"copy {tabela} to '{(GOLD / arquivo).as_posix()}.parquet' (format parquet, compression zstd)")

    n = {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in ("projetos_out", "votacoes_out", "votos_out")}
    elegiveis = con.execute("select count(*) from deputados_out where score is not null").fetchone()[0]
    print(f"{deps} deputados ({elegiveis} no ranking), {n['projetos_out']} projetos, "
          f"{n['votacoes_out']} votações, {n['votos_out']} votos; anos {anos}; dados até {ultima}")


def projetos(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"""
        create table prop as
        with base as (
            select cast(id as bigint) id, siglaTipo tipo, numero, ano, ementa,
                   coalesce(nullif(ementaDetalhada, ''), '') ementa_det,
                   cast(substr(dataApresentacao, 1, 10) as date) as data,
                   coalesce(ultimoStatus_descricaoSituacao, '') s
            from prop_raw
            where siglaTipo in {TIPOS_PROJETO + TIPOS_FISCALIZACAO}
        ), temas as (
            select id, list(tema order by tema) temas from tema group by id
        )
        select b.id, b.tipo, b.numero, b.ano, b.data, b.s situacao, {estagio_sql()} estagio,
               case when regexp_matches(lower(b.ementa), '{RE_EMENTA_VAGA}') and b.ementa_det <> ''
                    then b.ementa_det else b.ementa end texto,
               coalesce(t.temas, []) temas,
               regexp_matches(lower(b.ementa), '{RE_HONORARIA}')
                   or list_contains(coalesce(t.temas, []), '{TEMA_HOMENAGEM}') honoraria
        from base b left join temas t using (id)
    """)
    con.execute("""
        create table autoria as
        select distinct cast(a.idProposicao as bigint) id, cast(a.idDeputadoAutor as bigint) dep_id,
               a.ordemAssinatura = '1' principal
        from autor_raw a
        where a.idDeputadoAutor <> '' and a.proponente = '1'
    """)
    con.execute(f"""
        create table projetos_out as
        select au.dep_id parl_id, p.id, p.tipo || ' ' || p.numero || '/' || p.ano sigla, p.tipo, p.data, p.texto,
               p.situacao, p.estagio, p.honoraria homenagem, p.temas, '{LINK}' || p.id link
        from autoria au join prop p using (id)
        where au.principal and p.tipo in {TIPOS_PROJETO}
    """)


def votacoes(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        create table plen as
        select distinct v.id, cast(v.data as date) as data, v.descricao, v.aprovacao = '1' aprovada,
               cast(v.votosSim as int) sim, cast(v.votosNao as int) nao
        from vot_raw v
        where v.siglaOrgao = 'PLEN' and v.id in (select distinct votacao_id from voto)
    """)
    # Períodos em exercício: cada evento do histórico vale até o próximo evento do mesmo deputado.
    # Licença, suplência e vacância ficam fora, para não punir quem se afastou (ex.: virou ministro).
    con.execute(f"""
        create table exercicio as
        with ev as (
            select id dep_id, situacao, cast(dataHora as timestamp) ini,
                   lead(cast(dataHora as timestamp)) over (partition by id order by dataHora) prox
            from read_json('{RAW}/historico.json')
        )
        select dep_id, cast(ini as date) ini, cast(coalesce(prox, now()) as date) fim
        from ev where situacao = 'Exercício'
    """)
    con.execute("""
        create table plen_dep as
        select distinct e.dep_id, p.id votacao_id, p.data
        from exercicio e join plen p on p.data between e.ini and e.fim
    """)
    # Assunto de cada votação: a proposição de maior prioridade ligada a ela (PEC > PLP > ... > PDL)
    ordem = " ".join(f"when '{t}' then {i}" for i, t in enumerate(PRIORIDADE_VOTACAO))
    con.execute(f"""
        create table votacoes_out as
        with ligadas as (
            select idVotacao votacao_id, cast(proposicao_id as bigint) prop_id, proposicao_siglaTipo tipo,
                   proposicao_siglaTipo || ' ' || proposicao_numero || '/' || proposicao_ano sigla,
                   proposicao_ementa ementa,
                   row_number() over (partition by idVotacao order by case proposicao_siglaTipo {ordem} end) n
            from vprop_raw
            where proposicao_siglaTipo in {tuple(PRIORIDADE_VOTACAO)}
        ), governo as (
            select idVotacao votacao_id, any_value(orientacao) orientacao_governo
            from orient_raw where siglaBancada = 'Governo' group by 1
        ), temas as (
            select id, list(tema order by tema) temas from tema group by id
        )
        select p.id votacao_id, p.data, p.descricao, p.aprovada, p.sim, p.nao,
               l.prop_id, l.sigla, l.tipo, regexp_replace(l.ementa, '\\s+', ' ', 'g') ementa,
               coalesce(t.temas, []) temas,
               regexp_matches(lower(p.descricao), '{RE_TEXTO_PRINCIPAL}') texto_principal,
               coalesce(g.orientacao_governo, '') orientacao_governo, '{LINK}' || l.prop_id link
        from plen p
        join ligadas l on l.votacao_id = p.id and l.n = 1
        left join temas t on t.id = l.prop_id
        left join governo g on g.votacao_id = p.id
    """)
    # Um registro por deputado em exercício em cada votação; quem não votou fica como "Ausente"
    con.execute("""
        create table votos_out as
        select pd.votacao_id, pd.dep_id parl_id, coalesce(v.voto, 'Ausente') voto,
               coalesce(v.partido, d.siglaPartido) partido
        from plen_dep pd
        join votacoes_out vo on vo.votacao_id = pd.votacao_id
        join dep d on d.id = pd.dep_id
        left join voto v on v.votacao_id = pd.votacao_id and v.dep_id = pd.dep_id
    """)


def autores_votacoes(con: duckdb.DuckDBPyConnection) -> None:
    """Acrescenta às votações o autor do projeto: "Nome (PARTIDO-UF)", "Poder Executivo" etc."""
    arq = Path(RAW) / "autores_votados.json"
    autores = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    deps = {d["uri"]: f"{d['nome']} ({d['siglaPartido']}-{d['siglaUf']})"
            for d in json.loads((Path(RAW) / "deputados.json").read_text(encoding="utf-8"))}

    def texto(lista: list) -> str:
        lista = sorted((a for a in lista if a["proponente"] == 1), key=lambda a: a["ordem"]) or lista
        if not lista:
            return ""
        a = lista[0]
        nome = deps.get(a.get("uri")) or a["nome"]
        if a["tipo"] == "Deputado(a)" and a.get("uri") not in deps:
            nome = f"Dep. {nome}"
        elif a["tipo"] == "Senador(a)":
            nome = f"Sen. {nome}"
        outros = len(lista) - 1
        return nome + (f" e mais {outros}" if outros else "")

    mapa = {int(k): texto(v) for k, v in autores.items()}
    con.create_function("autor_de", lambda i: mapa.get(i, ""), ["BIGINT"], "VARCHAR")
    con.execute("create or replace table votacoes_out as select *, autor_de(prop_id) autor from votacoes_out")


def deputados(con: duckdb.DuckDBPyConnection) -> int:
    pontos = " ".join(f"when '{k}' then {v}" for k, v in PONTOS_ESTAGIO.items())
    # Pontos de resultado por deputado: estágio x peso da autoria x peso da homenagem
    con.execute(f"""
        create table m_proj as
        select au.dep_id,
               sum((case p.estagio {pontos} end)
                   * (case when au.principal then 1 else {PESO_COAUTOR} end)
                   * (case when p.honoraria then {PESO_HONORARIA} else 1 end)) pts_resultado,
               count(*) filter (where au.principal and not p.honoraria) projetos_autor,
               count(*) filter (where not au.principal and not p.honoraria) projetos_coautor,
               count(*) filter (where au.principal and p.honoraria) homenagens,
               count(*) filter (where au.principal and p.estagio = 'lei') viraram_lei,
               count(*) filter (where au.principal and p.estagio = 'aprovada_casa') aprovadas_casa,
               count(*) filter (where au.principal and p.estagio = 'avancou') avancaram
        from autoria au join prop p using (id)
        where p.tipo in {TIPOS_PROJETO}
        group by 1
    """)
    con.execute(f"""
        create table m_fisc as
        select au.dep_id, count(*) pedidos_fiscalizacao
        from autoria au join prop p using (id)
        where p.tipo in {TIPOS_FISCALIZACAO} and au.principal
        group by 1
    """)
    con.execute("""
        create table m_pres as
        select pd.dep_id, count(distinct pd.votacao_id) votacoes_periodo,
               count(distinct v.votacao_id) votou,
               -- "Artigo 17" marca quem presidia a sessão: por regra não vota nem apresenta projetos
               count(distinct v.votacao_id) filter (where v.voto = 'Artigo 17') presidiu
        from plen_dep pd
        left join voto v on v.votacao_id = pd.votacao_id and v.dep_id = pd.dep_id
        group by 1
    """)
    # Alinhamento, em todas as votações nominais do plenário em que o deputado votou:
    # - governo: votou igual à orientação oficial do governo (quando ela foi Sim ou Não)
    # - partido: votou igual à maioria dos colegas de partido. A orientação oficial do partido não serve
    #   aqui porque a maioria dos partidos orienta por bloco, e o nome do bloco vem truncado nos dados.
    con.execute("""
        create table m_alinh as
        with gov as (
            select idVotacao votacao_id, any_value(orientacao) orientacao
            from orient_raw where siglaBancada = 'Governo' and orientacao in ('Sim', 'Não') group by 1
        ), maioria as (
            select votacao_id, partido,
                   case when count(*) filter (where voto = 'Sim') > count(*) filter (where voto = 'Não') then 'Sim'
                        when count(*) filter (where voto = 'Não') > count(*) filter (where voto = 'Sim') then 'Não'
                   end orientacao
            from voto group by 1, 2
        ), v as (
            select * from voto where voto in ('Sim', 'Não', 'Abstenção', 'Obstrução')
        )
        select v.dep_id,
               count(g.orientacao) n_governo,
               count(*) filter (where v.voto = g.orientacao) com_governo,
               count(m.orientacao) n_partido,
               count(*) filter (where v.voto = m.orientacao) com_partido
        from v
        left join gov g on g.votacao_id = v.votacao_id
        left join maioria m on m.votacao_id = v.votacao_id and m.partido = v.partido
        group by 1
    """)
    con.execute(f"""
        create table deputados_out as
        with m as (
            select d.id, d.nome, d.siglaPartido partido, d.siglaUf uf, d.urlFoto foto, d.emExercicio em_exercicio,
                   coalesce(pr.pts_resultado, 0) pts_resultado,
                   coalesce(pr.projetos_autor, 0) projetos_autor,
                   coalesce(pr.projetos_coautor, 0) projetos_coautor,
                   coalesce(pr.homenagens, 0) homenagens,
                   coalesce(pr.viraram_lei, 0) viraram_lei,
                   coalesce(pr.aprovadas_casa, 0) aprovadas_casa,
                   coalesce(pr.avancaram, 0) avancaram,
                   coalesce(f.pedidos_fiscalizacao, 0) pedidos_fiscalizacao,
                   coalesce(ps.votou, 0) votou, coalesce(ps.votacoes_periodo, 0) votacoes_periodo,
                   coalesce(ps.presidiu, 0) presidiu,
                   coalesce(ps.votou / nullif(ps.votacoes_periodo, 0), 0) presenca,
                   al.com_governo / nullif(al.n_governo, 0) alinh_governo, coalesce(al.n_governo, 0) n_governo,
                   al.com_partido / nullif(al.n_partido, 0) alinh_partido, coalesce(al.n_partido, 0) n_partido
            from dep d
            left join m_proj pr on pr.dep_id = d.id
            left join m_fisc f on f.dep_id = d.id
            left join m_pres ps on ps.dep_id = d.id
            left join m_alinh al on al.dep_id = d.id
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
        from notas
        order by score desc nulls last, nome
    """)
    return con.execute("select count(*) from deputados_out").fetchone()[0]


if __name__ == "__main__":
    main()
