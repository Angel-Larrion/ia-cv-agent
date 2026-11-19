"""Compare retrieval quality for several k values, with no generation calls.

Each question is searched once with the largest k; smaller k values are the
top of the same ranking, so the comparison costs one embedding set only.
"""
import json
import time
from datetime import datetime
from pathlib import Path

import rag
from eval.casos import CASOS

KS = (2, 3, 4, 5, 6, 8, 10, 12)
CARACTERES_POR_TOKEN = 4  # rough characters-per-token estimate, as in run_eval


def main():
    casos = [c for c in CASOS if c["esperados"]]
    filas = []
    for c in casos:
        ranking = rag.buscar(c["turnos"][-1], c["turnos"][:-1], max(KS))
        filas.append((c, ranking))
        time.sleep(1)  # embeddings allow 100 per minute

    resumen = {}
    for k in KS:
        hit = rr = recall = chars = 0.0
        for c, ranking in filas:
            top = ranking[:k]
            ids = [f["id"] for f in top]
            pos = [ids.index(e) + 1 for e in c["esperados"] if e in ids]
            hit += bool(pos)
            rr += 1 / min(pos) if pos else 0.0
            recall += len(pos) / len(c["esperados"])
            chars += sum(len(f["texto"]) for f in top)
        n = len(filas)
        resumen[k] = {
            "hit": round(hit / n, 3), "mrr": round(rr / n, 3),
            "recall": round(recall / n, 3),
            "tokens_fragmentos": round(chars / n / CARACTERES_POR_TOKEN),
        }

    print(f"{len(filas)} questions with expected chunks")
    print("k    Hit@k  MRR    Recall  fragment tokens (avg)")
    for k, r in resumen.items():
        print(f"{k:<4} {r['hit']:<6} {r['mrr']:<6} {r['recall']:<7} {r['tokens_fragmentos']}")

    perdidos = {}
    for k in KS:
        falla = [c["id"] for c, ranking in filas
                 if not any(f["id"] in c["esperados"] for f in ranking[:k])]
        if falla:
            perdidos[k] = falla
    print("Questions with no expected chunk in the top k:", perdidos or "none")

    salida = Path(__file__).parent / "resultados"
    salida.mkdir(exist_ok=True)
    ruta = salida / f"{datetime.now():%Y%m%d-%H%M}-comparar-k.json"
    ruta.write_text(json.dumps({"resumen": resumen, "sin_acierto": perdidos}, indent=2), encoding="utf-8")
    print("Saved", ruta)


if __name__ == "__main__":
    main()
