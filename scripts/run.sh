#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export SM_DATA_DIR="${SM_DATA_DIR:-${HOME}/.local/share/smallcloset}"
export SM_TESSDATA="$SM_DATA_DIR/tessdata"
export PLAYWRIGHT_BROWSERS_PATH="$SM_DATA_DIR/browsers"
if [ ! -x .venv/bin/python ]; then
  echo '먼저 bash scripts/install.sh 를 실행하세요.'
  exit 1
fi
exec .venv/bin/python -m smallcloset.app
