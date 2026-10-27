"""Coleta dados do Poder Executivo federal no Congresso para data/raw/presidencia.

Medidas provisórias e vetos vêm da API do Senado (o Congresso Nacional analisa os dois).
Os projetos enviados pelo Executivo à Câmara são lidos depois, direto dos arquivos já baixados por coleta_camara.py.

Uso: python pipeline/coleta_presidencia.py
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from coleta_senado import get

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "presidencia"
INICIO = date(2023, 1, 1)


def trimestres(hoje: date) -> list[tuple[date, date]]:
    lista = []
    for ano in range(INICIO.year, hoje.year + 1):
        for t in range(4):
            a = date(ano, 3 * t + 1, 1)
            b = date(ano + (t == 3), (3 * t + 4) % 12 or 12, 1)
            b = b.fromordinal(b.toordinal() - 1)
            if a <= hoje:
                lista.append((a, min(b, hoje)))
    return lista


def processos(sigla: str, hoje: date) -> list:
    def lote(par):
        a, b = par
        return get("processo", {"sigla": sigla, "dataInicioApresentacao": f"{a}", "dataFimApresentacao": f"{b}"})

    with ThreadPoolExecutor(4) as pool:
        dados = [p for parte in pool.map(lote, trimestres(hoje)) for p in parte]
    return list({p["id"]: p for p in dados}.values())


def detalhes(ids: list) -> dict:
    """Detalhe de cada processo: traz a decisão (veto mantido/derrubado, MP aprovada ou não) e a norma gerada."""
    def um(id_):
        d = get(f"processo/{id_}")
        return str(id_), {k: d.get(k) for k in ("id", "identificacao", "situacaoAtual", "deliberacao", "normaGerada",
                                                "classificacoes", "conteudo", "dataSituacaoAtual")}

    with ThreadPoolExecutor(8) as pool:
        return dict(pool.map(um, ids))


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    hoje = date.today()
    for sigla in ("MPV", "VET"):
        lista = processos(sigla, hoje)
        det = detalhes([p["id"] for p in lista])
        (RAW / f"{sigla}.json").write_text(json.dumps({"lista": lista, "detalhes": det}, ensure_ascii=False),
                                           encoding="utf-8")
        print(f"  ok {sigla}: {len(lista)} processos", flush=True)


if __name__ == "__main__":
    main()
