# ocr2md

**Turn PDFs and images into clean, structured Markdown — entirely on your machine.**

[English](README.md) · [Tiếng Việt](README.vi.md)

[![Release](https://img.shields.io/github/v/release/imxuanmanh/ocr2md?sort=semver)](https://github.com/imxuanmanh/ocr2md/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20(Docker)-lightgrey.svg)](#install)

ocr2md renders PDF pages with PyMuPDF, runs Tesseract over them, and rebuilds the
text into readable Markdown: headings, paragraphs, bullet lists, running
headers removed, lines and pages joined correctly. It ships as a single-file
Windows executable with a local web UI, a CLI, and an optional AI proofreading
step. The pipeline is local-first — nothing leaves your machine unless you
explicitly enable an AI provider.

```
PDF ──PyMuPDF render──▶ images ──▶ Tesseract (TSV) ──▶ lines + coordinates
    ──rule-based layout──▶ Markdown ──(optional AI)──▶ Markdown
```

## Contents

- [Features](#features)
- [Install](#install)
- [Usage](#usage)
- [Web UI](#web-ui)
- [Optional AI proofreading](#optional-ai-proofreading)
- [How it works](#how-it-works)
- [Configuration](#configuration)
- [Build from source](#build-from-source)
- [Testing](#testing)
- [Project layout](#project-layout)
- [License](#license)

## Features

- **PDF and image input.** PNG, JPEG, TIFF, BMP, WebP and GIF; multi-frame
  TIFF/GIF/WebP files are processed frame by frame.
- **Layout-aware cleanup.** Repeated running headers and page numbers are
  dropped, broken lines and cross-page paragraphs are merged, heading levels
  are inferred from font size, lists are recognized, Unicode is normalized.
- **Figure extraction.** Images are detected heuristically, cropped to PNG,
  and linked from the Markdown at the right reading position with captions as
  `alt` text.
- **Two interfaces, one engine.** A local web UI for non-technical users and a
  scriptable CLI for automation.
- **Optional AI proofreading.** DeepSeek by default; OpenAI-compatible
  endpoints (OpenAI, Ollama, custom) and Anthropic are supported. Guardrails
  reject any edit that changes numbers, links or page anchors.
- **No Python required on Windows.** The release EXE bundles the runtime; the
  OCR engine is downloaded once, SHA-256 verified, into your user data folder.

## Install

### Windows (recommended)

Download [`OCR2MD.exe`](https://github.com/imxuanmanh/ocr2md/releases/latest/download/OCR2MD.exe)
from the [latest release](https://github.com/imxuanmanh/ocr2md/releases/latest)
and run it. Requirements: Windows 10/11 x64, no Python installation.

On first launch the web UI opens at <http://127.0.0.1:8765>. Before the first
OCR job, open **⚙ Settings → Download Tesseract**. The engine and the `eng`,
`vie`, `osd` language data are installed into `%APPDATA%\ocr2md`; you can also
point ocr2md at an existing `tesseract.exe`, or supply a custom HTTPS URL with
its SHA-256. The EXE is not code-signed, so SmartScreen may warn on first run:
**More info → Run anyway**.

The same executable exposes the CLI:

```powershell
.\OCR2MD.exe doctor
.\OCR2MD.exe convert document.pdf --lang vie+eng --extract-images
```

Running the EXE with no arguments starts the web UI, exactly like double-clicking it.

### pip / from source

Python 3.10 or newer. On Windows you can install the prebuilt wheel; on
Linux/macOS install from source and use the system Tesseract.

```powershell
git clone https://github.com/imxuanmanh/ocr2md.git
cd ocr2md
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -e .
# Only for the Claude provider:
pip install -e ".[anthropic]"
```

Prebuilt Windows wheel:

```powershell
pip install https://github.com/imxuanmanh/ocr2md/releases/download/v0.2.1/ocr2md-0.2.1-py3-none-win_amd64.whl
```

On Linux/macOS, install Tesseract from your package manager (for example
`apt install tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng`) or use Docker
below. Windows users who install from source can either install Tesseract
system-wide or let the web UI download it.

### Docker

The image already contains Tesseract with English and Vietnamese data.

```powershell
docker compose up --build     # build on first run, then open http://localhost:8765
docker compose up -d          # run in the background
```

- Settings and the optional API key live in the `ocr2md-data` volume
  (`/data/config.json`). Set `DEEPSEEK_API_KEY=...` in `.env` next to
  `docker-compose.yml` to keep the key in the environment instead.
- The port is published to `127.0.0.1` only; the web UI has no login. Do not
  change it to `8765:8765` unless you put authentication in front of it.
- Run CLI jobs inside the container with the input mounted under `./work`:

  ```powershell
  docker compose run --rm ocr2md convert /work/document.pdf --lang vie+eng --extract-images
  ```

  Results are written back to `./work`. The container runs as uid 1000; on
  Linux, make sure `./work` is writable by that user.
- To use Ollama on the host from inside the container, point the base URL at
  `http://host.docker.internal:11434/v1`; on Linux add
  `extra_hosts: ["host.docker.internal:host-gateway"]` to the service.
- To use `tessdata_best`, mount your tessdata folder into the container and
  enter that path in **⚙ Settings → tessdata folder**.
- To enable the Claude provider, uncomment `pip install ".[anthropic]"` in the
  `Dockerfile`.

## Usage

```powershell
# Basic conversion: writes document.md next to the input file
ocr2md convert document.pdf
python -m ocr2md convert document.pdf      # equivalent

# Render options, page range and page markers
ocr2md convert document.pdf -o out.md --lang vie+eng --dpi 300 --pages 1-10 --page-markers

# Images work the same way
ocr2md convert scan.jpg                    # PNG, JPEG, TIFF, BMP, WebP, GIF

# Extract figures to document_images/ and insert links into the Markdown
ocr2md convert document.pdf --extract-images
ocr2md convert document.pdf --images-dir D:\images\document

# Local web UI
ocr2md serve                               # http://127.0.0.1:8765
ocr2md serve --port 9000 --no-browser

# Check Tesseract, languages and where AI data would be sent
ocr2md doctor
```

Common `convert` options:

| Option | Description |
|---|---|
| `-o, --output` | Output `.md` path (default: next to the input) |
| `--lang` | Tesseract languages, e.g. `vie+eng`; `auto` prefers `vie+eng`, else `eng` |
| `--dpi` | Render resolution for PDF pages (default `300`) |
| `--pages` | Only these pages, e.g. `1-3,5` |
| `--page-markers` | Insert `<!-- page N -->` before each page |
| `--extract-images`, `--images-dir` | Extract figures and where to store them |
| `--psm`, `--workers` | Tesseract page segmentation mode and OCR parallelism |
| `--tesseract`, `--tessdata` | Use a specific Tesseract binary / language data |
| `--ai`, `--keep-raw` | Enable AI proofreading, keep the pre-AI copy as `*.raw.md` |

## Web UI

The local UI is designed to be usable before Tesseract is installed:

- **Settings** with a one-click Tesseract download (progress by stage,
  SHA-256 verification), custom HTTPS URL + checksum, or an existing
  `tesseract.exe` path. Settings persist in the user data folder.
- Drag-and-drop PDF/image upload, language/DPI/page selection, live progress,
  cancel, preview and download of the resulting Markdown and image bundle.
- AI provider configuration with a connection test.
- Binds to `127.0.0.1` by default, rejects foreign `Host` headers
  (DNS-rebinding protection) and cross-origin requests. To use another
  hostname on your LAN, pass `--allowed-host name` (or `*` behind a reverse
  proxy).

## Optional AI proofreading

AI correction is **off by default**. When enabled, Markdown is split into
chunks of at most 4,000 characters and sent to the selected provider.

| Provider | Default endpoint / model | Credentials |
|---|---|---|
| `deepseek` (default) | `https://api.deepseek.com`, `deepseek-flash` | `DEEPSEEK_API_KEY` |
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` + `--ai-model` |
| `ollama` | `http://localhost:11434/v1` | `--ai-model` |
| `custom` | your URL | `--ai-base-url` (+ `--ai-key-env` if needed) |
| `anthropic` | model `claude-sonnet-5-5` | `ANTHROPIC_API_KEY` + `anthropic` extra |

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
ocr2md convert document.pdf --ai --keep-raw

ocr2md convert a.pdf --ai --ai-provider ollama --ai-model qwen2.5:14b
ocr2md convert a.pdf --ai --ai-provider custom --ai-base-url http://localhost:8000/v1 --ai-model my-model
```

Provider, model and base URL can also be set with `OCR2MD_AI_PROVIDER`,
`OCR2MD_AI_MODEL` and `OCR2MD_AI_BASE_URL` (legacy `PDF2MD_*` variables are
still read). For DeepSeek, requests send `thinking: disabled` to avoid
unnecessary token usage.

**Guardrails.** A chunk is discarded and the original kept (with a warning) if
the response changes any number, changes an image link or page anchor, differs
in length by more than ±25%, or is truncated. As a consequence, AI is not
allowed to "fix" OCR digit errors such as `1O0` → `100` — that is intentional.
Network errors are retried on 429/5xx; invalid keys or exhausted credit stop
the job immediately.

**Privacy.** `doctor` prints the destination before any AI call. Using
`ollama` or a `custom` URL pointed at localhost keeps everything on your
machine. With DeepSeek/OpenAI/Anthropic, the OCR text is sent to that provider.

## How it works

### Markdown assembly

The formatter behaves conservatively:

- **Does:** remove repeated running headers and page numbers, merge lines into
  paragraphs, join paragraphs split across pages, infer headings from font
  size, recognize bullet lists, normalize Unicode (NFC) and spacing.
- **Does not:** reconstruct tables, bold/italic, multi-column layouts, or fix
  OCR recognition errors.

Headings are only detected when they are visibly larger than body text
(≥ 1.25×). A heading in the same size but bold becomes a normal paragraph.
For Vietnamese, hyphenated line breaks are deliberately **not** rejoined
(Vietnamese rarely hyphenates, and `Bắc-Nam` is a real compound); other
languages are de-hyphenated.

### Figure extraction

Detection is heuristic, with no ML model: regions containing "ink" that
Tesseract did not recognize as text are grouped into blocks, and blocks that
look like tables or paragraphs are filtered out. Each figure is cropped from
the color render, saved as PNG, and inserted at its reading position; `alt`
text comes from a nearby caption (`Figure 3: ...`, `Hình 3: ...`). Text inside
a figure region is dropped from the body because it is already in the image.

Known limitations: very faint or very small figures (below ~12% of page width
or 5% of page height) can be missed, sparsely ruled tables can be mistaken for
figures, and figures heavily overlaid with text are treated as text. A quick
look at the output image folder is recommended.

## Configuration

When the same value is set in several places, precedence is:

1. command-line flag
2. `TESSERACT_CMD` environment variable (Tesseract only)
3. saved ⚙ Settings
4. other environment variables
5. built-in default

A key saved in ⚙ Settings wins over the environment and is only used for the
provider/base URL recorded with it. The configuration file lives in
`%APPDATA%\ocr2md\config.json` on Windows (or `$OCR2MD_CONFIG` /
`~/.config/ocr2md/config.json` elsewhere). A corrupt file is set aside rather
than crashing the app.

## Build from source

Windows single-file EXE (PyInstaller, includes the 7-Zip extractor used by the
Tesseract installer):

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e . pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
# result: work\dist-final\OCR2MD.exe
```

Docker image:

```powershell
docker compose build
```

## Testing

The test suite uses only the standard library and does not require network
access. Tests that need a real Tesseract installation are skipped when the
engine is unavailable.

```powershell
python -m unittest discover -s tests
```

## Project layout

```
ocr2md/
  cli.py         command-line entry point (convert / serve / doctor)
  web.py         Flask app and embedded UI
  pipeline.py    shared PDF/image -> OCR -> Markdown flow
  ocr.py         Tesseract discovery and TSV processing
  markdown.py    layout rules: headings, paragraphs, lists, page joins
  figures.py     heuristic figure detection and cropping
  inputs.py      input format detection
  ai.py          provider config, chunking and guardrails
  installer.py   verified Tesseract download/extraction (Windows)
  config.py      persisted settings
tests/           unittest suite
```

## License

ocr2md is released under the [MIT License](LICENSE). Third-party components,
including the bundled 7-Zip extractor, PyMuPDF (AGPL-3.0), and the Tesseract
build downloaded at runtime, are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
