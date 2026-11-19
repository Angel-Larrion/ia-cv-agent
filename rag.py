import hashlib
import json
import os
import re
import time
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
INDICE = DATA / "index.json"

# 768: Google's recommended size, enough for a small corpus
MODELO_EMBED = os.environ.get("EMBED_MODEL", "gemini-embedding-001")
DIMENSIONES = 768
URL_EMBED = "https://generativelanguage.googleapis.com/v1beta/models/{}:embedContent"

K = 8                   # chunks sent to the model (compare with 6 and 10)
BOOST_EMPRESA = 0.03    # score bonus for chunks of the company named
EMPRESAS = ["propaga", "stori", "coppel", "sas"]


def leer_fragmentos(ruta=DATA / "proyectos.md"):
    """Split proyectos.md into chunks, one per '###' heading."""
    texto = Path(ruta).read_text(encoding="utf-8-sig")
    fragmentos = []
    titulo = None
    cuerpo = []

    def guardar():
        """Save the chunk being built, if it has a title."""
        if titulo:
            fragmentos.append({
                "id": len(fragmentos),
                "titulo": titulo,
                "texto": "\n".join(cuerpo).strip(),
            })

    for linea in texto.splitlines():
        if linea.startswith("### "):
            guardar()
            titulo = linea[4:].strip()
            cuerpo = []
        elif linea.startswith("#") or linea.strip() == "---":
            # A section heading or a rule closes the current chunk
            guardar()
            titulo = None
            cuerpo = []
        elif titulo:
            cuerpo.append(linea)
    guardar()
    return fragmentos


def embeber(texto, tarea):
    """Return the normalized Gemini embedding of a text.

    tarea: RETRIEVAL_DOCUMENT for chunks, RETRIEVAL_QUERY for questions.
    """
    clave = os.environ["GEMINI_API_KEY"]
    cuerpo = {
        "model": f"models/{MODELO_EMBED}",
        "content": {"parts": [{"text": texto}]},
        "taskType": tarea,
        "outputDimensionality": DIMENSIONES,
    }
    for intento in range(3):
        r = httpx.post(
            URL_EMBED.format(MODELO_EMBED),
            json=cuerpo,
            headers={"x-goog-api-key": clave},
            timeout=20,
        )
        # 429 = rate limit: wait and retry
        if r.status_code == 429:
            if intento < 2:
                time.sleep(5 * (intento + 1))
            continue
        r.raise_for_status()
        v = np.array(r.json()["embedding"]["values"], dtype="float32")
        # Not normalized at 768 dims; unit vectors make cosine a dot product
        return v / np.linalg.norm(v)
    raise RuntimeError("Gemini respondio 429 tres veces seguidas")


def hash_fragmentos(fragmentos):
    """Fingerprint of the chunk text, independent of line endings."""
    texto = "\n".join(f["titulo"] + "\n" + f["texto"] for f in fragmentos)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def cargar_indice():
    """Load index.json and check it matches the model and document."""
    datos = json.loads(INDICE.read_text(encoding="utf-8"))
    if datos["modelo"] != MODELO_EMBED or datos["dimensiones"] != DIMENSIONES:
        raise ValueError("El índice se hizo con otro modelo o con otras dimensiones")
    if datos["hash"] != hash_fragmentos(leer_fragmentos()):
        raise ValueError("proyectos.md cambió: hay que volver a correr scripts.build_index")
    fragmentos = datos["fragmentos"]
    matriz = np.array([f.pop("vector") for f in fragmentos], dtype="float32")
    # Normalize again: the stored vectors were rounded
    matriz /= np.linalg.norm(matriz, axis=1, keepdims=True)
    return fragmentos, matriz


def buscar(pregunta, historial=(), k=K):
    """Return the k chunks closest to the question, with scores.

    historial: previous user messages, oldest first.
    """
    fragmentos, matriz = cargar_indice()

    # Query vectors: alone, with last message, with last two
    previos = list(historial)[-2:]
    textos = [pregunta]
    if previos:
        textos.append(" ".join(previos[-1:] + [pregunta]))
    if len(previos) == 2:
        textos.append(" ".join(previos + [pregunta]))

    # Each chunk keeps its best score across the vectors
    puntajes = np.max([matriz @ embeber(t, "RETRIEVAL_QUERY") for t in textos], axis=0)

    # Bonus for chunks of the company named in the question
    nombradas = [e for e in EMPRESAS if re.search(rf"\b{e}\b", pregunta.lower())]
    for i, f in enumerate(fragmentos):
        empresa = f["titulo"].split(" · ")[0].lower()
        if any(re.search(rf"\b{e}\b", empresa) for e in nombradas):
            puntajes[i] += BOOST_EMPRESA

    orden = np.argsort(-puntajes)[:k]
    return [
        {
            "id": fragmentos[i]["id"],
            "titulo": fragmentos[i]["titulo"],
            "texto": fragmentos[i]["texto"],
            "puntaje": float(puntajes[i]),
        }
        for i in orden
    ]

