"""Monta a lista dos governadores eleitos em 2026 para o app.

Entrada: data/raw/tse (coleta_governadores.py)
Saída em data/gold/governadores:
    meta.json
    governadores.parquet   um registro por candidato eleito ou finalista do 2º turno
    planos/                texto extraído de cada plano de governo (para a curadoria das promessas)
"""
import csv
import json
from pathlib import Path

import pandas as pd
import pymupdf

RAIZ = Path(__file__).resolve().parent.parent
RAW = RAIZ / "data" / "raw" / "tse"
GOLD = RAIZ / "data" / "gold" / "governadores"


def texto_plano(pdfs: list[Path], destino: Path) -> int:
    """Extrai o texto dos PDFs do plano (uma vez) e devolve o número total de páginas."""
    partes = []
    for pdf in pdfs:
        with pymupdf.open(pdf) as doc:
            for pagina in doc:
                try:
                    texto = pagina.get_text()
                except RuntimeError:
                    # Página só com imagem ou corrompida: segue com as demais
                    texto = ""
                partes.append(f"=== PÁGINA {len(partes) + 1} ===\n{texto}")
    if not destino.exists():
        destino.write_text("\n".join(partes), encoding="utf-8")
    return len(partes)


def main() -> None:
    (GOLD / "planos").mkdir(parents=True, exist_ok=True)
    with open(RAW / "consulta_cand_2026" / "consulta_cand_2026_BRASIL.csv", encoding="latin-1", newline="") as f:
        cand = list(csv.DictReader(f, delimiter=";"))
    geracao = f"{cand[0]['DT_GERACAO']} {cand[0]['HH_GERACAO']}"
    gov = [c for c in cand if c["DS_CARGO"] == "GOVERNADOR"]
    # Vice da mesma chapa: mesma coligação no mesmo estado
    vices = {(c["SG_UF"], c["SQ_COLIGACAO"]): c["NM_URNA_CANDIDATO"] for c in cand if c["DS_CARGO"] == "VICE-GOVERNADOR"}
    eleitos_2t = {(c["SG_UF"], c["NR_CANDIDATO"]) for c in gov if c["NR_TURNO"] == "2" and c["DS_SIT_TOT_TURNO"] == "ELEITO"}
    nao_eleitos_2t = {(c["SG_UF"], c["NR_CANDIDATO"]) for c in gov
                      if c["NR_TURNO"] == "2" and c["DS_SIT_TOT_TURNO"] == "NÃO ELEITO"}

    linhas = []
    for c in gov:
        if c["NR_TURNO"] != "1" or c["DS_SIT_TOT_TURNO"] not in ("ELEITO", "2º TURNO"):
            continue
        chave = (c["SG_UF"], c["NR_CANDIDATO"])
        if c["DS_SIT_TOT_TURNO"] == "ELEITO":
            situacao = "Eleito no 1º turno"
        elif chave in eleitos_2t:
            situacao = "Eleito no 2º turno"
        elif chave in nao_eleitos_2t:
            continue
        else:
            situacao = "Aguardando resultado oficial do 2º turno"
        pdfs = sorted((RAW / "planos_governadores_2026").glob(f"2026{c['SG_UF']}{c['SQ_CANDIDATO']}_*.pdf"))
        paginas = texto_plano(pdfs, GOLD / "planos" / f"{c['SG_UF']}-{c['SQ_CANDIDATO']}.txt") if pdfs else 0
        linhas.append({
            "uf": c["SG_UF"], "sq": c["SQ_CANDIDATO"], "numero": c["NR_CANDIDATO"],
            "nome": c["NM_URNA_CANDIDATO"].title(), "nome_completo": c["NM_CANDIDATO"].title(),
            "partido": c["SG_PARTIDO"], "coligacao": c["NM_COLIGACAO"] if c["NM_COLIGACAO"] != "PARTIDO ISOLADO" else "",
            "composicao": c["DS_COMPOSICAO_COLIGACAO"], "vice": vices.get((c["SG_UF"], c["SQ_COLIGACAO"]), "").title(),
            "situacao": situacao, "eleito": situacao.startswith("Eleito"),
            # Para download no app vale o primeiro arquivo; os demais (raros) são anexos do mesmo plano
            "plano_pdf": str(pdfs[0].relative_to(RAIZ)).replace("\\", "/") if pdfs else "",
            "plano_paginas": paginas,
        })
    df = pd.DataFrame(linhas).sort_values(["uf", "eleito"], ascending=[True, False])
    df.to_parquet(GOLD / "governadores.parquet", index=False)
    (GOLD / "meta.json").write_text(json.dumps({"tse_gerado_em": geracao, "posse": "2027-01-06"}, ensure_ascii=False),
                                    encoding="utf-8")
    print(f"{df['eleito'].sum()} eleitos, {(~df['eleito']).sum()} finalistas aguardando resultado; TSE gerado em {geracao}")
    print(df.groupby("partido")["eleito"].sum().sort_values(ascending=False).to_string())


if __name__ == "__main__":
    main()
