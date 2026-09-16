# Tier 2b — Fly.io

Runs the **same** `hosting/Dockerfile` image on [Fly.io](https://fly.io) as a
long-lived Machine. You get a public HTTPS URL, scale-to-zero, and a persistent
volume for session transcripts — no Kubernetes to operate.

Like the Modal tier, the Fly URL is public with nothing in front of it, so the
server requires a bearer token (`AGENT_AUTH_TOKEN`) on `/sessions/*`. `/health`
stays open for Fly's liveness proxy.

## Prerequisites

```bash
# Install flyctl: https://fly.io/docs/flyctl/install/
fly auth login
export ANTHROPIC_API_KEY=sk-ant-...
```

## Deploy (scripted)

The helper does app + volume + secrets + deploy in one go:

```bash
cd claude_agent_sdk/
./hosting/fly/deploy.sh                 # app: agent-sdk-hosting, region: fra
# or: ./hosting/fly/deploy.sh my-app-name ord
```

It prints the `url:` and the `token:` at the end.

## Deploy (manual)

Same steps, if you'd rather run them yourself. All commands run from
`claude_agent_sdk/` — the build context that holds `research_agent/` and
`utils/` next to `hosting/`.

```bash
cd claude_agent_sdk/

# 1. Create the app. Match the name to `app =` in hosting/fly/fly.toml
#    (or edit the toml to match).
fly apps create agent-sdk-hosting

# 2. Persistent volume for /data (session transcripts). Same region as the app.
fly volumes create data --app agent-sdk-hosting --region fra --size 1

# 3. Secrets. The public URL is gated only by AGENT_AUTH_TOKEN.
fly secrets set --app agent-sdk-hosting \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  AGENT_AUTH_TOKEN="$(openssl rand -base64 32)"

# 4. Deploy the shared image.
fly deploy --config hosting/fly/fly.toml --dockerfile hosting/Dockerfile
```

## Talk to it

```bash
URL=https://agent-sdk-hosting.fly.dev
TOKEN=...   # from the deploy output / `fly secrets` you set

curl -N -X POST "$URL/sessions/demo-1/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"What are the latest AI agent trends?"}'
```

## Persistence

`fly.toml` mounts a volume named `data` at `/data` (= `CLAUDE_CONFIG_DIR`), so
session transcripts and the external→SDK session map survive restarts — the
same trick as every other tier.

> **One machine, one volume.** A Fly volume attaches to a single Machine, so the
> config keeps `min_machines_running = 0` with auto start/stop (one Machine that
> sleeps when idle). To run **several** Machines behind the load balancer, each
> needs its own volume and they won't share sessions — move session state to a
> [`SessionStore`](https://code.claude.com/docs/en/agent-sdk/session-storage)
> backed by an external store (what the Kubernetes tier does with Redis).

## Scale to zero

`auto_stop_machines = "stop"` + `min_machines_running = 0` means the Machine
sleeps when idle and Fly's proxy wakes it on the next request (a few seconds of
cold start). Set `min_machines_running = 1` if you want it always warm.

## Logs & status

```bash
fly logs --app agent-sdk-hosting
fly status --app agent-sdk-hosting
```

## Teardown

```bash
fly apps destroy agent-sdk-hosting        # removes the app + its Machines
fly volumes list --app agent-sdk-hosting  # then destroy any leftover volume
```

Destroying the app stops billing for the Machine; delete the volume too so
you're not billed for idle storage.
