from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OCRResult:
    text: str
    status: str
    engine: str
    error: str = ""


class ImageOCRAdapter:
    """Optional OCR adapter.

    The adapter is intentionally dependency-light at import time. If users install
    pytesseract and the tesseract binary, image documents become searchable
    without changing the ingestion pipeline.
    """

    def extract_text(self, image_path: Path) -> OCRResult:
        if not shutil.which("tesseract"):
            return OCRResult(
                text="",
                status="unavailable",
                engine="tesseract",
                error="未安装 tesseract 可执行文件。",
            )
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            return OCRResult(
                text="",
                status="unavailable",
                engine="tesseract",
                error=f"缺少 Python 依赖：{exc.__class__.__name__}",
            )

        try:
            text = pytesseract.image_to_string(Image.open(image_path), lang="chi_sim+eng")
        except Exception as exc:
            return OCRResult(
                text="",
                status="failed",
                engine="tesseract",
                error=f"OCR 处理失败（{type(exc).__name__}）。",
            )
        return OCRResult(text=text.strip(), status="ok" if text.strip() else "empty", engine="tesseract")
