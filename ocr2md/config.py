"""Cấu hình lưu trên đĩa, để chỉnh bằng giao diện web một lần là dùng được cả CLI lẫn web.

Vị trí: %APPDATA%\\ocr2md\\config.json (Windows), ~/.config/ocr2md/config.json (nơi khác);
đổi được bằng biến môi trường OCR2MD_CONFIG.

Lưu ý: API key (nếu bạn nhập trong giao diện) được lưu dạng văn bản thường trong file này.
Trên máy dùng chung, hãy dùng biến môi trường thay vì lưu key.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Settings:
    tesseract: str = ""
    tessdata: str = ""
    ai_provider: str = ""
    ai_model: str = ""
    ai_base_url: str = ""
    ai_key_env: str = ""
    ai_api_key: str = ""


def config_path() -> Path:
    override = os.environ.get("OCR2MD_CONFIG") or os.environ.get("PDF2MD_CONFIG")
    if override:
        return Path(override)
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "ocr2md" / "config.json"


def load(path: Path | None = None) -> Settings:
    migrated = False
    if path is None:
        path = config_path()
        if not path.exists() and not (os.environ.get("OCR2MD_CONFIG") or os.environ.get("PDF2MD_CONFIG")):
            old = path.parent.parent / "pdf2md" / "config.json"
            if old.is_file():
                path, migrated = old, True
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config không phải object")
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError):  # file hỏng: để nguyên làm bản sao lưu, dùng mặc định
        try:
            path.replace(path.with_name(path.name + ".bad"))
        except OSError:
            pass
        return Settings()
    known = {f.name for f in fields(Settings)}
    settings = Settings(**{k: v for k, v in raw.items() if k in known and isinstance(v, str)})
    if migrated:
        settings.tesseract = ""
        settings.tessdata = ""
    return settings


def save(settings: Settings, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(settings), fh, ensure_ascii=False, indent=2)
        if os.name != "nt":
            os.chmod(tmp, 0o600)  # file có thể chứa API key
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
