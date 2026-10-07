#!/bin/sh
# Real integration tests. Everything runs in isolated loopback-only disposable labs.
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$TASK_ROOT"
if [ "$#" -eq 0 ]; then
  set -- 7.0 7.2 7.4
fi
for version in "$@"; do
  case "$version" in 7.0|7.2|7.4) ;; *) echo "Unsupported family: $version" >&2; exit 2 ;; esac
  python3 lab/lab.py start --version "$version"
  python3 tests/integration/zabbix_runtime.py --version "$version"
done
