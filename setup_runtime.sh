#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'Supported: Linux x86-64'; exit 1; }
project=$PWD
mkdir -p .runtime/tools/bin .runtime/downloads
export UV_UNMANAGED_INSTALL="$project/.runtime/tools/bin" UV_NO_MODIFY_PATH=1 UV_NO_CONFIG=1
export UV_PYTHON_INSTALL_DIR="$project/.runtime/tools/python" UV_CACHE_DIR="$project/.runtime/downloads/uv"
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV
uv="$project/.runtime/tools/bin/uv"
if [[ ! -x "$uv" ]] || [[ $("$uv" --version) != "uv 0.12.21 "* ]]; then
    if command -v curl >/dev/null; then
        curl -fLsS https://astral.sh/uv/0.12.21/install.sh -o .runtime/downloads/install-uv.sh
    elif command -v wget >/dev/null; then
        wget -q https://astral.sh/uv/0.12.21/install.sh -O .runtime/downloads/install-uv.sh
    else echo 'Install curl or wget, then retry.' >&2; exit 1; fi
    sh .runtime/downloads/install-uv.sh
fi
"$uv" python install 3.12 --no-bin --no-registry
runtime_python=$("$uv" python find --managed-python --no-project 3.12)
exec "$runtime_python" runtime_setup.py --uv "$uv" --python "$runtime_python" "$@"
