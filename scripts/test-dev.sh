#!/usr/bin/env bash
set -euo pipefail
NE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
NE_VENV=${NE_VENV:-"$NE_ROOT/.venv"}
NE_PYTHON=${NE_PYTHON:-"$NE_VENV/bin/python"}
NE_PHP_IMAGE=php@sha256:af246ab279bb71c614ab4ceee428a6da72f68b1d47858bccb9ca7cbf6b27363d
cd "$NE_ROOT"
"$NE_PYTHON" -m pytest
"$NE_PYTHON" templates/generate_lab.py --check
node --test tests/browser/widgets.test.cjs
if command -v php >/dev/null 2>&1; then
  php tests/php/run.php
else
  docker run --rm --user 0 -v "$NE_ROOT:/work:ro" -w /work "$NE_PHP_IMAGE" php tests/php/run.php
fi
printf 'Development checks passed. Actual Zabbix integration and browser suites are separate commands.\n'
