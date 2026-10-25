import hashlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from PIL import Image, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 20_000_000


def ocr_available():
    return importlib.util.find_spec("tesserocr") is not None or shutil.which("tesseract") is not None


def save_image(content: bytes, directory: Path):
    if len(content) > 10_000_000:
        raise ValueError("이미지는 10MB 이하로 올려주세요.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("이미지 크기가 너무 큽니다.")
            image.load()
            image = image.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("지원하지 않거나 손상된 이미지입니다.")
    evidence_dir = directory / "evidence"
    evidence_dir.mkdir(exist_ok=True, mode=0o700)
    # Re-encode image: no EXIF or original filenames/paths in outputs.
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    evidence_id = hashlib.sha256(buffer.getvalue()).hexdigest() + ".png"
    path = evidence_dir / evidence_id
    path.write_bytes(buffer.getvalue())
    path.chmod(0o600)
    return evidence_id, path


def read_image(content: bytes, directory: Path):
    evidence_id, path = save_image(content, directory)
    tessdata = os.environ.get("SM_TESSDATA")
    if importlib.util.find_spec("tesserocr") is not None:
        args = [sys.executable, "-m", "smallcloset.ocr_worker", str(path), tessdata or ""]
    else:
        executable = shutil.which("tesseract")
        if not executable:
            return {"evidence": evidence_id, "text": "", "warning": "OCR 엔진이 없습니다. 윈도우는 INSTALL-WINDOWS.bat를 실행하세요. 원본은 직접 확인할 수 있습니다."}
        args = [executable, str(path), "stdout", "-l", "kor+eng", "--psm", "6"]
        if tessdata:
            args += ["--tessdata-dir", tessdata]
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=45, check=False, cwd=Path(__file__).resolve().parent.parent,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        if result.returncode:
            return {"evidence": evidence_id, "text": "", "warning": "한국어 OCR 언어팩 또는 Tesseract 실행 오류. 설치 절차를 확인하세요."}
        return {"evidence": evidence_id, "text": result.stdout[:20000],
                "warning": "OCR 초안입니다. 총장 열·사이즈 행·단위를 원본과 직접 대조해야 합니다. 자동 통과시키지 않습니다."}
    except subprocess.TimeoutExpired:
        return {"evidence": evidence_id, "text": "", "warning": "OCR 처리 시간 초과. 원본은 보관했습니다."}
