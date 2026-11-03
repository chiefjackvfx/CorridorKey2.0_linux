#!/usr/bin/env bash
# Standalone bootstrap or repair an existing checkout.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ -f "$script_dir/runtime_setup.py" ]]; then exec bash "$script_dir/1-install.sh" "$@"; fi
target=${1:-"$script_dir/CorridorKey2.0"}
if [[ ! -e "$target" ]] || [[ -d "$target" && -z $(ls -A -- "$target") ]]; then
    git clone --branch master https://github.com/chiefjackvfx/CorridorKey2.0.git "$target"
elif [[ ! -e "$target/.git" || ! -f "$target/runtime_setup.py" ]]; then
    echo 'Target must be a new folder or an existing CK2 checkout.' >&2; exit 1
fi
exec bash "$target/1-install.sh"
