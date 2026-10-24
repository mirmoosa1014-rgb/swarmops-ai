#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if ! .venv/bin/python -c 'import fastapi,uvicorn' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements-web.txt
fi
if [ ! -d frontend/node_modules ]; then (cd frontend && npm ci); fi
(cd frontend && npm run build)
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
printf '\nStarting SwarmOps. Ctrl-C stops this server.\n\n'
exec .venv/bin/python -m swarmops.web "$@"
