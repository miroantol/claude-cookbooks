# syntax=docker/dockerfile:1
#
# Chief of Staff agent — container image.
#
# Build context is chief_of_staff_agent/ (the parent of deploy/), because the
# image needs the agent's project files — .claude/, scripts/, financial_data/,
# CLAUDE.md — copied in alongside the server.
#
#   cd claude_agent_sdk/chief_of_staff_agent/
#   docker build -f deploy/Dockerfile -t chief-of-staff-agent .

FROM python:3.11-slim

# The Agent SDK shells out to the Claude Code CLI. Install Node + the CLI so
# query() has a runtime to drive.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @anthropic-ai/claude-code@2.1.140 \
 && apt-get purge -y curl \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Stable cwd. The agent runs with cwd=/app and setting_sources=["project",
# "local"], so .claude/ and CLAUDE.md must sit here. Session transcripts are
# stored under $CLAUDE_CONFIG_DIR/projects/<encoded-cwd>/, so a stable cwd is
# also what lets resume= find prior sessions across restarts.
WORKDIR /app

COPY deploy/requirements.txt ./deploy/requirements.txt
RUN pip install --no-cache-dir -r deploy/requirements.txt

# The agent's project files. These ARE the agent: filesystem settings, custom
# scripts, subagent/command/hook/output-style definitions, and company data.
COPY CLAUDE.md ./CLAUDE.md
COPY .claude/ ./.claude/
COPY scripts/ ./scripts/
COPY financial_data/ ./financial_data/

# The hosting layer: server + entrypoint. `deploy` must be an importable package
# (uvicorn deploy.server:app), and the hooks referenced by settings.local.json
# must stay executable.
COPY deploy/server.py deploy/entrypoint.sh ./deploy/
RUN chmod +x deploy/entrypoint.sh .claude/hooks/*.py \
 && touch deploy/__init__.py

# Redirect session storage to /data — mount something persistent there (Fly
# volume, compose bind mount) to keep transcripts across restarts.
ENV CLAUDE_CONFIG_DIR=/data
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

ENTRYPOINT ["./deploy/entrypoint.sh"]
