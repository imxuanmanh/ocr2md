# ocr2md

**Chuyển PDF và ảnh thành Markdown sạch, có cấu trúc — hoàn toàn trên máy của bạn.**

[English](README.md) · [Tiếng Việt](README.vi.md)

[![Release](https://img.shields.io/github/v/release/imxuanmanh/ocr2md?sort=semver)](https://github.com/imxuanmanh/ocr2md/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20(Docker)-lightgrey.svg)](#cài-đặt)

ocr2md render từng trang PDF bằng PyMuPDF, chạy Tesseract trên ảnh rồi dựng lại
văn bản thành Markdown dễ đọc: heading, đoạn văn, danh sách; bỏ header/footer
lặp lại; nối dòng và nối đoạn qua trang đúng cách. Sản phẩm có bản EXE Windows
một file với web UI cục bộ, một CLI, và bước hiệu đính bằng AI tùy chọn. Toàn bộ
pipeline chạy cục bộ — không có dữ liệu nào rời máy trừ khi bạn chủ động bật
nhà cung cấp AI.

```
PDF ──PyMuPDF render──▶ ảnh ──▶ Tesseract (TSV) ──▶ dòng chữ + toạ độ
    ──quy tắc bố cục──▶ Markdown ──(AI tùy chọn)──▶ Markdown
```

## Mục lục

- [Tính năng](#tính-năng)
- [Cài đặt](#cài-đặt)
- [Sử dụng](#sử-dụng)
- [Web UI](#web-ui)
- [Hiệu đính bằng AI (tùy chọn)](#hiệu-đính-bằng-ai-tùy-chọn)
- [Cách hoạt động](#cách-hoạt-động)
- [Cấu hình](#cấu-hình)
- [Tự build từ mã nguồn](#tự-build-từ-mã-nguồn)
- [Kiểm thử](#kiểm-thử)
- [Cấu trúc project](#cấu-trúc-project)
- [Giấy phép](#giấy-phép)

## Tính năng

- **Nhận PDF và ảnh.** PNG, JPEG, TIFF, BMP, WebP và GIF; file TIFF/GIF/WebP
  nhiều frame được xử lý theo từng frame.
- **Dọn bố cục thông minh.** Bỏ header/footer lặp lại và số trang, nối dòng bị
  ngắt và đoạn bị cắt qua trang, suy ra heading và cấp heading từ cỡ chữ,
  nhận diện danh sách, chuẩn hoá Unicode.
- **Tách hình.** Hình được phát hiện bằng heuristic, cắt ra PNG và chèn link
  vào Markdown đúng vị trí theo thứ tự đọc, `alt` lấy từ chú thích gần đó.
- **Hai giao diện, một engine.** Web UI cục bộ cho người dùng phổ thông và CLI
  để tự động hoá.
- **Hiệu đính bằng AI tùy chọn.** Mặc định DeepSeek; hỗ trợ endpoint tương
  thích OpenAI (OpenAI, Ollama, custom) và Anthropic. Bộ chặn an toàn loại bỏ
  mọi chỉnh sửa làm đổi số, link hoặc dấu trang.
- **Windows không cần Python.** Bản EXE chứa sẵn runtime; engine OCR được tải
  một lần, kiểm tra SHA-256, vào thư mục dữ liệu người dùng.

## Cài đặt

### Windows (khuyến nghị)

Tải [`OCR2MD.exe`](https://github.com/imxuanmanh/ocr2md/releases/latest/download/OCR2MD.exe)
từ [bản phát hành mới nhất](https://github.com/imxuanmanh/ocr2md/releases/latest)
và mở file. Yêu cầu: Windows 10/11 x64, không cần cài Python.

Lần đầu mở, web UI chạy tại <http://127.0.0.1:8765>. Trước lần OCR đầu tiên,
vào **⚙ Cài đặt → Tải Tesseract**. Engine cùng dữ liệu ngôn ngữ `eng`, `vie`,
`osd` được cài vào `%APPDATA%\ocr2md`; bạn cũng có thể trỏ tới `tesseract.exe`
đã cài, hoặc dán link HTTPS riêng kèm SHA-256. EXE chưa ký số nên SmartScreen
có thể cảnh báo lần đầu: **More info → Run anyway**.

File EXE cũng mở được CLI:

```powershell
.\OCR2MD.exe doctor
.\OCR2MD.exe convert tai-lieu.pdf --lang vie+eng --extract-images
```

Chạy EXE không kèm tham số sẽ mở web UI, giống như nhấp đúp.

### pip / từ mã nguồn

Cần Python 3.10 trở lên. Trên Windows có thể cài wheel dựng sẵn; trên
Linux/macOS cài từ mã nguồn và dùng Tesseract của hệ điều hành.

```powershell
git clone https://github.com/imxuanmanh/ocr2md.git
cd ocr2md
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -e .
# Chỉ khi dùng nhà cung cấp Claude:
pip install -e ".[anthropic]"
```

Wheel dựng sẵn cho Windows:

```powershell
pip install https://github.com/imxuanmanh/ocr2md/releases/download/v0.2.1/ocr2md-0.2.1-py3-none-win_amd64.whl
```

Trên Linux/macOS, cài Tesseract qua trình quản lý gói (ví dụ
`apt install tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng`) hoặc dùng
Docker bên dưới. Người dùng Windows cài từ mã nguồn có thể cài Tesseract toàn
hệ thống hoặc để web UI tải giúp.

### Docker

Image đã có sẵn Tesseract cùng dữ liệu tiếng Việt/Anh.

```powershell
docker compose up --build     # lần đầu build, sau đó mở http://localhost:8765
docker compose up -d          # chạy nền
```

- Cài đặt và API key (nếu có) nằm trong volume `ocr2md-data`
  (`/data/config.json`). Đặt `DEEPSEEK_API_KEY=...` trong `.env` cạnh
  `docker-compose.yml` nếu muốn giữ key trong biến môi trường.
- Cổng chỉ publish về `127.0.0.1`; web UI không có đăng nhập. Đừng đổi thành
  `8765:8765` trừ khi đã đặt lớp xác thực phía trước.
- Chạy job CLI trong container với file mount trong `./work`:

  ```powershell
  docker compose run --rm ocr2md convert /work/tai-lieu.pdf --lang vie+eng --extract-images
  ```

  Kết quả ghi lại vào `./work`. Container chạy bằng uid 1000; trên Linux cần
  bảo đảm `./work` cho phép user đó ghi.
- Muốn dùng Ollama trên máy host từ trong container, trỏ URL tới
  `http://host.docker.internal:11434/v1`; trên Linux thêm
  `extra_hosts: ["host.docker.internal:host-gateway"]` vào service.
- Muốn dùng `tessdata_best`, mount thư mục tessdata của bạn vào container rồi
  nhập đường dẫn đó ở **⚙ Cài đặt → Thư mục tessdata**.
- Muốn bật nhà cung cấp Claude, bỏ comment dòng `pip install ".[anthropic]"`
  trong `Dockerfile`.

## Sử dụng

```powershell
# Chuyển cơ bản: ghi tai-lieu.md cạnh file đầu vào
ocr2md convert tai-lieu.pdf
python -m ocr2md convert tai-lieu.pdf      # tương đương

# Tuỳ chọn render, khoảng trang và dấu trang
ocr2md convert tai-lieu.pdf -o out.md --lang vie+eng --dpi 300 --pages 1-10 --page-markers

# Ảnh dùng cùng cách
ocr2md convert anh-chup.jpg                # PNG, JPEG, TIFF, BMP, WebP, GIF

# Tách hình ra tai-lieu_images/ và chèn link vào Markdown
ocr2md convert tai-lieu.pdf --extract-images
ocr2md convert tai-lieu.pdf --images-dir D:\anh\tai-lieu

# Web UI cục bộ
ocr2md serve                               # http://127.0.0.1:8765
ocr2md serve --port 9000 --no-browser

# Kiểm tra Tesseract, ngôn ngữ và nơi dữ liệu AI sẽ được gửi
ocr2md doctor
```

Các tuỳ chọn `convert` thường dùng:

| Tuỳ chọn | Mô tả |
|---|---|
| `-o, --output` | Đường dẫn `.md` đầu ra (mặc định: cạnh file đầu vào) |
| `--lang` | Ngôn ngữ Tesseract, ví dụ `vie+eng`; `auto` ưu tiên `vie+eng`, nếu không có thì `eng` |
| `--dpi` | Độ phân giải render trang PDF (mặc định `300`) |
| `--pages` | Chỉ xử lý các trang này, ví dụ `1-3,5` |
| `--page-markers` | Chèn `<!-- page N -->` trước mỗi trang |
| `--extract-images`, `--images-dir` | Tách hình và chọn thư mục lưu |
| `--psm`, `--workers` | Chế độ phân đoạn trang và số tiến trình OCR song song |
| `--tesseract`, `--tessdata` | Dùng bản Tesseract / dữ liệu ngôn ngữ cụ thể |
| `--ai`, `--keep-raw` | Bật hiệu đính AI, giữ bản trước AI thành `*.raw.md` |

## Web UI

UI cục bộ được thiết kế để dùng được ngay cả khi chưa cài Tesseract:

- **Cài đặt** với nút tải Tesseract một lần (tiến độ theo giai đoạn, kiểm tra
  SHA-256), hoặc nhập link HTTPS riêng kèm checksum, hoặc trỏ tới
  `tesseract.exe` đã có. Cài đặt được lưu trong thư mục dữ liệu người dùng.
- Kéo-thả PDF/ảnh, chọn ngôn ngữ/DPI/trang, xem tiến độ, huỷ job, xem trước và
  tải Markdown cùng gói ảnh.
- Cấu hình nhà cung cấp AI kèm nút kiểm tra kết nối.
- Mặc định chỉ bind `127.0.0.1`, chặn `Host` lạ (chống DNS rebinding) và request
  khác origin. Muốn dùng tên máy khác trong LAN, truyền `--allowed-host ten-may`
  (hoặc `*` khi đặt sau reverse proxy).

## Hiệu đính bằng AI (tùy chọn)

Hiệu đính AI **tắt mặc định**. Khi bật, Markdown được chia thành từng đoạn tối
đa 4.000 ký tự và gửi tới nhà cung cấp đã chọn.

| Nhà cung cấp | Endpoint / model mặc định | Cần |
|---|---|---|
| `deepseek` (mặc định) | `https://api.deepseek.com`, `deepseek-flash` | `DEEPSEEK_API_KEY` |
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` + `--ai-model` |
| `ollama` | `http://localhost:11434/v1` | `--ai-model` |
| `custom` | URL bạn đưa | `--ai-base-url` (+ `--ai-key-env` nếu cần) |
| `anthropic` | model `claude-sonnet-5-5` | `ANTHROPIC_API_KEY` + extra `anthropic` |

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
ocr2md convert tai-lieu.pdf --ai --keep-raw

ocr2md convert a.pdf --ai --ai-provider ollama --ai-model qwen2.5:14b
ocr2md convert a.pdf --ai --ai-provider custom --ai-base-url http://localhost:8000/v1 --ai-model my-model
```

Cũng đặt được nhà cung cấp, model và base URL bằng `OCR2MD_AI_PROVIDER`,
`OCR2MD_AI_MODEL`, `OCR2MD_AI_BASE_URL` (biến cũ `PDF2MD_*` vẫn được đọc). Với
DeepSeek, request gửi `thinking: disabled` để tránh tốn token không cần thiết.

**Chặn an toàn.** Một đoạn bị loại bỏ và giữ bản gốc (kèm cảnh báo) nếu phản
hồi làm đổi bất kỳ con số nào, đổi link ảnh hoặc dấu trang, lệch độ dài quá
±25%, hoặc bị cắt cụt. Vì vậy AI không được phép "sửa" lỗi OCR ở chữ số như
`1O0` → `100` — đây là chủ ý. Lỗi mạng được thử lại với 429/5xx; sai key hoặc
hết tiền thì dừng job ngay.

**Quyền riêng tư.** `doctor` in ra đích gửi dữ liệu trước mọi lệnh gọi AI. Dùng
`ollama` hoặc `custom` trỏ về localhost thì không có gì rời máy. Với
DeepSeek/OpenAI/Anthropic, văn bản OCR được gửi tới nhà cung cấp đó.

## Cách hoạt động

### Dựng Markdown

Bộ định dạng làm việc thận trọng:

- **Có làm:** bỏ header/footer lặp lại và số trang, gom dòng thành đoạn, nối
  đoạn bị cắt qua trang, suy ra heading từ cỡ chữ, nhận diện danh sách, chuẩn
  hoá Unicode (NFC) và khoảng trắng.
- **Không làm:** dựng lại bảng biểu, chữ đậm/nghiêng, bố cục nhiều cột, hoặc
  sửa lỗi nhận diện chữ.

Heading chỉ được nhận ra khi **to hơn** thân bài (≥ 1,25 lần). Heading cùng cỡ
nhưng in đậm sẽ thành đoạn văn thường. Với tiếng Việt, dấu gạch nối ngắt dòng
**không** được nối lại (tiếng Việt hiếm khi ngắt từ kiểu đó, và `Bắc-Nam` là
từ ghép thật); ngôn ngữ khác thì có nối.

### Tách hình

Phát hiện bằng heuristic, không dùng mô hình học máy: vùng có "mực" mà
Tesseract không nhận ra là chữ được gộp thành khối, các khối trông giống bảng
hoặc đoạn văn bị loại. Mỗi hình được cắt từ bản render màu, lưu PNG và chèn
đúng vị trí theo thứ tự đọc; `alt` lấy từ chú thích gần đó (`Hình 3: ...`,
`Figure 2...`). Chữ nằm trong vùng hình bị bỏ khỏi phần văn bản vì đã nằm
trong ảnh.

Giới hạn đã biết: có thể **sót** hình rất nhạt/rất nhỏ (dưới ~12% chiều rộng
hoặc 5% chiều cao trang), có thể **nhận nhầm** bảng kẻ thưa là hình, và hình bị
chữ đè lên nhiều sẽ bị coi là văn bản. Nên liếc qua thư mục ảnh sau khi chạy.

## Cấu hình

Khi cùng một giá trị được đặt ở nhiều nơi, thứ tự ưu tiên là:

1. cờ dòng lệnh
2. biến môi trường `TESSERACT_CMD` (riêng Tesseract)
3. ⚙ Cài đặt đã lưu
4. biến môi trường khác
5. mặc định của chương trình

API key lưu trong ⚙ Cài đặt thắng biến môi trường và chỉ dùng cho đúng nhà cung
cấp/base URL lúc lưu. File cấu hình nằm ở `%APPDATA%\ocr2md\config.json` trên
Windows (hoặc `$OCR2MD_CONFIG` / `~/.config/ocr2md/config.json` trên hệ khác).
File hỏng được đặt sang một bên thay vì làm ứng dụng crash.

## Tự build từ mã nguồn

EXE một file cho Windows (PyInstaller, kèm bộ giải nén 7-Zip dùng khi cài
Tesseract):

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e . pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
# kết quả: work\dist-final\OCR2MD.exe
```

Image Docker:

```powershell
docker compose build
```

## Kiểm thử

Bộ test chỉ dùng thư viện chuẩn và không cần mạng. Các test cần Tesseract thật
sẽ được bỏ qua khi chưa có engine.

```powershell
python -m unittest discover -s tests
```

## Cấu trúc project

```
ocr2md/
  cli.py         điểm vào dòng lệnh (convert / serve / doctor)
  web.py         Flask app và UI nhúng
  pipeline.py    luồng PDF/ảnh -> OCR -> Markdown dùng chung
  ocr.py         tìm Tesseract và xử lý TSV
  markdown.py    quy tắc bố cục: heading, đoạn, danh sách, nối trang
  figures.py     phát hiện và cắt hình bằng heuristic
  inputs.py      nhận diện định dạng đầu vào
  ai.py          cấu hình nhà cung cấp, chia đoạn và chặn an toàn
  installer.py   tải/giải nén Tesseract có kiểm tra (Windows)
  config.py      cài đặt được lưu
tests/           bộ test unittest
```

## Giấy phép

ocr2md phát hành theo [MIT License](LICENSE). Các thành phần bên thứ ba, gồm
bộ giải nén 7-Zip đi kèm, PyMuPDF (AGPL-3.0) và Tesseract tải lúc chạy, được
liệt kê trong [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
