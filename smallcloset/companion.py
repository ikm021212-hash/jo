"""Local bridge for user-triggered capture from ordinary Chrome."""
import base64
import hashlib
import json
from pathlib import Path

EXTENSION_DIRECTORY = Path(__file__).resolve().parent.parent / "chrome-extension"
_manifest = json.loads((EXTENSION_DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
_key = base64.b64decode(_manifest["key"])
EXTENSION_ID = "".join(chr(97 + int(char, 16)) for char in hashlib.sha256(_key).hexdigest()[:32])
EXTENSION_ORIGIN = "chrome-extension://" + EXTENSION_ID


def challenge_reason(text):
    lower = text.lower()
    if any(s in lower for s in ["보안 확인 수행 중", "사람인지 확인하십시오", "captcha", "로봇이 아닙니다", "비정상적인 접근", "접근이 제한", "access denied", "too many requests", "verify you are human"]):
        return "CAPTCHA·보안 확인 또는 접근 제한 화면입니다. 자동 수집을 일시정지했습니다. 일반 Chrome에서 직접 확인 후 상품 페이지 가져오기를 사용하세요."
    return None
