#!/bin/bash
# Launch pyterm in its virtual environment.
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
    python3 -m venv .venv
    ./.venv/bin/pip install --quiet -r requirements.txt
fi
exec ./.venv/bin/python pyterm.py
