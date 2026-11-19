import json
import os
import re
import time
from functools import lru_cache

import httpx

import rag

MODELO = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
MODELO_RESPALDO = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")
URL_GENERAR = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

REINTENTOS = int(os.environ.get("GEMINI_RETRIES", "2"))  # main model only
TEMPERATURA = 0.3       # low, for stable answers about the CV
MAX_MENSAJES = 12       # history messages accepted
MAX_CARACTERES = 2000   # max characters per message
MAX_TOKENS_SALIDA = 2048  # headroom in case the model spends tokens reasoning
PRESUPUESTO = 40        # max seconds to answer, retries included
TIMEOUT_LLAMADA = 20    # max seconds per Gemini call
MIN_RESTANTE = 3        # below this many seconds, no new attempt

SIN_PREGUNTA = "No recibí ninguna pregunta. ¿Qué te gustaría saber sobre la trayectoria de Angel?"

# Common words that are English but not Spanish, and the reverse, to detect the question's language
PALABRAS_EN = {"the", "you", "your", "yourself", "have", "how", "what", "which", "who", "when",
               "where", "why", "did", "does", "do", "are", "is", "was", "were", "with", "about",
               "tell", "many", "much", "can", "could", "would", "my", "of", "and", "it", "this"}
PALABRAS_ES = {"el", "la", "los", "las", "de", "del", "que", "como", "cuantos", "cuantas", "tu",
               "tus", "tienes", "eres", "para", "por", "con", "en", "un", "una", "y", "es", "al",
               "se", "sus", "cual", "donde", "cuando", "quien", "has", "he", "mi", "me", "lo"}


class ErrorGemini(Exception):
    """A Gemini call failed or came back empty."""


@lru_cache(maxsize=1)
def cargar_textos():
    """Read the prompt template and the full CV, once."""
    plantilla = (rag.DATA / "prompt.md").read_text(encoding="utf-8-sig")
    cv = (rag.DATA / "cv.md").read_text(encoding="utf-8-sig").strip()
    return plantilla, cv


def limpiar(texto):
    """Remove the tags that delimit the CV and chunks in the prompt."""
    return re.sub(r"</?\s*(cv|fragmentos)\s*>", "", texto, flags=re.IGNORECASE)


def preparar(mensajes):
    """Keep recent, short user/assistant messages; [] if no final user question."""
    limpios = []
    for rol, texto in mensajes:
        # system/developer roles dropped: the client can't give instructions
        if rol not in ("user", "assistant") or not isinstance(texto, str):
            continue
        texto = limpiar(texto).strip()[:MAX_CARACTERES]
        if texto:
            limpios.append((rol, texto))
    limpios = limpios[-MAX_MENSAJES:]
    # The conversation must start and end with the user
    while limpios and limpios[0][0] != "user":
        limpios.pop(0)
    if not limpios or limpios[-1][0] != "user":
        return []
    return limpios


def recuperar(mensajes):
    """Search relevant chunks; if it fails, return all of them."""
    pregunta = mensajes[-1][1]
    previos = [t for r, t in mensajes[:-1] if r == "user"]
    try:
        return rag.buscar(pregunta, previos), "rag"
    except Exception as e:
        registrar("rag_fallo", error=f"{type(e).__name__}: {e}"[:200])
        return rag.leer_fragmentos(), "todos"


def es_ingles(texto):
    """True only when the text is clearly English; when unsure, leave it to the model."""
    palabras = re.findall(r"[a-záéíóúñ]+", texto.lower())
    en = sum(p in PALABRAS_EN for p in palabras)
    es = sum(p in PALABRAS_ES for p in palabras)
    return en >= 2 and en > es


def armar_prompt(fragmentos):
    """Fill {cv} and {fragmentos} in the template."""
    plantilla, cv = cargar_textos()
    texto = "\n\n".join(f"### {f['titulo']}\n{f['texto']}" for f in fragmentos)
    valores = {"cv": cv, "fragmentos": texto}
    # One pass, so a placeholder inside the CV isn't replaced
    return re.sub(r"\{(cv|fragmentos)\}", lambda m: valores[m.group(1)], plantilla)


