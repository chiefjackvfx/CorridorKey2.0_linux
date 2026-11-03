#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ "$(uname -s)" != Linux ]]; then
    echo 'This installer targets Linux.' >&2; exit 1
fi
case "${1:-}" in
    ''|--skip-weights) ;;
    *) echo 'Usage: ./1-install.sh [--skip-weights]'; exit 2 ;;
esac
if [[ ! -x venv/bin/python ]]; then
    runtime="${CK_PYTHON:-}"
    if [[ -z "$runtime" ]]; then
        for candidate in python3.12 python3.11; do
            if command -v "$candidate" >/dev/null; then runtime="$candidate"; break; fi
        done
    fi
    if [[ -z "$runtime" ]]; then
        echo 'Install Python 3.11 or 3.12 with venv support, then retry.' >&2; exit 1
    fi
    "$runtime" -m venv venv
fi
venv/bin/python -c 'import sys; assert (3,11) <= sys.version_info[:2] <= (3,12), "Use Python 3.11 or 3.12 (NumPy <2 is required)"'
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128
venv/bin/python -m pip install -r requirements-linux.txt
venv/bin/python -m pip check
venv/bin/python scripts/create_linux_launcher.py
if [[ "${1:-}" != --skip-weights ]]; then
    venv/bin/python scripts/download_weights.py
fi
echo 'Installed. Launch with ./2-start.sh; diagnose with ./3-check.sh.'
if ! venv/bin/python scripts/check_linux.py; then
    echo 'Software installed, but inference prerequisites above still need attention.' >&2
    exit 1
fi
