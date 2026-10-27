"""Coleta os arquivos em lote da Câmara dos Deputados (dados abertos).

Baixa proposições, autores, votações e votos da legislatura atual (57ª, 2023-2027)
para data/raw/camara. Retoma downloads interrompidos e confere o tamanho final.

Uso: python pipeline/coleta_camara.py [--anos 2023 2024 2025 2026] [--forcar]
"""
import argparse
import time
from pathlib import Path

import requests

BASE = "https://dadosabertos.camara.leg.br/arquivos"
ARQUIVOS = {
    "proposicoes": "proposicoes/csv/proposicoes-{ano}.csv",
    "proposicoesAutores": "proposicoesAutores/csv/proposicoesAutores-{ano}.csv",
    "votacoes": "votacoes/csv/votacoes-{ano}.csv",
    "votacoesVotos": "votacoesVotos/csv/votacoesVotos-{ano}.csv",
    "votacoesProposicoes": "votacoesProposicoes/csv/votacoesProposicoes-{ano}.csv",
    "votacoesOrientacoes": "votacoesOrientacoes/csv/votacoesOrientacoes-{ano}.csv",
}
# Temas oficiais da Câmara. Vão desde 1988 porque muitos projetos votados hoje são antigos.
TEMAS = "proposicoesTemas/csv/proposicoesTemas-{ano}.csv"
ANO_INICIAL_TEMAS = 1988
API_DEPUTADOS = "https://dadosabertos.camara.leg.br/api/v2/deputados"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "camara"


def baixar(url: str, destino: Path, forcar: bool = False, tentativas: int = 40) -> None:
    total = int(requests.head(url, allow_redirects=True, timeout=60).headers.get("content-length", 0))
    if destino.exists() and not forcar and total and destino.stat().st_size == total:
        print(f"  ok (já baixado) {destino.name}")
        return
    if forcar and destino.exists():
        destino.unlink()
    for tentativa in range(1, tentativas + 1):
        feito = destino.stat().st_size if destino.exists() else 0
        if total and feito >= total:
            break
        headers = {"Range": f"bytes={feito}-"} if feito else {}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=120) as r:
                r.raise_for_status()
                modo = "ab" if feito and r.status_code == 206 else "wb"
                with open(destino, modo) as f:
                    for bloco in r.iter_content(1 << 20):
                        f.write(bloco)
        except requests.RequestException as e:
            # O servidor da Câmara derruba conexões longas com frequência; o Range retoma do ponto onde parou
            print(f"  tentativa {tentativa} interrompida; retomando de {destino.stat().st_size / 1e6:.1f} MB")
            time.sleep(min(2 * tentativa, 15))
    tamanho = destino.stat().st_size
    if total and tamanho != total:
        raise RuntimeError(f"{destino.name}: {tamanho} de {total} bytes")
    print(f"  ok {destino.name} ({tamanho / 1e6:.1f} MB)")


def get_api(url: str, params: dict | None = None, tentativas: int = 8) -> dict:
    for tentativa in range(1, tentativas + 1):
        try:
            r = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if tentativa == tentativas:
                raise
            time.sleep(2 * tentativa)


def baixar_deputados() -> None:
    """Deputados da 57ª legislatura (um registro por pessoa) e o histórico de licenças/afastamentos."""
    import json
    from concurrent.futures import ThreadPoolExecutor

    # A consulta por legislatura repete o deputado a cada troca de partido; fica o último registro
    dados, pagina = {}, 1
    while lote := get_api(API_DEPUTADOS, {"idLegislatura": 57, "itens": 100, "pagina": pagina,
                                          "ordem": "ASC", "ordenarPor": "nome"})["dados"]:
        dados.update({d["id"]: d for d in lote})
        pagina += 1
    # Sem filtro de legislatura, a API devolve só quem está em exercício hoje, com partido atual
    atuais = {d["id"]: d for d in get_api(API_DEPUTADOS, {"itens": 1000})["dados"]}
    for id_, d in dados.items():
        d.update(atuais.get(id_, {}))
        d["emExercicio"] = id_ in atuais
    (RAW / "deputados.json").write_text(json.dumps(list(dados.values()), ensure_ascii=False), encoding="utf-8")
    print(f"  ok deputados.json ({len(dados)} deputados, {len(atuais)} em exercício)")

    def historico(id_: int) -> list:
        hist = get_api(f"{API_DEPUTADOS}/{id_}/historico")["dados"]
        return [{"id": id_, "dataHora": h["dataHora"], "situacao": h["situacao"],
                 "descricaoStatus": h["descricaoStatus"]}
                for h in hist if h["idLegislatura"] == 57 and h["situacao"]]

    with ThreadPoolExecutor(6) as pool:
        hist = [h for lista in pool.map(historico, dados) for h in lista]
    (RAW / "historico.json").write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    print(f"  ok historico.json ({len(hist)} eventos)")


