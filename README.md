# ocr2md

OCR **PDF và ảnh** bằng Tesseract rồi biên tập thành **Markdown**. Có CLI và web UI cục bộ.
Ứng dụng mở được ngay. Trên Windows, vào ⚙ Cài đặt để tải Tesseract khi cần; có thanh tiến độ tải và hỗ trợ dán link bộ cài riêng kèm SHA-256, hoặc chọn đường dẫn Tesseract đã cài.
Toàn bộ chạy trên máy bạn; bước hiệu đính bằng AI là tùy chọn và tắt mặc định.

```
PDF ──PyMuPDF render──▶ ảnh ──▶ Tesseract (TSV)──▶ dòng chữ + toạ độ ──quy tắc──▶ Markdown ──(tùy chọn) AI──▶ Markdown
```

Ảnh PNG, JPEG, TIFF, BMP, WebP và GIF đi thẳng vào OCR. TIFF/GIF/WebP nhiều frame được xử lý theo từng trang/frame.

## Bản Windows mở trực tiếp

Tải `OCR2MD.exe` từ [GitHub Releases](https://github.com/imxuanmanh/ocr2md/releases/latest) rồi mở file. Cửa sổ dòng lệnh sẽ chạy web UI và trình duyệt tự mở tại `http://127.0.0.1:8765`; đóng cửa sổ dòng lệnh để dừng ứng dụng. File EXE khoảng 45 MB và không chứa Tesseract. Lần đầu cần OCR, vào **⚙ Cài đặt → Tải Tesseract**; bộ OCR tải riêng và lưu trong dữ liệu người dùng. Có thể dùng đường dẫn bản đã cài thay cho tải tự động.

Để tự tạo EXE từ mã nguồn trên Windows:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e . pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
# kết quả: work\dist-final\OCR2MD.exe
```

## Chạy bằng venv (VS Code)

```powershell
# Mở thư mục project trong VS Code, rồi trong terminal tích hợp:
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -e .
# Chỉ nếu muốn dùng Claude làm bước AI (DeepSeek/OpenAI/Ollama không cần):
pip install -e ".[anthropic]"

python -m ocr2md serve              # web UI tại http://127.0.0.1:8765
```

VS Code tự nhận `.venv`; chọn nó ở *Python: Select Interpreter*. Thư mục `.vscode/` có sẵn:
**F5** chạy/debug web UI, convert file PDF/ảnh đang mở, hoặc `doctor`; tab *Testing* chạy được unittest.

Web UI chạy ngay cả khi chưa có Tesseract. Trong ⚙ Cài đặt, bấm **Tải Tesseract** để lấy bản Windows x64 đề xuất cùng dữ liệu `eng`, `vie`, `osd`; thanh tiến độ hiển thị từng giai đoạn. Có thể nhập link HTTPS khác kèm SHA-256 để tải bản riêng, hoặc điền đường dẫn `tesseract.exe` đã có. Sau khi cài, chạy `python -m ocr2md doctor` để kiểm tra.
Trên Linux/macOS, dùng Docker hoặc cài Tesseract qua trình quản lý gói của hệ điều hành.

## Chạy bằng Docker

```powershell
docker compose up --build          # lần đầu build, sau đó mở http://localhost:8765
docker compose up -d               # chạy nền
```

- Image có sẵn Tesseract + tiếng Việt/Anh (gói Debian). Để trống ô Tesseract trong ⚙ Cài đặt, nó tự tìm.
- Cổng chỉ publish về `127.0.0.1` (web UI không có đăng nhập). Đừng đổi thành `8765:8765`.
- ⚙ Cài đặt được giữ trong volume `ocr2md-data` (file `/data/config.json`, API key nếu bạn nhập nằm ở đây).
  Muốn đưa key bằng biến môi trường thay vì lưu: đặt `DEEPSEEK_API_KEY=...` trong file `.env` cạnh `docker-compose.yml`.
- Dùng CLI trong container: đặt PDF hoặc ảnh vào `./work` rồi
  ```powershell
  docker compose run --rm ocr2md convert /work/tai-lieu.pdf --lang vie+eng --extract-images
  ```
  Kết quả ra cùng thư mục `./work`. Container chạy bằng user uid 1000; trên Linux nếu `./work` thuộc user khác thì ghi file sẽ bị từ chối.
- Muốn bước AI dùng Claude: bỏ comment dòng `pip install ".[anthropic]"` trong `Dockerfile`.
- Dùng Ollama chạy trên máy host từ trong container: URL là `http://host.docker.internal:11434/v1` (Docker Desktop);
  trên Linux thêm `extra_hosts: ["host.docker.internal:host-gateway"]` vào service.
- Muốn dùng `tessdata_best`: mount thư mục tessdata của bạn vào container (thêm vào `volumes`) rồi nhập đường dẫn đó ở ô *Thư mục tessdata*.

Thứ tự ưu tiên khi cùng một mục được đặt ở nhiều nơi: cờ dòng lệnh > biến `TESSERACT_CMD` (riêng Tesseract) > ⚙ Cài đặt đã lưu > biến môi trường khác > mặc định.
API key lưu trong ⚙ Cài đặt thắng biến môi trường, và chỉ được dùng cho đúng nhà cung cấp/URL lúc lưu.

## Dùng

```powershell
# CLI
python -m ocr2md convert tai-lieu.pdf                 # ghi tai-lieu.md cạnh file PDF
python -m ocr2md convert tai-lieu.pdf -o out.md --lang vie+eng --dpi 300 --pages 1-10 --page-markers
python -m ocr2md convert anh-chup.jpg          # PNG, JPEG, TIFF, BMP, WebP, GIF cũng được

# Tách hình ra thư mục tai-lieu_images/ và chèn link ![...](tai-lieu_images/p001_fig01.png) vào .md
python -m ocr2md convert tai-lieu.pdf --extract-images
python -m ocr2md convert tai-lieu.pdf --images-dir D:\anh\tai-lieu

# Web UI (mở http://127.0.0.1:8765)
python -m ocr2md serve

# Hiệu đính bằng AI (tùy chọn) — mặc định DeepSeek
$env:DEEPSEEK_API_KEY = "sk-..."
python -m ocr2md convert tai-lieu.pdf --ai --keep-raw
```

Dùng `--tesseract`/`--tessdata` nếu chạy CLI với bản Tesseract riêng. Web UI vẫn mở khi chưa có engine để bạn tải hoặc chọn đường dẫn.
`python -m ocr2md doctor` in ra tình trạng Tesseract, ngôn ngữ, và nơi dữ liệu sẽ được gửi nếu bật AI.

## Tách hình

Phát hiện bằng heuristic (không dùng mô hình học máy): lấy vùng có "mực" mà Tesseract không nhận ra là chữ,
gộp thành khối, rồi loại khối trông giống bảng/đoạn văn. Mỗi hình được cắt từ bản render màu, lưu PNG,
chèn vào Markdown đúng vị trí theo thứ tự đọc, `alt` lấy từ dòng chú thích gần đó (`Hình 3: ...`, `Figure 2...`).
Chữ nằm trong vùng hình (nhãn trục biểu đồ, rác OCR từ ảnh chụp) bị bỏ khỏi văn bản vì đã nằm trong ảnh.

Giới hạn: có thể **sót** hình rất nhạt/rất nhỏ (dưới ~12% chiều rộng hoặc 5% chiều cao trang), có thể **nhận nhầm**
bảng vẽ bằng đường kẻ thưa là hình, và hình bị chữ đè lên nhiều sẽ bị coi là văn bản. Nên liếc qua thư mục ảnh sau khi chạy.

## Chọn nhà cung cấp AI

| `--ai-provider` | Mặc định | Cần |
|---|---|---|
| `deepseek` (mặc định) | `https://api.deepseek.com`, model `deepseek-flash` | `DEEPSEEK_API_KEY` |
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` + `--ai-model` |
| `ollama` | `http://localhost:11434/v1` (chạy local) | `--ai-model` |
| `custom` | URL bạn đưa | `--ai-base-url` (+ `--ai-key-env` nếu cần key) |
| `anthropic` | model `claude-sonnet-5-5` | `ANTHROPIC_API_KEY` + `pip install anthropic` |

```powershell
python -m ocr2md convert a.pdf --ai --ai-provider ollama --ai-model qwen2.5:14b
python -m ocr2md convert a.pdf --ai --ai-provider custom --ai-base-url http://localhost:8000/v1 --ai-model my-model
```

Cũng đặt được bằng biến môi trường: `OCR2MD_AI_PROVIDER`, `OCR2MD_AI_MODEL`, `OCR2MD_AI_BASE_URL`. Các biến `PDF2MD_*` cũ vẫn được đọc.
Với DeepSeek, tool gửi `thinking: disabled` (mặc định của DeepSeek là bật; việc sửa lỗi OCR không cần và sẽ tốn token hơn).
Tên model và giá của DeepSeek thay đổi theo thời gian — nếu `deepseek-flash` không còn, đổi bằng `--ai-model`.

## Phần biên tập làm gì (và không làm gì)

Làm: bỏ header/footer lặp lại và số trang · gom dòng thành đoạn · nối đoạn bị cắt giữa hai trang ·
suy ra heading và cấp heading từ cỡ chữ · nhận diện danh sách · chuẩn hoá Unicode (NFC) và khoảng trắng.

Không làm: **bảng biểu**, chữ đậm/nghiêng, bố cục nhiều cột, sửa lỗi nhận diện chữ.
Heading chỉ nhận ra được khi chúng **to hơn** thân bài (≥1,25 lần); heading cùng cỡ nhưng in đậm sẽ thành đoạn văn thường.

Với tiếng Việt, tool **không** nối từ bị ngắt dòng bằng dấu gạch nối (vì tiếng Việt gần như không ngắt từ kiểu đó,
còn "Bắc-Nam" là từ ghép thật). Với ngôn ngữ khác thì có nối.

## Bước AI: cơ chế an toàn

Văn bản chia thành từng đoạn ≤ 4000 ký tự gửi lên API (tự thử lại khi gặp 429/5xx; sai key/hết tiền thì dừng ngay).
Kết quả của mỗi đoạn bị loại bỏ (giữ bản gốc, có cảnh báo) nếu: **con số bị đổi**, **link ảnh hoặc dấu trang bị đổi**,
độ dài lệch quá ±25%, hoặc phản hồi bị cắt cụt. Hệ quả: AI không sửa được lỗi OCR ở chữ số (`1O0` → `100`);
đó là chủ ý để tránh "sửa" nhầm số liệu.

**Quyền riêng tư:** tool in rõ dữ liệu sẽ đi đâu trước khi chạy. Dùng `ollama` hoặc `custom` trỏ về localhost
thì không có gì rời máy. Web UI không có đăng nhập; nó chặn request có `Host` lạ (chống DNS rebinding) và `Origin` khác (chống trang web khác
gọi vào). Muốn truy cập bằng tên khác (ví dụ tên máy trong LAN) thì thêm `--allowed-host ten-may`.

## Kiểm thử

```powershell
python -m unittest discover -s tests
```
