# Deploying the Chief of Staff agent

Wraps the agent from
[`01_The_chief_of_staff_agent.ipynb`](../01_The_chief_of_staff_agent.ipynb) in a
FastAPI + SSE server and packages it as a container. Same HTTP contract as the
research-agent hosting tiers in [`../../hosting/`](../../hosting/).

```
deploy/
  server.py         ← FastAPI + SSE server wrapping the agent
  entrypoint.sh     ← starts uvicorn on :8000
  requirements.txt
  Dockerfile        ← agent image (build context = chief_of_staff_agent/)
  Dockerfile.dockerignore
  .env.example
  fly/              ← Fly.io deploy (fly.toml + deploy.sh + README)
```

## Browser UI

Open the app's root URL (`https://<app>.fly.dev/`) for a minimal chat page
([`ui.html`](ui.html), served at `/`). Paste the `AGENT_AUTH_TOKEN` into the
field once (kept in `localStorage`), pick a session id, and chat — slash
commands like `/budget-impact …` work straight from the box. No curl needed.

## Interface

```
GET  /                                 → 200 text/html (chat UI)       (open)
GET  /health                           → 200 {"status":"ok"}          (open)
POST /sessions/{session_id}/messages   → text/event-stream            (token-gated)
     Body: {"prompt":"...", "output_style":"executive" | null}
     Reuse a session_id to continue the conversation; change it to start fresh.

Required env: ANTHROPIC_API_KEY
Optional env: AGENT_AUTH_TOKEN (required for any public URL — gates /sessions/*),
              MODEL (default claude-opus-4-6), PERMISSION_MODE (default "default"),
              CLAUDE_CONFIG_DIR (default /data — mount for persistence),
              AGENT_CWD (default /app — where .claude/ + CLAUDE.md load from)
```

⚠️ This agent runs **Bash, Write, and Edit**. Never expose it without
`AGENT_AUTH_TOKEN`, and treat the container as disposable. See the security note
in [`fly/README.md`](fly/README.md).

## Run locally (Docker)

```bash
cd claude_agent_sdk/chief_of_staff_agent/
docker build -f deploy/Dockerfile -t chief-of-staff-agent .
docker run --rm -p 127.0.0.1:8000:8000 \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -v "$PWD/.sessions:/data" \
  chief-of-staff-agent

# In another shell (no token needed when bound to loopback with AGENT_AUTH_TOKEN unset):
curl -N -X POST localhost:8000/sessions/demo-1/messages \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"/strategic-brief Q2 hiring plan","output_style":"executive"}'
```

## Deploy to Fly.io

See [`fly/README.md`](fly/README.md). Short version:

```bash
cd claude_agent_sdk/chief_of_staff_agent/
export ANTHROPIC_API_KEY=sk-ant-...
./deploy/fly/deploy.sh
```
