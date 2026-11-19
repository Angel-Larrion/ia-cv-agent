import collections
import hmac
import json
import os
import threading
import time
import uuid

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

import agente
import rag

API_KEY = os.environ.get("AGENT_API_KEY", "").strip()
MODEL = "angel-larrion-cv-agent"
MAX_BODY = 256 * 1024  # bytes; a full 12-message history is about 25 KB
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MIN", "60"))  # 0 turns it off
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "https://hackathon-2024.com").split(",") if o.strip()]

app = FastAPI(title="CV agent")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["Authorization", "Content-Type"])

recent_requests = collections.deque()
rate_lock = threading.Lock()


def precalentar():
    """Load prompt and index at startup so failures show in the logs."""
    if not API_KEY:
        agente.registrar("arranque_sin_clave", aviso="AGENT_API_KEY no está definida: el endpoint rechaza todas las peticiones")
    try:
        agente.cargar_textos()
        rag.cargar_indice()
    except Exception as e:
        agente.registrar("arranque_fallo", error=f"{type(e).__name__}: {e}"[:200])


precalentar()


def check_auth(authorization):
    """Reject the request unless it carries the right Bearer key."""
    # Without AGENT_API_KEY the endpoint stays closed, never open by default
    if not API_KEY:
        raise HTTPException(503, "Server misconfigured: AGENT_API_KEY is not set")
    # compare_digest: constant time, and safe with non-ASCII headers
    if not hmac.compare_digest((authorization or "").encode(), f"Bearer {API_KEY}".encode()):
        raise HTTPException(401, "Invalid or missing API key")


def check_rate():
    """Allow at most RATE_LIMIT requests per rolling minute, shared by all clients."""
    if RATE_LIMIT <= 0:
        return
    now = time.monotonic()
    with rate_lock:
        while recent_requests and now - recent_requests[0] > 60:
            recent_requests.popleft()
        if len(recent_requests) >= RATE_LIMIT:
            wait = int(60 - (now - recent_requests[0])) + 1
            raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(wait)})
        recent_requests.append(now)


async def read_body(request):
    """Read the body, refusing anything over MAX_BODY bytes."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY:
        raise HTTPException(413, "Body too large")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise HTTPException(413, "Body too large")
        chunks.append(chunk)
    return b"".join(chunks)


def parse_input(body):
    """Turn the request `input` (string or items) into [(role, text)]."""
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
    """Build the Open Responses response object."""
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
        "temperature": agente.TEMPERATURA,
        "usage": None,
        "metadata": {},
    }


def message_item(resp_id, text, status):
    """Build the assistant message item of a response."""
    content = [{"type": "output_text", "text": text, "annotations": []}] if text else []
    return {
        "id": "msg_" + resp_id[5:],
        "type": "message",
        "status": status,
        "role": "assistant",
        "content": content,
    }


def sse(event, data):
    """Format one server-sent event."""
    data = {"type": event, **data}
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream(text, body):
    """Emit the answer as SSE events; full text, split into words."""
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

    # Simulated streaming: the answer is already complete
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
    """Health check for Render."""
    return {"status": "ok"}


@app.get("/.well-known/agent-card.json")
def agent_card(request: Request):
    """Serve the A2A agent card."""
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
    """Answer a /v1/responses request, as JSON or as a stream."""
    check_auth(authorization)
    check_rate()
    try:
        body = json.loads(await read_body(request))
    except ValueError:
        raise HTTPException(400, "Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")

    # Own thread: responder waits on the network and would block the server
    # The client's `instructions` field is ignored on purpose
    text = await run_in_threadpool(agente.responder, parse_input(body))

    if body.get("stream"):
        return StreamingResponse(stream(text, body), media_type="text/event-stream")
    resp_id = "resp_" + uuid.uuid4().hex
    return JSONResponse(response_object(resp_id, int(time.time()), text, "completed", body))
