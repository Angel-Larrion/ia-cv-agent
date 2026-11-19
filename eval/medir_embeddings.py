"""Time the query embeddings: one after another vs in parallel.

From the repo root:  python -m eval.medir_embeddings
Needs GEMINI_API_KEY. Spends about 30 embeddings and no generations.
"""
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import rag

TEXTOS = [
    "¿Y qué resultado tuvo?",
    "¿Qué hiciste con agentes de voz con IA en cobranza? ¿Y qué resultado tuvo?",
    "¿Qué hiciste en Propaga? ¿Qué hiciste con agentes de voz con IA en cobranza? ¿Y qué resultado tuvo?",
]
REPETICIONES = 5


def secuencial():
    """Three embeddings, one after another (the old behavior)."""
    return [rag.embeber(t, "RETRIEVAL_QUERY") for t in TEXTOS]


def paralelo():
    """Three embeddings at the same time (the current behavior)."""
    with ThreadPoolExecutor(len(TEXTOS)) as pool:
        return list(pool.map(lambda t: rag.embeber(t, "RETRIEVAL_QUERY"), TEXTOS))


def medir(funcion):
    """Seconds one call takes."""
    inicio = time.time()
    funcion()
    return time.time() - inicio


def main():
    paralelo()  # warm-up: opens the connection and loads the model
    tiempos = {"secuencial": [], "paralelo": []}
    for _ in range(REPETICIONES):
        # Alternating the order keeps time-of-day noise out of the comparison
        for nombre, funcion in (("secuencial", secuencial), ("paralelo", paralelo)):
            tiempos[nombre].append(medir(funcion))
            time.sleep(1)
    for nombre, valores in tiempos.items():
        print(f"{nombre:11} mediana {statistics.median(valores):.2f} s   "
              f"min {min(valores):.2f} s   max {max(valores):.2f} s")
    ganancia = statistics.median(tiempos["secuencial"]) - statistics.median(tiempos["paralelo"])
    print(f"Ahorro con 3 vectores: {ganancia:.2f} s por pregunta")


if __name__ == "__main__":
    main()
