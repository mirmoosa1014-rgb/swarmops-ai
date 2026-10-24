#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if ! .venv/bin/python -c 'import matplotlib' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements-web.lock
fi
exec .venv/bin/python scripts/reproduce.py "$@"
