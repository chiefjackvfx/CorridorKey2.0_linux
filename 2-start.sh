#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
[[ -x venv/bin/python ]] || { echo 'Run ./1-install.sh first.' >&2; exit 1; }
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH PYTHONHOME PYTHONPATH
exec venv/bin/python scripts/launch.py "$@"
