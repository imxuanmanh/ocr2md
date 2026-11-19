# Third-party notices

ocr2md is MIT-licensed. It bundles or depends on the following third-party
components, each under its own license.

## Bundled in the Windows build

| Component | Version | License | Notes |
|---|---|---|---|
| [7-Zip](https://www.7-zip.org/) (`7z.exe`, `7z.dll`) | bundled copy | GNU LGPL 2.1+ (with unRAR restriction on part of `7z.dll`), BSD 2-clause / 3-clause for some code | Used only to extract the Tesseract installer. Full text: [`ocr2md/vendor/7zip/License.txt`](ocr2md/vendor/7zip/License.txt). Source: https://www.7-zip.org/ |
| Python runtime and standard library | CPython 3.10 | PSF License | Embedded by PyInstaller in `OCR2MD.exe` |
| [PyMuPDF](https://pymupdf.readthedocs.io/) | >= 1.24 | GNU AGPL 3.0 | PDF rendering. Because the distributed EXE includes PyMuPDF, AGPL 3.0 applies to that distribution; the corresponding source is this public repository. |
| [Flask](https://flask.palletsprojects.com/) | >= 3.0 | BSD 3-clause | Local web UI |
| [NumPy](https://numpy.org/) | >= 1.26 | BSD 3-clause | Figure detection |
| [Pillow](https://python-pillow.org/) | >= 10.0 | HPND | Image handling |
| [PyInstaller](https://pyinstaller.org/) | build only | GPL 2.0 with bootloader exception | Produces the single-file EXE |

## Downloaded at runtime (not bundled)

| Component | License | Notes |
|---|---|---|
| [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) 5.5.3 Windows build | Apache 2.0 | Downloaded into the user data directory on first use, SHA-256 verified |
| [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) `eng`, `vie`, `osd` | Apache 2.0 | Language models, downloaded together with Tesseract |

## Optional Python extra

| Component | License | Notes |
|---|---|---|
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) | MIT | Only installed with `pip install ".[anthropic]"`, not bundled in the EXE |
