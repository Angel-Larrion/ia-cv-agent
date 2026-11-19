"""Run the evaluation cases against the agent and report the metrics.

From the repo root:  python -m eval.run_eval --runs 2
Needs GEMINI_API_KEY in the environment.
"""
import argparse
import json
import os
import re
import statistics
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import agente
import rag
from eval.casos import CASOS

SALIDA = Path(__file__).resolve().parent / "resultados"
MAX_PALABRAS = 110  # the prompt asks for about 80; this leaves some room
GLOBAL_NO = [r"^como (un )?asistente", r"^as an ai"]  # openings the prompt forbids
TRAMPAS = "MNOP"  # case groups that probe invented or private data

eventos = []
busquedas = {}
buscar_real = rag.buscar


def normalizar(texto):
    """Lowercase and strip accents, so the patterns match any spelling."""
    texto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def buscar_cacheada(pregunta, historial=(), k=rag.K):
    """Search once per question: later runs reuse it and spend no embeddings."""
    clave = (pregunta, tuple(historial), k)
    if clave not in busquedas:
        busquedas[clave] = buscar_real(pregunta, historial, k)
        time.sleep(0.1)  # small margin: embeddings allow 100 per minute
    return busquedas[clave]


def buscar_roto(*args, **kwargs):
    """Force the fallback: the agent then sends every chunk in the prompt."""
    raise RuntimeError("evaluation without retrieval")


def metricas_recuperacion(esperados, resultado):
    """Hit@1, Hit@4, Hit@k, reciprocal rank and recall for one search."""
    ids = [f["id"] for f in resultado]
    posiciones = [ids.index(e) + 1 for e in esperados if e in ids]
    return {
        "hit1": ids[0] in esperados,
        "hit4": any(i in esperados for i in ids[:4]),
        "hitk": bool(posiciones),
        "rr": 1 / min(posiciones) if posiciones else 0.0,
        "recall": len(posiciones) / len(esperados),
        "ids": ids,
    }


def revisar(caso, respuesta):
    """Check one answer; return (assertions run, list of failures)."""
    texto = normalizar(respuesta)
    fallos = []
    total = 0
    for patron in caso["debe"]:
        total += 1
        if not re.search(patron, texto):
            fallos.append({"tipo": "debe", "patron": patron})
    for patron in caso["no_debe"] + GLOBAL_NO:
        total += 1
        if re.search(patron, texto):
            fallos.append({"tipo": "no_debe", "patron": patron})
    total += 1
    palabras = len(respuesta.split())
    if palabras > MAX_PALABRAS:
        fallos.append({"tipo": "largo", "patron": f"{palabras} palabras"})
    if caso["frases"]:
        total += 1
        frases = len(re.findall(r"[.!?](?:\s|$)", respuesta.strip()))
        if frases != caso["frases"]:
            fallos.append({"tipo": "frases", "patron": f"{frases} frases"})
    return total, fallos


def correr(caso, pausa):
    """Run one case once, turn by turn, like the platform does."""
    historial = []
    for turno in caso["turnos"]:
        historial.append(("user", turno))
        eventos.clear()
        inicio = time.time()
        respuesta = agente.responder(historial)
        ms = int((time.time() - inicio) * 1000)
        historial.append(("assistant", respuesta))
        time.sleep(pausa)
    previos = [t for r, t in historial[:-2] if r == "user"]
    return respuesta, ms, list(eventos), previos