def baixar_autores_votados() -> None:
    """Autores dos projetos votados no plenário. Muitos são de antes de 2023 e não estão nos arquivos em lote."""
    import json
    from concurrent.futures import ThreadPoolExecutor

    import duckdb

    # Só projetos votados no plenário: o arquivo de ligações inclui as comissões (10 mil projetos)
    csv = "delim=';', all_varchar=true, quote='\"', escape='\"', union_by_name=true"
    r = RAW.as_posix()
    ids = {i for (i,) in duckdb.sql(f"""
        select distinct p.proposicao_id
        from read_csv('{r}/votacoesProposicoes-*.csv', {csv}) p
        join read_csv('{r}/votacoes-*.csv', {csv}) v on v.id = p.idVotacao
        where v.siglaOrgao = 'PLEN' and p.proposicao_siglaTipo in ('PEC', 'PLP', 'MPV', 'PLV', 'PL', 'PDL')
          and v.id in (select idVotacao from read_csv('{r}/votacoesVotos-*.csv', {csv}))
    """).fetchall()}
    destino = RAW / "autores_votados.json"
    cache = json.loads(destino.read_text(encoding="utf-8")) if destino.exists() else {}
    pendentes = sorted(ids - set(cache))
    print(f"  autores: {len(pendentes)} projetos a consultar", flush=True)

    def autores(id_: str) -> tuple[str, list]:
        dados = get_api(f"https://dadosabertos.camara.leg.br/api/v2/proposicoes/{id_}/autores")["dados"]
        return id_, [{"nome": a["nome"], "tipo": a["tipo"], "ordem": a["ordemAssinatura"],
                      "proponente": a["proponente"], "uri": a.get("uri")} for a in dados]

    with ThreadPoolExecutor(8) as pool:
        for n, (id_, lista) in enumerate(pool.map(autores, pendentes), 1):
            cache[id_] = lista
            if n % 100 == 0:
                destino.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                print(f"  {n}/{len(pendentes)}", flush=True)
    destino.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print(f"  ok autores_votados.json ({len(cache)} projetos, {len(pendentes)} novos)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", nargs="+", type=int, default=[2023, 2024, 2025, 2026])
    ap.add_argument("--forcar", action="store_true", help="baixa de novo mesmo se já existir")
    ap.add_argument("--so-deputados", action="store_true", help="atualiza só deputados e histórico")
    ap.add_argument("--tipos", nargs="+", choices=list(ARQUIVOS) + ["temas"], default=list(ARQUIVOS) + ["temas"],
                    help="quais arquivos baixar (padrão: todos)")
    ap.add_argument("--sem-deputados", action="store_true", help="pula a atualização de deputados")
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    if not args.sem_deputados:
        baixar_deputados()
    if args.so_deputados:
        return
    if "temas" in args.tipos:
        print("Temas", flush=True)
        # Anos anteriores não mudam; só o atual é baixado de novo com --forcar
        for ano in range(ANO_INICIAL_TEMAS, max(args.anos) + 1):
            baixar(f"{BASE}/{TEMAS.format(ano=ano)}", RAW / f"proposicoesTemas-{ano}.csv",
                   args.forcar and ano in args.anos)
    for ano in args.anos:
        print(f"Ano {ano}", flush=True)
        for nome in [t for t in args.tipos if t in ARQUIVOS]:
            caminho = ARQUIVOS[nome]
            baixar(f"{BASE}/{caminho.format(ano=ano)}", RAW / f"{nome}-{ano}.csv", args.forcar)
    if "votacoesProposicoes" in args.tipos:
        baixar_autores_votados()


if __name__ == "__main__":
    main()
