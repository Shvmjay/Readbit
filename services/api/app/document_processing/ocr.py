"""OCR adapter. OCR is optional and never silently assumed: `OCR_PROVIDER=none` disables it."""

from __future__ import annotations

import shutil
import subprocess  # noqa: S404 - fixed argv, no shell
from abc import ABC, abstractmethod

from app.core.config import get_settings


class OCREngine(ABC):
    name = "none"

    @property
    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def image_to_text(self, image_bytes: bytes, language: str = "eng") -> str: ...


class NoOCR(OCREngine):
    name = "none"

    @property
    def available(self) -> bool:
        return False

    def image_to_text(self, image_bytes: bytes, language: str = "eng") -> str:
        return ""


class TesseractOCR(OCREngine):
    """Runs the local `tesseract` binary on page images. Requires tesseract to be installed in the worker image."""

    name = "tesseract"

    @property
    def available(self) -> bool:
        return shutil.which("tesseract") is not None

    def image_to_text(self, image_bytes: bytes, language: str = "eng+hin") -> str:
        binary = shutil.which("tesseract")
        if not binary:
            return ""
        proc = subprocess.run(  # noqa: S603
            [binary, "stdin", "stdout", "-l", language],
            input=image_bytes,
            capture_output=True,
            timeout=60,
            check=False,
        )
        return proc.stdout.decode("utf-8", "ignore") if proc.returncode == 0 else ""


def get_ocr_engine() -> OCREngine:
    if get_settings().ocr_provider == "tesseract":
        return TesseractOCR()
    return NoOCR()
