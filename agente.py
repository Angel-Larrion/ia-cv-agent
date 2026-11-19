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

REINTENTOS = int(os.environ.get("GEMINI_RETRIES", "2"))  # solo para el modelo principal
TEMPERATURA = 0.3       # baja, para que las respuestas sobre el CV sean estables
MAX_MENSAJES = 12       # mensajes del historial que se aceptan
MAX_CARACTERES = 2000   # largo máximo de cada mensaje
MAX_TOKENS_SALIDA = 2048  # holgura por si el modelo gasta tokens razonando
PRESUPUESTO = 40        # segundos máximos para generar la respuesta, contando reintentos
TIMEOUT_LLAMADA = 20    # segundos máximos de cada llamada a Gemini
MIN_RESTANTE = 3        # con menos segundos que estos ya no se intenta otra llamada

SIN_PREGUNTA = "No recibí ninguna pregunta. ¿Qué te gustaría saber sobre la trayectoria de Angel?"


class ErrorGemini(Exception):
    pass


@lru_cache(maxsize=1)
def cargar_textos():
    """Lee la plantilla del prompt y el CV completo (una sola vez)."""
    plantilla = (rag.DATA / "prompt.md").read_text(encoding="utf-8-sig")
    cv = (rag.DATA / "cv.md").read_text(encoding="utf-8-sig").strip()
    return plantilla, cv


def limpiar(texto):
    """Quita las etiquetas que delimitan el CV y los fragmentos dentro del prompt."""
    return re.sub(r"</?\s*(cv|fragmentos)\s*>", "", texto, flags=re.IGNORECASE)


def preparar(mensajes):
    """Deja solo mensajes de usuario y asistente, recientes, cortos y sin etiquetas del prompt.

    Se descartan los roles system/developer: el cliente no puede dar instrucciones.
    Devuelve [] si no queda ninguna pregunta del usuario al final.
    """
    limpios = []
    for rol, texto in mensajes:
        if rol not in ("user", "assistant") or not isinstance(texto, str):
            continue
        texto = limpiar(texto).strip()[:MAX_CARACTERES]
        if texto:
            limpios.append((rol, texto))
    limpios = limpios[-MAX_MENSAJES:]
    while limpios and limpios[0][0] != "user":
        limpios.pop(0)
    if not limpios or limpios[-1][0] != "user":
        return []
    return limpios


def recuperar(mensajes):
    """Busca los fragmentos relevantes; si falla, devuelve todos (respaldo)."""
    pregunta = mensajes[-1][1]
    previos = [t for r, t in mensajes[:-1] if r == "user"]
    try:
        return rag.buscar(pregunta, previos), "rag"
    except Exception as e:
        registrar("rag_fallo", error=f"{type(e).__name__}: {e}"[:200])
        return rag.leer_fragmentos(), "todos"


def armar_prompt(fragmentos):
    """Rellena {cv} y {fragmentos} de la plantilla en una sola pasada."""
    plantilla, cv = cargar_textos()
    texto = "\n\n".join(f"### {f['titulo']}\n{f['texto']}" for f in fragmentos)
    valores = {"cv": cv, "fragmentos": texto}
    return re.sub(r"\{(cv|fragmentos)\}", lambda m: valores[m.group(1)], plantilla)


def extraer_texto(datos):
    """Junta solo el campo 'text' de las partes y devuelve (texto, finishReason)."""
    candidatos = datos.get("candidates") or []
    partes = candidatos[0].get("content", {}).get("parts", []) if candidatos else []
    motivo = candidatos[0].get("finishReason") if candidatos else "sin candidatos"
    texto = "".join(p.get("text", "") for p in partes if not p.get("thought")).strip()
    if not texto:
        raise ErrorGemini(f"respuesta vacía ({motivo})")
    return texto, motivo


def llamar_gemini(modelo, prompt, mensajes, reintentos, limite):
    """Pide la respuesta a un modelo y devuelve (texto, finishReason).

    Reintenta solo si hay 429, error 5xx o corte de red, y nunca pasa de `limite`
    (hora en que se acaba el presupuesto de tiempo).
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
                r.raise_for_status()  # un 400 o 403 no se arregla reintentando
                return extraer_texto(r.json())
        except httpx.TransportError as e:
            ultimo = type(e).__name__
        espera = 5 * (intento + 1)
        if intento < reintentos:
            if time.time() + espera > limite - MIN_RESTANTE:
                break  # no tiene caso esperar si ya no alcanzará otra llamada
            time.sleep(espera)
    raise ErrorGemini(f"{modelo}: {ultimo}")


def mensaje_amable():
    """Respuesta cuando nada funcionó: resumen del perfil sacado del CV."""
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
    """Una línea JSON por evento; se ve en los logs de Render."""
    print(json.dumps({"evento": evento, **campos}, ensure_ascii=False), flush=True)


def responder(mensajes):
    """Recibe [(rol, texto), ...] y devuelve el texto de la respuesta. Nunca lanza error."""
    inicio = time.time()
    limite = inicio + PRESUPUESTO
    try:
        mensajes = preparar(mensajes)
        if not mensajes:
            return SIN_PREGUNTA
        fragmentos, modo = recuperar(mensajes)
        prompt = armar_prompt(fragmentos)
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