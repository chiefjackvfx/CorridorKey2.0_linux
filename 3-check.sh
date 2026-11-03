#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x venv/bin/python ]]; then echo 'Run ./1-install.sh first.' >&2; exit 1; fi
exec venv/bin/python scripts/check_linux.py "$@"
