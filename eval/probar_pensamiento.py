"""Compare answer latency with the default thinking and a lower thinking level.

Calls Gemini directly with the same prompt for both settings, alternating the
order, and checks each answer with the evaluation assertions.
"""
import argparse
import statistics
import sys
import time

import httpx

import agente
from eval.casos import CASOS
from eval.run_eval import revisar

PREGUNTAS = ["A1", "B1", "E4", "G1", "I1", "X1"]
PAUSA = 4  # generation allows 15 requests per minute


def generar(prompt, mensajes, nivel):
    """One generation call; nivel=None keeps the model's default thinking."""
    config = {"temperature": agente.TEMPERATURA, "maxOutputTokens": agente.MAX_TOKENS_SALIDA}
    if nivel:
        config["thinkingConfig"] = {"thinkingLevel": nivel}
    cuerpo = {
        "systemInstruction": {"parts": [{"text": prompt}]},
        "contents": [
            {"role": "user" if rol == "user" else "model", "parts": [{"text": texto}]}
            for rol, texto in mensajes
        ],
        "generationConfig": config,
    }
    inicio = time.time()
    r = httpx.post(
        agente.URL_GENERAR.format(agente.MODELO), json=cuerpo,
        headers={"x-goog-api-key": agente.os.environ["GEMINI_API_KEY"]}, timeout=40,
    )
    ms = int((time.time() - inicio) * 1000)
    if r.status_code != 200:
        sys.exit(f"HTTP {r.status_code}: {r.text[:300]}")
    datos = r.json()
    texto, _ = agente.extraer_texto(datos)
    pensado = datos.get("usageMetadata", {}).get("thoughtsTokenCount", 0)
    return texto, ms, pensado


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nivel", default="minimal", help="thinking level to compare with the default")
    ap.add_argument("--reps", type=int, default=2, help="repetitions per question")
    ap.add_argument("--solo", help="comma-separated case ids")
    args = ap.parse_args()

    ids = args.solo.split(",") if args.solo else PREGUNTAS
    casos = [c for c in CASOS if c["id"] in ids]
    medidas = {"defecto": [], args.nivel: []}
    pensamiento = {"defecto": [], args.nivel: []}
    fallos = {"defecto": 0, args.nivel: 0}

    for c in casos:
        mensajes = agente.preparar([("user", t) for t in c["turnos"]])
        fragmentos, _ = agente.recuperar(mensajes)
        prompt = agente.armar_prompt(fragmentos)
        for rep in range(args.reps):
            orden = [("defecto", None), (args.nivel, args.nivel)]
            if rep % 2:
                orden.reverse()  # alternate so neither setting always goes first
            for nombre, nivel in orden:
                texto, ms, pensado = generar(prompt, mensajes, nivel)
                _, falla = revisar(c, texto)
                medidas[nombre].append(ms)
                pensamiento[nombre].append(pensado)
                fallos[nombre] += bool(falla)
                print(f"{c['id']:4} {nombre:8} {ms:6} ms  thinking tokens {pensado:5}  "
                      f"{'ok' if not falla else 'FALLA'}", flush=True)
                time.sleep(PAUSA)

    print("\nsetting    median ms  mean thinking tokens  failing answers")
    for nombre, valores in medidas.items():
        print(f"{nombre:10} {int(statistics.median(valores)):9}  "
              f"{int(statistics.mean(pensamiento[nombre])):20}  {fallos[nombre]}/{len(valores)}")


if __name__ == "__main__":
    main()
