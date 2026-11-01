from functools import lru_cache
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Environment variables still work when running the dependency-light demo.
    pass


class Settings:
    app_name: str = "InvoiceIQ"
    api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    demo_mode: bool = os.getenv("INVOICEIQ_DEMO_MODE", "true").lower() == "true"
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "15"))
    max_document_chars: int = int(os.getenv("MAX_DOCUMENT_CHARS", "30000"))
    validation_tolerance: float = float(os.getenv("VALIDATION_TOLERANCE", "0.02"))
    ocr_enabled: bool = os.getenv("OCR_ENABLED", "true").lower() == "true"

    @property
    def live_llm(self) -> bool:
        return bool(self.api_key) and not self.demo_mode


@lru_cache
def get_settings() -> Settings:
    return Settings()

