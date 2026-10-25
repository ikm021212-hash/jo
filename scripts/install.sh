#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export SM_DATA_DIR="${SM_DATA_DIR:-${HOME}/.local/share/smallcloset}"
export PLAYWRIGHT_BROWSERS_PATH="${SM_DATA_DIR}/browsers"
mkdir -p "$SM_DATA_DIR"
chmod 700 "$SM_DATA_DIR"
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-dev.txt
if ! command -v chromium >/dev/null && ! command -v google-chrome >/dev/null && [ -z "${SM_CHROMIUM:-}" ]; then
  .venv/bin/python -m playwright install chromium
fi
if ! command -v tesseract >/dev/null; then
  echo 'Tesseract가 필요합니다. Linux: sudo apt install tesseract-ocr / macOS: brew install tesseract'
  exit 1
fi
SM_TESSDATA="$SM_DATA_DIR/tessdata" .venv/bin/python scripts/setup_models.py --check-ocr
SM_TESSDATA="$SM_DATA_DIR/tessdata" SM_BROWSER_TESTS=1 .venv/bin/python scripts/test.py
echo '설치·테스트 완료. bash scripts/run.sh 로 실행하세요.'
