#!/usr/bin/env bash
# One-shot Fly.io setup + deploy for the Chief of Staff agent.
#
# Build context = chief_of_staff_agent/, Dockerfile = deploy/Dockerfile. Run from
# anywhere; the script cd's to the agent directory itself.
#
# Prereqs:
#   - flyctl installed and logged in:  https://fly.io/docs/flyctl/install/ ; fly auth login
#   - ANTHROPIC_API_KEY exported in your shell
#
# Usage:
#   export ANTHROPIC_API_KEY=sk-ant-...
#   ./deploy/fly/deploy.sh [app-name] [region]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_CONTEXT="$(cd "$HERE/../.." && pwd)"   # chief_of_staff_agent/
CONFIG="deploy/fly/fly.toml"
DOCKERFILE="deploy/Dockerfile"

APP="${1:-chief-of-staff-agent}"
REGION="${2:-fra}"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "error: export ANTHROPIC_API_KEY before running" >&2
  exit 2
fi

cd "$BUILD_CONTEXT"

# 1. App (idempotent).
fly apps create "$APP" 2>/dev/null || true

# 2. Persistent volume for /data (session transcripts). Skip if one exists.
if ! fly volumes list --app "$APP" 2>/dev/null | grep -q '\bdata\b'; then
  fly volumes create data --app "$APP" --region "$REGION" --size 1 --yes
fi

# 3. Secrets. This agent has Bash/Write/Edit — the public URL MUST be gated.
#    server.py requires this bearer token on /sessions/* when it is set.
AUTH_TOKEN="$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-43)"
fly secrets set --app "$APP" \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  AGENT_AUTH_TOKEN="$AUTH_TOKEN"

# 4. Deploy.
fly deploy --app "$APP" --config "$CONFIG" --dockerfile "$DOCKERFILE" --regions "$REGION"

URL="https://$APP.fly.dev"
cat <<EOF

Deployed.
  url:   $URL
  token: $AUTH_TOKEN

⚠️  This agent can run Bash and write files inside the container. The URL is
    public and the token is the ONLY thing gating it — don't share both, and
    treat the container as disposable.

Try it:
  curl -N -X POST "$URL/sessions/demo-1/messages" \\
    -H "Authorization: Bearer $AUTH_TOKEN" \\
    -H 'Content-Type: application/json' \\
    -d '{"prompt":"/budget-impact hiring 3 senior engineers","output_style":"executive"}'
EOF