def percentil(valores, p):
    """Nearest-rank percentile of a list."""
    valores = sorted(valores)
    return valores[min(len(valores) - 1, int(len(valores) * p))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2, help="runs per case")
    ap.add_argument("--nucleo", action="store_true", help="only the 14 core cases")
    ap.add_argument("--solo", default="", help="comma-separated case ids")
    ap.add_argument("--todos", action="store_true", help="no retrieval: every chunk in the prompt")
    ap.add_argument("--pausa", type=float, default=5, help="seconds between generations")
    ap.add_argument("--reintentos", type=int, default=4, help="retries on the main model")
    args = ap.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("Define GEMINI_API_KEY first")

    casos = CASOS
    if args.nucleo:
        casos = [c for c in casos if c["nucleo"]]
    if args.solo:
        ids = set(args.solo.split(","))
        casos = [c for c in casos if c["id"] in ids]

    # The agent reports events through registrar; keep them instead of printing
    agente.registrar = lambda evento, **campos: eventos.append({"evento": evento, **campos})
    agente.REINTENTOS = args.reintentos
    agente.PRESUPUESTO = 90  # more room than in production: the quota is shared
    rag.buscar = buscar_roto if args.todos else buscar_cacheada

    resultados = []
    for caso in casos:
        corridas = []
        for n in range(args.runs):
            respuesta, ms, evs, previos = correr(caso, args.pausa)
            total, fallos = revisar(caso, respuesta)
            corrida = {
                "respuesta": respuesta, "ms": ms, "aserciones": total, "fallos": fallos,
                "eventos": [e["evento"] for e in evs],
                "modelo": next((e["modelo"] for e in evs if e["evento"] == "respuesta"), None),
                "finish": next((e["finish"] for e in evs if e["evento"] == "respuesta"), None),
                "palabras": len(respuesta.split()),
            }
            if caso["esperados"] and not args.todos:
                resultado = buscar_cacheada(caso["turnos"][-1], previos)
                corrida["recuperacion"] = metricas_recuperacion(caso["esperados"], resultado)
            fragmentos = rag.leer_fragmentos() if args.todos else buscar_cacheada(caso["turnos"][-1], previos)
            corrida["tokens_entrada"] = len(agente.armar_prompt(fragmentos)) // 4  # rough estimate
            corridas.append(corrida)
            print(f"{caso['id']:4} run {n + 1}: {'ok' if not fallos else 'FALLA'} {ms} ms", flush=True)
            for f in fallos:
                print(f"       {f['tipo']}: {f['patron']}")
        resultados.append({"caso": caso, "corridas": corridas})

    resumen = resumir(resultados, args)
    SALIDA.mkdir(exist_ok=True)
    nombre = datetime.now().strftime("%Y%m%d-%H%M") + ("-todos" if args.todos else "-rag") + ".json"
    ruta = SALIDA / nombre
    ruta.write_text(json.dumps({"resumen": resumen, "resultados": resultados},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nSaved {ruta.name}")


def resumir(resultados, args):
    """Aggregate the metrics of the README table and print them."""
    corridas = [(r["caso"], c) for r in resultados for c in r["corridas"]]
    aserciones = sum(c["aserciones"] for _, c in corridas)
    falladas = sum(len(c["fallos"]) for _, c in corridas)
    limpias = sum(1 for _, c in corridas if not c["fallos"])
    fugas = sum(
        1 for caso, c in corridas if caso["id"][0] in TRAMPAS
        for f in c["fallos"] if f["tipo"] == "no_debe"
    )
    tiempos = [c["ms"] for _, c in corridas]
    con_rec = [c["recuperacion"] for _, c in corridas if "recuperacion" in c]
    degradadas = sum(1 for _, c in corridas
                     if set(c["eventos"]) & {"modelo_fallo", "error", "respuesta_amable"})
    respaldo = sum(1 for _, c in corridas if c["modelo"] == agente.MODELO_RESPALDO)
    cortadas = sum(1 for _, c in corridas if c["finish"] not in (None, "STOP"))

    resumen = {
        "modo": "todos" if args.todos else "rag",
        "casos": len(resultados), "corridas": len(corridas),
        "aserciones_cumplidas": f"{aserciones - falladas}/{aserciones}",
        "corridas_sin_fallos": f"{limpias}/{len(corridas)}",
        "fugas_en_trampas": fugas,
        "latencia_p50_ms": int(statistics.median(tiempos)),
        "latencia_p95_ms": percentil(tiempos, 0.95),
        "tokens_entrada_aprox": int(statistics.mean(c["tokens_entrada"] for _, c in corridas)),
        "palabras_media": round(statistics.mean(c["palabras"] for _, c in corridas), 1),
        "corridas_degradadas": degradadas, "con_modelo_de_respaldo": respaldo,
        "respuestas_cortadas": cortadas,
        "reintentos": sum(c["eventos"].count("reintento") for _, c in corridas),
    }
    if con_rec:
        for clave in ("hit1", "hit4", "hitk"):
            resumen[clave] = round(sum(r[clave] for r in con_rec) / len(con_rec), 3)
        resumen["mrr"] = round(statistics.mean(r["rr"] for r in con_rec), 3)
        resumen["recall"] = round(statistics.mean(r["recall"] for r in con_rec), 3)

    print("\n=== Summary ===")
    for clave, valor in resumen.items():
        print(f"{clave:24} {valor}")
    inestables = [r["caso"]["id"] for r in resultados
                  if 0 < sum(1 for c in r["corridas"] if c["fallos"]) < len(r["corridas"])]
    siempre = [r["caso"]["id"] for r in resultados if all(c["fallos"] for c in r["corridas"])]
    print(f"\nFail in every run: {', '.join(siempre) or '-'}")
    print(f"Fail in some runs: {', '.join(inestables) or '-'}")
    return resumen


if __name__ == "__main__":
    main()
