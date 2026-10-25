# OCR test image

`korean-size-table.png` is a generated, test-only image, not a Sinsangmarket screenshot. It contains headers 사이즈 / 가슴단면 / 총장 and rows S / 60 / 67, M / 62 / 69. It was rendered on a white 900 × 360 canvas using Noto Sans CJK Regular at 60px. No font binary is redistributed.

All platforms use these identical pixels to test Korean model loading, UTF-8 output and reading the total-length column's known values. The assertions require 총장, 67 and 69; the output must remain an unverified OCR draft.

The Windows Malgun font variant failed OCR recognition during validation. This is a known OCR limitation, not evidence that arbitrary shop images are reliable. The application does not turn OCR text into verified options automatically; the user must compare the original image's labels, rows, columns and numbers.