def extraer_texto(datos):
    """Join the parts' text and return (text, finishReason)."""
    candidatos = datos.get("candidates") or []
    partes = candidatos[0].get("content", {}).get("parts", []) if candidatos else []
    motivo = candidatos[0].get("finishReason") if candidatos else "sin candidatos"
    # Thought parts are skipped; only the answer text goes out
    texto = "".join(p.get("text", "") for p in partes if not p.get("thought")).strip()
    if not texto:
        raise ErrorGemini(f"respuesta vacía ({motivo})")
    return texto, motivo


def llamar_gemini(modelo, prompt, mensajes, reintentos, limite):
    """Ask one model for the answer; return (text, finishReason).

    Retries only on 429, 5xx or network errors, never past `limite`.
    """
    cuerpo = {
        "systemInstruction": {"parts": [{"text": prompt}]},
        "contents": [
            {"role": "user" if rol == "user" else "model", "parts": [{"text": texto}]}
            for rol, texto in mensajes
        ],
        "generationConfig": {"temperature": TEMPERATURA, "maxOutputTokens": MAX_TOKENS_SALIDA},
    }
    clave = os.environ["GEMINI_API_KEY"]
    ultimo = None
    for intento in range(reintentos + 1):
        restante = limite - time.time()
        if restante < MIN_RESTANTE:
            raise ErrorGemini(f"{modelo}: sin tiempo ({ultimo})")
        try:
            r = httpx.post(
                URL_GENERAR.format(modelo),
                json=cuerpo,
                headers={"x-goog-api-key": clave},
                timeout=min(TIMEOUT_LLAMADA, restante),
            )
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = f"HTTP {r.status_code}"
            else:
                r.raise_for_status()  # a 400 or 403 isn't fixed by retrying
                return extraer_texto(r.json())
        except httpx.TransportError as e:
            ultimo = type(e).__name__
        espera = 5 * (intento + 1)
        if intento < reintentos:
            if time.time() + espera > limite - MIN_RESTANTE:
                break  # no point waiting if there's no time for another call
            registrar("reintento", modelo=modelo, motivo=ultimo, espera=espera)
            time.sleep(espera)
    raise ErrorGemini(f"{modelo}: {ultimo}")


def mensaje_amable():
    """Last-resort reply: apology plus the CV profile summary."""
    texto = ("Tuve un problema técnico y no pude consultar mi información completa en este "
             "momento. Puedes intentarlo de nuevo en un minuto.")
    try:
        _, cv = cargar_textos()
        perfil = re.search(r"^## Profile\s+(.+?)(?=^## |\Z)", cv, re.MULTILINE | re.DOTALL)
        if perfil:
            texto += "\n\nMientras tanto, un resumen de mi perfil:\n" + perfil.group(1).strip()
    except Exception:
        pass
    return texto


def registrar(evento, **campos):
    """Print one JSON line per event (shows in Render logs)."""
    print(json.dumps({"evento": evento, **campos}, ensure_ascii=False), flush=True)


def responder(mensajes):
    """Take [(role, text), ...] and return the answer; never raises."""
    inicio = time.time()
    limite = inicio + PRESUPUESTO
    try:
        mensajes = preparar(mensajes)
        if not mensajes:
            return SIN_PREGUNTA
        fragmentos, modo = recuperar(mensajes)
        prompt = armar_prompt(fragmentos)
        # The prompt and the documents are in Spanish and pull short English questions that way
        if es_ingles(mensajes[-1][1]):
            prompt += "\n\nThe user's last message is in English: answer entirely in English."
        # Main model with retries, then the fallback with a single attempt
        for modelo, reintentos in ((MODELO, REINTENTOS), (MODELO_RESPALDO, 0)):
            try:
                texto, motivo = llamar_gemini(modelo, prompt, mensajes, reintentos, limite)
            except Exception as e:
                registrar("modelo_fallo", modelo=modelo, error=f"{type(e).__name__}: {e}"[:200])
                continue
            registrar(
                "respuesta", modelo=modelo, modo=modo, finish=motivo,
                fragmentos=[f["id"] for f in fragmentos],
                puntajes=[round(f["puntaje"], 3) for f in fragmentos if "puntaje" in f],
                ms=int((time.time() - inicio) * 1000),
            )
            return texto
    except Exception as e:
        registrar("error", error=f"{type(e).__name__}: {e}"[:200])
    registrar("respuesta_amable", ms=int((time.time() - inicio) * 1000))
    return mensaje_amable()