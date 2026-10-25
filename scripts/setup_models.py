"""Verified local OCR assets, shared by Windows and Linux installation."""
import argparse
import hashlib
import io
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def fetch_verified(url, destination, expected_sha256):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected_sha256:
        return False
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            with urllib.request.urlopen(url, timeout=90) as response:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected_sha256:
            raise ValueError("OCR model checksum mismatch; verification must not be disabled.")
        temporary.replace(destination)
        return True
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def install_models(directory):
    manifest = json.loads((ROOT / "scripts/setup-assets.json").read_text(encoding="utf-8"))
    for model in manifest["models"]:
        fetch_verified(model["url"], Path(directory) / model["name"], model["sha256"])


def check_ocr():
    from PIL import Image, ImageDraw, ImageFont
    from smallcloset.ocr import read_image
    image = Image.new("RGB", (350, 150), "white")
    ImageDraw.Draw(image).text((30, 25), "67 cm", fill="black", font=ImageFont.load_default(size=65))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    with tempfile.TemporaryDirectory(prefix="smallcloset-install-check-") as directory:
        result = read_image(stream.getvalue(), Path(directory))
        if "67" not in result["text"]:
            raise RuntimeError("Local OCR self-check failed. Reinstall; do not approve unverified OCR results.")
    print("Local OCR readiness check: passed (generated test image, no real products).")


def main():
    from smallcloset.runtime import data_dir
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-ocr", action="store_true")
    args = parser.parse_args()
    directory = Path(os.environ.get("SM_TESSDATA") or data_dir() / "tessdata")
    os.environ["SM_TESSDATA"] = str(directory)
    install_models(directory)
    if args.check_ocr:
        check_ocr()


if __name__ == "__main__":
    main()
