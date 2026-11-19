import hmac
import json
import os
import time
import uuid

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

import agente
import rag

API_KEY = os.environ.get("AGENT_API_KEY", "")
MODEL = "angel-larrion-cv-agent"

app = FastAPI(title="CV agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def precalentar():
    """Carga el prompt y el índice al arrancar: si algo falla, se ve en los logs de inmediato."""
    if not API_KEY:
        agente.registrar("arranque_sin_clave", aviso="AGENT_API_KEY no está definida: el endpoint rechaza todas las peticiones")
    try:
        agente.cargar_textos()
        rag.cargar_indice()
    except Exception as e:
        agente.registrar("arranque_fallo", error=f"{type(e).__name__}: {e}"[:200])


precalentar()


def check_auth(authorization):
    # Sin AGENT_API_KEY el endpoint se cierra: nunca queda abierto por omisión
    if not API_KEY:
        raise HTTPException(503, "Server misconfigured: AGENT_API_KEY is not set")
    if not hmac.compare_digest((authorization or "").encode(), f"Bearer {API_KEY}".encode()):
        raise HTTPException(401, "Invalid or missing API key")


def parse_input(body):
    """`input` puede ser un string o una lista de items; devuelve [(rol, texto)]."""
    raw = body.get("input", "")
    if isinstance(raw, str):
        return [("user", raw)]
    if not isinstance(raw, list):
        return []
    messages = []
    for item in raw:
        if not isinstance(item, dict) or item.get("type", "message") != "message":
            continue
        content = item.get("content", "")
        if isinstance(content, list):
            content = "".join(
                p["text"] for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)
            )
        messages.append((item.get("role", "user"), content))
    return messages


def response_object(resp_id, created, text, status, body):
    output = []
    if status == "completed":
        output = [message_item(resp_id, text, "completed")]
    return {
        "id": resp_id,
        "object": "response",
        "created_at": created,
        "completed_at": int(time.time()) if status == "completed" else None,
        "status": status,
        "incomplete_details": None,
        "model": body.get("model") or MODEL,
        "previous_response_id": None,
        "instructions": body.get("instructions"),
        "output": output,
        "error": None,
        "tools": [],
        "tool_choice": "auto",
        "truncation": "disabled",
        "parallel_tool_calls": False,
        "text": {"format": {"type": "text"}},
        "top_p": 1.0,
        "temperature": 1.0,
        "usage": None,
        "metadata": {},
    }


def message_item(resp_id, text, status):
    content = [{"type": "output_text", "text": text, "annotations": []}] if text else []
    return {
        "id": "msg_" + resp_id[5:],
        "type": "message",
        "status": status,
        "role": "assistant",
        "content": content,
    }


def sse(event, data):
    data = {"type": event, **data}
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream(text, body):
    resp_id = "resp_" + uuid.uuid4().hex
    created = int(time.time())
    msg_id = "msg_" + resp_id[5:]
    seq = iter(range(10_000))
    ref = {"item_id": msg_id, "output_index": 0, "content_index": 0}

    started = response_object(resp_id, created, "", "in_progress", body)
    yield sse("response.created", {"sequence_number": next(seq), "response": started})
    yield sse("response.in_progress", {"sequence_number": next(seq), "response": started})
    yield sse("response.output_item.added", {
        "sequence_number": next(seq), "output_index": 0,
        "item": message_item(resp_id, "", "in_progress"),
    })
    yield sse("response.content_part.added", {
        "sequence_number": next(seq), **ref,
        "part": {"type": "output_text", "text": "", "annotations": []},
    })

    words = text.split(" ")
    for i, word in enumerate(words):
        delta = word if i == len(words) - 1 else word + " "
        yield sse("response.output_text.delta", {"sequence_number": next(seq), **ref, "delta": delta})

    part = {"type": "output_text", "text": text, "annotations": []}
    yield sse("response.output_text.done", {"sequence_number": next(seq), **ref, "text": text})
    yield sse("response.content_part.done", {"sequence_number": next(seq), **ref, "part": part})
    yield sse("response.output_item.done", {
        "sequence_number": next(seq), "output_index": 0,
        "item": message_item(resp_id, text, "completed"),
    })
    final = response_object(resp_id, created, text, "completed", body)
    yield sse("response.completed", {"sequence_number": next(seq), "response": final})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/.well-known/agent-card.json")
def agent_card(request: Request):
    base = str(request.base_url).rstrip("/")
    return {
        "name": "Angel Larrion - AI Engineer",
        "description": "Agente conversacional sobre el perfil profesional de Angel Larrion.",
        "url": f"{base}/v1",
        "version": "0.1.0",
        "capabilities": {"streaming": True},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [{
            "id": "cv-qa",
            "name": "Preguntas sobre el CV",
            "description": "Experiencia, habilidades y proyectos.",
            "tags": ["cv", "career"],
        }],
    }


@app.post("/v1/responses")
async def create_response(request: Request, authorization: str | None = Header(default=None)):
    check_auth(authorization)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")

    # agente.responder espera a la red: en un hilo aparte para no bloquear a otros usuarios.
    # El campo `instructions` del cliente se ignora a propósito.
    text = await run_in_threadpool(agente.responder, parse_input(body))

    if body.get("stream"):
        return StreamingResponse(stream(text, body), media_type="text/event-stream")
    resp_id = "resp_" + uuid.uuid4().hex
    return JSONResponse(response_object(resp_id, int(time.time()), text, "completed", body))
