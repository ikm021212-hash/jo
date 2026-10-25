"""Isolated native OCR process: bounded by the caller's timeout on all OSes."""
import sys
from PIL import Image


def main():
    from tesserocr import PyTessBaseAPI, PSM
    options = {"lang": "kor+eng", "psm": PSM.SINGLE_BLOCK}
    if len(sys.argv) > 2 and sys.argv[2]:
        options["path"] = sys.argv[2]
    with Image.open(sys.argv[1]) as image, PyTessBaseAPI(**options) as api:
        api.SetImage(image.convert("RGB"))
        text = api.GetUTF8Text()
    # An explicit encoding avoids Korean output being decoded as cp949 on Windows.
    sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
