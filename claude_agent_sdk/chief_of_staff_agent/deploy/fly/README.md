# Chief of Staff agent on Fly.io

Deploys the agent from
[`01_The_chief_of_staff_agent.ipynb`](../../01_The_chief_of_staff_agent.ipynb)
as a long-lived [Fly.io](https://fly.io) Machine: a public HTTPS URL,
scale-to-zero, and a persistent volume for session transcripts.

It wraps the agent in the same HTTP + SSE contract as the research-agent hosting
tiers (`../../hosting/`), so the same clients work:

```
GET  /health                           → 200 {"status":"ok"}
POST /sessions/{session_id}/messages   → text/event-stream
     Body: {"prompt":"...", "output_style":"executive" | null}
```

## ⚠️ Security first

This agent runs with **Bash, Write, and Edit enabled** (it runs the bundled
scripts and writes reports). Anyone who can POST to it can run code and write
files *inside the container* — which also holds your `ANTHROPIC_API_KEY`.

- The Fly URL is public, so the server requires a bearer token
  (`AGENT_AUTH_TOKEN`) on `/sessions/*`; `/health` stays open. The deploy script
  generates and sets it for you.
- The token gates access, it does **not** sandbox the agent. Keep the API key
  minimally scoped and treat the machine as disposable.

## Prerequisites

```bash
# Install flyctl: https://fly.io/docs/flyctl/install/
fly auth login
export ANTHROPIC_API_KEY=sk-ant-...
```

## Deploy (scripted)

```bash
cd claude_agent_sdk/chief_of_staff_agent/
./deploy/fly/deploy.sh                 # app: chief-of-staff-agent, region: fra
# or: ./deploy/fly/deploy.sh my-cos-agent ord
```

It prints the `url:` and `token:` at the end.

## Deploy (manual)

All commands run from `chief_of_staff_agent/` — the build context that holds
`.claude/`, `scripts/`, `financial_data/`, and `CLAUDE.md`.

```bash
cd claude_agent_sdk/chief_of_staff_agent/

fly apps create chief-of-staff-agent
fly volumes create data --app chief-of-staff-agent --region fra --size 1
fly secrets set --app chief-of-staff-agent \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  AGENT_AUTH_TOKEN="$(openssl rand -base64 32)"
fly deploy . --config deploy/fly/fly.toml --dockerfile deploy/Dockerfile
```

> The leading `.` pins the build context to `chief_of_staff_agent/`. Without it,
> flyctl treats `deploy/fly/` (the config's directory) as the context and can't
> find the Dockerfile or COPY the project files.

## Talk to it

`session_id` in the path scopes a conversation; reuse it to continue, change it
to start fresh. `output_style` is optional (`executive`, `technical`, …).

```bash
URL=https://chief-of-staff-agent.fly.dev
TOKEN=...   # from the deploy output

# Slash commands from .claude/commands/ work through the prompt:
curl -N -X POST "$URL/sessions/board-q2/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"/budget-impact hiring 3 senior engineers","output_style":"executive"}'

# Follow-up on the same session_id resumes the conversation:
curl -N -X POST "$URL/sessions/board-q2/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Now compare that against delaying the hires by one quarter."}'
```

The response is an SSE stream: `event: message` lines carry serialized SDK
messages, `event: done` closes the turn, `event: error` carries `{"message": …}`.

## What's in the image

The Dockerfile copies the agent's project files so filesystem settings load
(`setting_sources=["project","local"]`, `cwd=/app`):

- `CLAUDE.md` — project instructions
- `.claude/` — slash commands, the `financial-analyst` + `recruiter` subagents,
  hooks, output styles
- `scripts/` — the Python models the agent runs via Bash
- `financial_data/` — the company data it reads

Runtime outputs (`output_reports/`, `audit/`) are **not** baked in; the agent and
its hooks recreate them. They live on the container's ephemeral disk, so they do
**not** persist across restarts — only session transcripts on `/data` do. To
keep generated reports, point the agent at `/data` (e.g. ask it to write under
`/data/reports`) or add another volume.

## Persistence & scaling

`fly.toml` mounts a volume `data` at `/data` (= `CLAUDE_CONFIG_DIR`), so session
transcripts and the session map survive restarts.

> **One machine, one volume.** A Fly volume attaches to a single Machine, so the
> config keeps one auto start/stop Machine (`min_machines_running = 0`). To run
> several Machines, each needs its own volume and they won't share sessions —
> move session state to a
> [`SessionStore`](https://code.claude.com/docs/en/agent-sdk/session-storage)
> backed by an external store.

## Logs, status, teardown

```bash
fly logs   --app chief-of-staff-agent
fly status --app chief-of-staff-agent

fly apps destroy chief-of-staff-agent        # then delete any leftover volume
fly volumes list --app chief-of-staff-agent
```
