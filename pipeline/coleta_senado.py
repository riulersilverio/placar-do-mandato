"""Coleta dados do Senado Federal (API de dados abertos) para data/raw/senado.

Baixa senadores da 57ª legislatura e seus períodos em exercício, votações nominais do plenário com o voto
de cada senador, orientações das lideranças e projetos apresentados (com autoria e classificação temática).
Meses e projetos já baixados são reaproveitados; os dois últimos meses são sempre atualizados.

Uso: python pipeline/coleta_senado.py
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import requests

API = "https://legis.senado.leg.br/dadosabertos"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "senado"
INICIO = date(2023, 2, 1)
# Projetos que podem virar lei ou mudar a Constituição, e requerimentos (para os pedidos de informação)
SIGLAS_PROJETO = ["PL", "PLP", "PEC", "PDL"]
SIGLA_REQUERIMENTO = "RQS"


def get(caminho: str, params: dict | None = None, tentativas: int = 8):
    for tentativa in range(1, tentativas + 1):
        try:
            r = requests.get(f"{API}/{caminho}", params=params, headers={"Accept": "application/json"}, timeout=120)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if tentativa == tentativas:
                raise
            time.sleep(2 * tentativa)


def salvar(nome: str, dados) -> None:
    (RAW / nome).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def ler(nome: str, padrao=None):
    arq = RAW / nome
    return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else padrao


def meses(ate: date) -> list[tuple[date, date]]:
    lista, ini = [], INICIO
    while ini <= ate:
        prox = date(ini.year + (ini.month == 12), ini.month % 12 + 1, 1)
        lista.append((ini, min(prox.fromordinal(prox.toordinal() - 1), ate)))
        ini = prox
    return lista


def senadores() -> None:
    atuais = get("senador/lista/atual.json")["ListaParlamentarEmExercicio"]["Parlamentares"]["Parlamentar"]
    leg = get("senador/lista/legislatura/57.json")["ListaParlamentarLegislatura"]["Parlamentares"]["Parlamentar"]
    codigos = sorted({p["IdentificacaoParlamentar"]["CodigoParlamentar"] for p in atuais + leg})

    def mandatos(cod: str) -> dict:
        return {"codigo": cod, "dados": get(f"senador/{cod}/mandatos.json")}

    with ThreadPoolExecutor(6) as pool:
        mand = list(pool.map(mandatos, codigos))
    salvar("senadores_atuais.json", atuais)
    salvar("senadores_legislatura.json", leg)
    salvar("mandatos.json", mand)
    print(f"  ok senadores ({len(atuais)} em exercício, {len(codigos)} na legislatura)", flush=True)


def votacoes(hoje: date) -> None:
    (RAW / "votacoes").mkdir(exist_ok=True)
    lista = meses(hoje)
    for i, (ini, fim) in enumerate(lista):
        nome = f"votacoes/{ini:%Y-%m}.json"
        if (RAW / nome).exists() and i < len(lista) - 2:
            continue
        vot = get("votacao", {"dataInicio": f"{ini}", "dataFim": f"{fim}"})
        ori = get(f"plenario/votacao/orientacaoBancada/{ini:%Y%m%d}/{fim:%Y%m%d}.json")
        salvar(nome, {"votacoes": vot, "orientacoes": ori.get("votacoes", [])})
        print(f"  ok votações {ini:%Y-%m} ({len(vot)})", flush=True)


def processos(hoje: date) -> None:
    (RAW / "processos").mkdir(exist_ok=True)
    for sigla in SIGLAS_PROJETO + [SIGLA_REQUERIMENTO]:
        for ano in range(INICIO.year, hoje.year + 1):
            nome = f"processos/{sigla}-{ano}.json"
            if (RAW / nome).exists() and ano < hoje.year - 1:
                continue
            ini = max(INICIO, date(ano, 1, 1))
            fim = min(hoje, date(ano, 12, 31))
            # Dividido em trimestres para não estourar o tempo de resposta da API
            dados = []
            for t in range(4):
                a = date(ano, 3 * t + 1, 1)
                b = date(ano + (t == 3), (3 * t + 4) % 12 or 12, 1)
                b = b.fromordinal(b.toordinal() - 1)
                if b < ini or a > fim:
                    continue
                dados += get("processo", {"sigla": sigla, "dataInicioApresentacao": f"{max(a, ini)}",
                                          "dataFimApresentacao": f"{min(b, fim)}"})
            salvar(nome, dados)
            print(f"  ok {sigla} {ano} ({len(dados)})", flush=True)


def detalhes() -> None:
    """Detalhe dos projetos apresentados no Senado: autoria com ordem e classificação temática."""
    cache = ler("detalhes.json", {})
    pendentes = []
    for sigla in SIGLAS_PROJETO:
        for arq in sorted((RAW / "processos").glob(f"{sigla}-*.json")):
            for p in json.loads(arq.read_text(encoding="utf-8")):
                if p.get("casaIdentificadora") != "SF" or p.get("objetivo") != "Iniciadora":
                    continue
                antigo = cache.get(str(p["id"]))
                if not antigo or (antigo.get("dthUltimaAtualizacao") or "") < (p.get("dataUltimaAtualizacao") or ""):
                    pendentes.append(p["id"])
    # Projetos votados no plenário (muitos vêm da Câmara): o detalhe traz a classificação temática
    for arq in (RAW / "votacoes").glob("*.json"):
        for v in json.loads(arq.read_text(encoding="utf-8"))["votacoes"]:
            if v.get("idProcesso") and str(v["idProcesso"]) not in cache:
                pendentes.append(v["idProcesso"])
    pendentes = list(dict.fromkeys(pendentes))

    def detalhe(id_):
        d = get(f"processo/{id_}")
        return str(id_), {k: d.get(k) for k in ("id", "codigoMateria", "identificacao", "sigla", "situacaoAtual",
                                                "classificacoes", "autoriaIniciativa", "normaGerada",
                                                "dthUltimaAtualizacao")}

    print(f"  detalhando {len(pendentes)} projetos...", flush=True)
    with ThreadPoolExecutor(8) as pool:
        for i, (id_, d) in enumerate(pool.map(detalhe, pendentes), 1):
            cache[id_] = d
            if i % 500 == 0:
                salvar("detalhes.json", cache)
                print(f"  {i}/{len(pendentes)}", flush=True)
    salvar("detalhes.json", cache)
    print(f"  ok detalhes ({len(cache)} projetos)", flush=True)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    hoje = date.today()
    senadores()
    votacoes(hoje)
    processos(hoje)
    detalhes()


if __name__ == "__main__":
    main()
