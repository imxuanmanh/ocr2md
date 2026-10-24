FROM python:3.12-slim-bookworm

# Tesseract + tiếng Việt/Anh từ Debian. Muốn dùng tessdata_best: mount thư mục tessdata của bạn
# và nhập đường dẫn trong ⚙ Cài đặt (xem README).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-vie tesseract-ocr-osd \
 && rm -rf /var/lib/apt/lists/*

# Chạy bằng user thường, không phải root. /data chứa cấu hình (⚙ Cài đặt), /work để mount file cho CLI.
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /data /work \
 && chown app:app /data /work

WORKDIR /app
COPY pyproject.toml ./
COPY ocr2md ./ocr2md
RUN pip install --no-cache-dir .
# Dùng Claude làm bước AI? Bỏ comment dòng dưới (DeepSeek/OpenAI/Ollama không cần gói này):
# RUN pip install --no-cache-dir ".[anthropic]"

USER app
ENV OCR2MD_CONFIG=/data/config.json \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
WORKDIR /work
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8765/api/config', timeout=3)" || exit 1

# Mặc định chạy web UI; ghi đè bằng: docker compose run --rm ocr2md convert /work/file.pdf ...
ENTRYPOINT ["ocr2md"]
CMD ["serve", "--host", "0.0.0.0", "--no-browser"]
