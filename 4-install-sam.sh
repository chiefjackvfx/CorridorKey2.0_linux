#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x venv/bin/python ]]; then
    echo 'Run ./1-install.sh first.' >&2
    exit 1
fi
venv/bin/python -c 'import sys; assert sys.version_info[:2] >= (3,12), "SAM 3.1 requires Python 3.12 or newer"'
sam_revision=f1647e8d0c1d280991f4d1b7d974c2704537fe66
if [[ ! -e third_party/sam3/.git ]]; then
    mkdir -p third_party
    git clone https://github.com/facebookresearch/sam3.git third_party/sam3
    git -C third_party/sam3 checkout "$sam_revision"
fi
sam_installed_revision=$(git -C third_party/sam3 rev-parse HEAD)
if [[ "$sam_installed_revision" != "$sam_revision" ]]; then
    echo "Expected SAM revision $sam_revision; found $sam_installed_revision. Leaving existing source untouched." >&2
    exit 1
fi
venv/bin/python -m pip install -e ./third_party/sam3 pycocotools psutil
venv/bin/python -m pip check
printf '%s\n' 'SAM 3.1 code installed. Select sam3.1_multiplex.pt in Alpha Hint → Create / Edit hint.'
