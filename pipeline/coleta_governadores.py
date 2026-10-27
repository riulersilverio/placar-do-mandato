"""Coleta dados oficiais do TSE sobre os governadores eleitos em 2026 para data/raw/tse.

- consulta_cand_2026: candidatos e situação (eleito, 2º turno). É baixado de novo a cada execução, porque o TSE
  atualiza o resultado do 2º turno depois da eleição.
- proposta_governo_2026_{UF}: planos de governo. Só os PDFs dos eleitos e finalistas são guardados.

Uso: python pipeline/coleta_governadores.py
"""
import csv
import zipfile
from pathlib import Path

from coleta_camara import baixar as baixar_retomando

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "tse"
CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"
CANDIDATOS = RAW / "consulta_cand_2026"
PLANOS = RAW / "planos_governadores_2026"
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
       "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]


def baixar(url: str, forcar: bool = False) -> Path:
    """Baixa para um .zip temporário (retomando se a conexão cair) e devolve o caminho."""
    (RAW / "zips").mkdir(parents=True, exist_ok=True)
    destino = RAW / "zips" / url.rsplit("/", 1)[1]
    baixar_retomando(url, destino, forcar)
    return destino


def candidatos() -> list[dict]:
    CANDIDATOS.mkdir(parents=True, exist_ok=True)
    arq = baixar(f"{CDN}/consulta_cand/consulta_cand_2026.zip", forcar=True)
    with zipfile.ZipFile(arq) as z:
        z.extract("consulta_cand_2026_BRASIL.csv", CANDIDATOS)
    arq.unlink()
    with open(CANDIDATOS / "consulta_cand_2026_BRASIL.csv", encoding="latin-1", newline="") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    print(f"  ok candidatos 2026 (gerado em {linhas[0]['DT_GERACAO']} {linhas[0]['HH_GERACAO']})", flush=True)
    return linhas


def planos(linhas: list[dict]) -> None:
    """Guarda o plano de governo de quem foi eleito ou foi ao 2º turno para governador."""
    PLANOS.mkdir(parents=True, exist_ok=True)
    alvos = {}
    for c in linhas:
        if c["DS_CARGO"] == "GOVERNADOR" and c["DS_SIT_TOT_TURNO"] in ("ELEITO", "2º TURNO"):
            alvos.setdefault(c["SG_UF"], set()).add(c["SQ_CANDIDATO"])
    for uf in UFS:
        faltam = {sq for sq in alvos.get(uf, set()) if not any(PLANOS.glob(f"2026{uf}{sq}_*.pdf"))}
        if not faltam:
            continue
        arq = baixar(f"{CDN}/proposta_governo/proposta_governo_2026_{uf}.zip")
        with zipfile.ZipFile(arq) as z:
            for sq in faltam:
                # O plano pode vir em mais de um arquivo: 2026{UF}{SQ}_01.pdf, _02.pdf...
                partes = [n for n in z.namelist() if Path(n).name.startswith(f"2026{uf}{sq}_")]
                for n in partes:
                    (PLANOS / Path(n).name).write_bytes(z.read(n))
                if not partes:
                    print(f"  aviso: plano de governo não encontrado para {uf} {sq}", flush=True)
        # O zip traz o plano de todos os candidatos do estado; só os eleitos e finalistas são guardados
        arq.unlink()
        print(f"  ok planos {uf} ({len(faltam)})", flush=True)


def main() -> None:
    planos(candidatos())


if __name__ == "__main__":
    main()
