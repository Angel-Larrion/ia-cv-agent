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

# 768: tamaño recomendado por Google y suficiente para un corpus pequeño (se revisa en la evaluación)
MODELO_EMBED = os.environ.get("EMBED_MODEL", "gemini-embedding-001")
DIMENSIONES = 768
URL_EMBED = "https://generativelanguage.googleapis.com/v1beta/models/{}:embedContent"

K = 8                   # fragmentos que se mandan al modelo (se compara con 6 y 10)
BOOST_EMPRESA = 0.03    # empujón a los fragmentos de la empresa mencionada
EMPRESAS = ["propaga", "stori", "coppel", "sas"]


def leer_fragmentos(ruta=DATA / "proyectos.md"):
    """Parte proyectos.md en fragmentos: uno por cada encabezado '###'."""
    texto = Path(ruta).read_text(encoding="utf-8-sig")
    fragmentos = []
    titulo = None
    cuerpo = []

    def guardar():
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
            # Un encabezado de sección o una raya cierra el fragmento actual
            guardar()
            titulo = None
            cuerpo = []
        elif titulo:
            cuerpo.append(linea)
    guardar()
    return fragmentos


def embeber(texto, tarea):
    """Pide a Gemini el embedding de un texto y lo devuelve normalizado.

    tarea: "RETRIEVAL_DOCUMENT" para fragmentos, "RETRIEVAL_QUERY" para preguntas.
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
        # 429 = limite de peticiones: se espera y se reintenta.
        if r.status_code == 429:
            if intento < 2:
                time.sleep(5 * (intento + 1))
            continue
        r.raise_for_status()
        v = np.array(r.json()["embedding"]["values"], dtype="float32")
        # Gemini no normaliza con 768 dimensiones, asi que lo hacemos aqui:
        # con vectores de longitud 1, coseno = producto punto.
        return v / np.linalg.norm(v)
    raise RuntimeError("Gemini respondio 429 tres veces seguidas")


def hash_fragmentos(fragmentos):
    """Huella del contenido de los fragmentos (no depende de los saltos de línea del archivo)."""
    texto = "\n".join(f["titulo"] + "\n" + f["texto"] for f in fragmentos)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def cargar_indice():
    """Carga data/index.json y comprueba que corresponda al modelo y al documento actuales."""
    datos = json.loads(INDICE.read_text(encoding="utf-8"))
    if datos["modelo"] != MODELO_EMBED or datos["dimensiones"] != DIMENSIONES:
        raise ValueError("El índice se hizo con otro modelo o con otras dimensiones")
    if datos["hash"] != hash_fragmentos(leer_fragmentos()):
        raise ValueError("proyectos.md cambió: hay que volver a correr scripts.build_index")
    fragmentos = datos["fragmentos"]
    matriz = np.array([f.pop("vector") for f in fragmentos], dtype="float32")
    # Se normaliza de nuevo porque los vectores guardados están redondeados
    matriz /= np.linalg.norm(matriz, axis=1, keepdims=True)
    return fragmentos, matriz


def buscar(pregunta, historial=(), k=K):
    """Devuelve los k fragmentos más parecidos a la pregunta, con su puntaje.

    historial: mensajes previos del usuario, del más antiguo al más reciente.
    """
    fragmentos, matriz = cargar_indice()

    # Vectores de la pregunta: sola, con el mensaje previo y con los dos previos
    previos = list(historial)[-2:]
    textos = [pregunta]
    if previos:
        textos.append(" ".join(previos[-1:] + [pregunta]))
    if len(previos) == 2:
        textos.append(" ".join(previos + [pregunta]))

    # Cada fragmento se queda con su mejor puntaje entre los vectores
    puntajes = np.max([matriz @ embeber(t, "RETRIEVAL_QUERY") for t in textos], axis=0)

    # Empujón a los fragmentos de la empresa que se nombra en la pregunta
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

