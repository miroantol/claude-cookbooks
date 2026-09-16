#!/usr/bin/env bash
# Start the Chief of Staff FastAPI server on :8000.
set -euo pipefail
exec uvicorn deploy.server:app --host 0.0.0.0 --port 8000
