"""FastAPI wrapper that exposes the Chief of Staff agent over HTTP + SSE.

This is the ``hosting/server.py`` pattern (see ../../hosting/) adapted to the
Chief of Staff agent from ``01_The_chief_of_staff_agent.ipynb``. The interface
contract is identical, so the same clients and the same gateway work against it:

  GET  /health                              → 200 {"status": "ok"}
  POST /sessions/{session_id}/messages      → text/event-stream (message/done/error)
        Body: {"prompt": "...", "output_style": "executive" | null}

⚠️  SECURITY — READ THIS BEFORE DEPLOYING
Unlike the research agent (which the hosting tier locks to WebSearch only), this
agent runs with **Bash, Write, and Edit enabled** — it can execute the bundled
scripts and write reports. That is the whole point of the demo, but it also means
anyone who can POST to this server can run code and write files *inside the
container* (which also holds your ANTHROPIC_API_KEY and every other session's
transcripts). So:

  - Never expose this without auth. On a public URL (e.g. Fly.io) set
    ``AGENT_AUTH_TOKEN`` — the server then requires ``Authorization: Bearer
    <token>`` on ``/sessions/*``. ``/health`` stays open for liveness probes.
  - The token gates *access*, it does not *sandbox* the agent. Treat the
    container as disposable and give the API key the least scope you can.
  - For real multi-tenant use, put an authenticating gateway in front that
    scopes each ``session_id`` to its caller (see ../../hosting/README.md).

Session continuity works exactly like the hosting tier: the SDK mints its own
session IDs, so we persist a map from the caller's ``session_id`` to the SDK's
internal ID under ``CLAUDE_CONFIG_DIR`` and pass it to ``resume=`` next turn.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

# The Chief of Staff system prompt, lifted verbatim from chief_of_staff_agent/
# agent.py's send_query() so this server deploys *that* agent. The paths it
# mentions (scripts/, financial_data/) resolve relative to AGENT_CWD below.
COS_SYSTEM_PROMPT = """You are the Chief of Staff for TechStart Inc, a 50-person startup.

        Apart from your tools and two subagents, you also have custom Python scripts in the scripts/ directory you can run with Bash:
        - python scripts/financial_forecast.py: Advanced financial modeling
        - python scripts/talent_scorer.py: Candidate scoring algorithm
        - python scripts/decision_matrix.py: Strategic decision framework

        You have access to company data in the financial_data/ directory.
        """

# Same shape the k8s gateway enforces: must start alphanumeric so a session_id
# can never begin with "-"/"_" (safe as a filename or k8s label).
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# Opt-in bearer token for deployments with a public URL and no gateway.
AUTH_TOKEN = os.environ.get("AGENT_AUTH_TOKEN")

CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", "/data"))
SESSION_MAP_PATH = CONFIG_DIR / "hosting_session_map.json"

# Where .claude/ (commands, agents, hooks, output-styles) and CLAUDE.md live.
# setting_sources=["project","local"] loads them from here, and it must match
# resume's expectations, so keep it stable. The Dockerfile copies the agent to
# /app and sets this as WORKDIR.
AGENT_CWD = os.environ.get("AGENT_CWD", "/app")

# The agent's full toolset from the notebook. Task enables the financial-analyst
# and recruiter subagents; Bash runs the bundled scripts; Write/Edit produce
# reports. See the security note in the module docstring.
ALLOWED_TOOLS = ["Task", "Read", "Write", "Edit", "Bash", "WebSearch"]

MAX_BUFFER_SIZE = 10 * 1024 * 1024
MAX_BODY_BYTES = 256 * 1024

# The notebook uses Opus. Override with MODEL=claude-sonnet-4-6 to run cheap.
DEFAULT_MODEL = "claude-opus-4-6"

# The notebook runs with "default"; kept overridable. In headless SDK use the
# tools in ALLOWED_TOOLS execute without an interactive prompt. Set
# PERMISSION_MODE=acceptEdits if you want edits applied without any gate.
PERMISSION_MODE = os.environ.get("PERMISSION_MODE", "default")

_session_map: dict[str, str] = {}  # external session_id → SDK session_id
_map_lock = asyncio.Lock()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if SESSION_MAP_PATH.exists():
        _session_map.update(json.loads(SESSION_MAP_PATH.read_text()))
    yield


app = FastAPI(title="Chief of Staff Agent (Claude Agent SDK)", lifespan=_lifespan)


@app.middleware("http")
async def _limit_body_size(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "request body too large"})
    return await call_next(request)


class MessageIn(BaseModel):
    prompt: str
    # Optional per-turn output style (e.g. "executive", "technical"), matching
    # the agent's output_style feature. Maps to the SDK settings JSON.
    output_style: str | None = None


def _require_token(authorization: str | None = Header(default=None)) -> None:
    if AUTH_TOKEN is None:
        return
    expected = f"Bearer {AUTH_TOKEN}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="missing or invalid token")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sessions/{session_id}/messages", dependencies=[Depends(_require_token)])
async def post_message(session_id: str, body: MessageIn) -> EventSourceResponse:
    if not SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="invalid session_id")

    sdk_session_id = _session_map.get(session_id)
    options = _build_options(resume=sdk_session_id, output_style=body.output_style)
    return EventSourceResponse(_stream_turn(session_id, body.prompt, options))


def _build_options(*, resume: str | None, output_style: str | None) -> ClaudeAgentOptions:
    """Rebuild the notebook's agent config, plus hosting concerns."""
    return ClaudeAgentOptions(
        system_prompt=COS_SYSTEM_PROMPT,
        allowed_tools=ALLOWED_TOOLS,
        max_buffer_size=MAX_BUFFER_SIZE,
        model=os.environ.get("MODEL", DEFAULT_MODEL),
        permission_mode=PERMISSION_MODE,
        cwd=AGENT_CWD,
        # Load .claude/ and CLAUDE.md from AGENT_CWD — without this the SDK runs
        # in isolation with no slash commands, subagents, or hooks.
        setting_sources=["project", "local"],
        settings=json.dumps({"outputStyle": output_style}) if output_style else None,
        resume=resume,
    )


async def _stream_turn(
    external_id: str, prompt: str, options: ClaudeAgentOptions
) -> AsyncIterator[ServerSentEvent]:
    try:
        async for message in query(prompt=prompt, options=options):
            yield ServerSentEvent(event="message", data=_serialize(message))
            if isinstance(message, ResultMessage) and message.session_id:
                await _remember(external_id, message.session_id)
        yield ServerSentEvent(event="done", data="")
    except Exception as exc:  # noqa: BLE001 — surface any agent error to the stream
        yield ServerSentEvent(event="error", data=json.dumps({"message": str(exc)}))


async def _remember(external_id: str, sdk_session_id: str) -> None:
    async with _map_lock:
        if _session_map.get(external_id) == sdk_session_id:
            return
        _session_map[external_id] = sdk_session_id
        tmp = SESSION_MAP_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_session_map))
        tmp.replace(SESSION_MAP_PATH)


def _serialize(message: Any) -> str:
    payload = asdict(message) if is_dataclass(message) else {"value": message}
    payload["type"] = type(message).__name__
    return json.dumps(payload, default=str)
