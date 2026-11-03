#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
[[ -x venv/bin/python ]] || { echo 'Run ./1-install.sh first.' >&2; exit 1; }
exec venv/bin/python scripts/update_cli.py
