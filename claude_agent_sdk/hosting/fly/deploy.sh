#!/usr/bin/env bash
# One-shot Fly.io setup + deploy for the research agent.
#
# Reuses hosting/Dockerfile (build context = claude_agent_sdk/). Run from
# anywhere; the script cd's to claude_agent_sdk/ itself.
#
# Prereqs:
#   - flyctl installed and logged in:  https://fly.io/docs/flyctl/install/ ; fly auth login
#   - ANTHROPIC_API_KEY exported in your shell
#
# Usage:
#   export ANTHROPIC_API_KEY=sk-ant-...
#   ./hosting/fly/deploy.sh [app-name] [region]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_CONTEXT="$(cd "$HERE/../.." && pwd)"   # claude_agent_sdk/
CONFIG="hosting/fly/fly.toml"
DOCKERFILE="hosting/Dockerfile"

APP="${1:-agent-sdk-hosting}"
REGION="${2:-fra}"

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "error: export ANTHROPIC_API_KEY before running" >&2
  exit 2
fi

cd "$BUILD_CONTEXT"

# 1. App (idempotent — ignore "already exists").
fly apps create "$APP" 2>/dev/null || true

# 2. Persistent volume for /data (session transcripts). Skip if one exists.
if ! fly volumes list --app "$APP" 2>/dev/null | grep -q '\bdata\b'; then
  fly volumes create data --app "$APP" --region "$REGION" --size 1 --yes
fi

# 3. Secrets. The Fly URL is public with nothing in front of it, so — exactly
#    like the Modal tier — the server requires this bearer token on /sessions/*.
AUTH_TOKEN="$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-43)"
fly secrets set --app "$APP" \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  AGENT_AUTH_TOKEN="$AUTH_TOKEN"

# 4. Deploy the shared image.
fly deploy --app "$APP" --config "$CONFIG" --dockerfile "$DOCKERFILE" --regions "$REGION"

URL="https://$APP.fly.dev"
cat <<EOF

Deployed.
  url:   $URL
  token: $AUTH_TOKEN

⚠️  The URL is public. The token is the only thing gating it — don't share both.

Try it:
  curl -N -X POST "$URL/sessions/demo-1/messages" \\
    -H "Authorization: Bearer $AUTH_TOKEN" \\
    -H 'Content-Type: application/json' \\
    -d '{"prompt":"What are the latest AI agent trends?"}'
EOF
