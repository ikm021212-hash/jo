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
mkdir -p "$SM_DATA_DIR/tessdata"
# TLS + pinned SHA256. Never disable TLS or alter these hashes to fix a failure.
fetch_model() {
  local lang="$1" expected="$2" source="${3:-tessdata_fast}" target="$SM_DATA_DIR/tessdata/$1.traineddata"
  if [ -f "$target" ] && .venv/bin/python - "$target" "$expected" <<'PY'
import hashlib,sys
sys.exit(0 if hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()==sys.argv[2] else 1)
PY
  then return; fi
  curl --fail --location --retry 1 --max-time 120 "https://raw.githubusercontent.com/tesseract-ocr/$source/main/$lang.traineddata" -o "$target.tmp"
  .venv/bin/python - "$target.tmp" "$expected" <<'PY'
import hashlib,sys
if hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()!=sys.argv[2]:
    raise SystemExit('OCR model checksum mismatch; stop and investigate official upstream release.')
PY
  mv "$target.tmp" "$target"
}
fetch_model kor f888d4038348a0c3d25151e7f452bda0d74ca275b18cab146798bcbb94084fff tessdata_best
# English model hash is filled from the TLS-verified official tessdata artifact.
fetch_model eng 7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2
SM_TESSDATA="$SM_DATA_DIR/tessdata" SM_BROWSER_TESTS=1 .venv/bin/python scripts/test.py
echo '설치·테스트 완료. bash scripts/run.sh 로 실행하세요.'
