#!/usr/bin/env bash
set -euo pipefail
NE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
NE_PYTHON=${NE_PYTHON:-python3}
NE_VENV=${NE_VENV:-"$NE_ROOT/.venv"}
"$NE_PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer is required"'
if [[ ! -x "$NE_VENV/bin/python" ]]; then
  "$NE_PYTHON" -m venv "$NE_VENV"
fi
"$NE_VENV/bin/python" -m pip install --disable-pip-version-check -r "$NE_ROOT/requirements-dev.txt"
printf 'Development Python: %s\n' "$NE_VENV/bin/python"
