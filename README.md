# ia-cv-agent

Agente de CV de Angel Larrión. Expone `POST /v1/responses` (Open Responses) con streaming SSE y se despliega como contenedor.

Estado: esqueleto con respuesta fija. Pendiente: RAG sobre el CV y los proyectos, Gemini, evaluación.

## Correr en local

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export AGENT_API_KEY=mi-clave
uvicorn app:app --reload
```

```bash
curl http://localhost:8000/v1/responses \
  -H "Authorization: Bearer mi-clave" \
  -H "Content-Type: application/json" \
  -d '{"input": "Hola"}'
```

## Docker

```bash
docker build -t ia-cv-agent .
docker run -p 8000:8000 -e AGENT_API_KEY=mi-clave ia-cv-agent
```

Las variables de entorno están en `.env.example`.
