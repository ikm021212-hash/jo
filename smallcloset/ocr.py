import hashlib
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 20_000_000


def read_image(content: bytes, directory: Path):
    if len(content) > 10_000_000:
        raise ValueError("이미지는 10MB 이하로 올려주세요.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            if image.width * image.height > 20_000_000:
                raise ValueError("이미지 크기가 너무 큽니다.")
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
    executable = shutil.which("tesseract")
    if not executable:
        return {"evidence": evidence_id, "text": "", "warning": "Tesseract가 없어 OCR을 실행하지 못했습니다. 원본을 직접 확인해 주세요."}
    tessdata = os.environ.get("SM_TESSDATA")
    args = [executable, str(path), "stdout", "-l", "kor+eng", "--psm", "6"]
    if tessdata:
        args += ["--tessdata-dir", tessdata]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=45, check=False)
        if result.returncode:
            return {"evidence": evidence_id, "text": "", "warning": "한국어 OCR 언어팩 또는 Tesseract 실행 오류. 설치 절차를 확인하세요."}
        return {"evidence": evidence_id, "text": result.stdout[:20000],
                "warning": "OCR 초안입니다. 총장 열·사이즈 행·단위를 원본과 직접 대조해야 합니다. 자동 통과시키지 않습니다."}
    except subprocess.TimeoutExpired:
        return {"evidence": evidence_id, "text": "", "warning": "OCR 처리 시간 초과. 원본은 보관했습니다."}
