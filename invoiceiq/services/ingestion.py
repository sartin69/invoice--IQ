from dataclasses import dataclass
from io import BytesIO
import logging
from pathlib import Path
from PIL import Image, UnidentifiedImageError
import fitz
from invoiceiq.config import get_settings

logger = logging.getLogger(__name__)
SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg"}


class IngestionError(ValueError):
    pass


@dataclass
class DocumentText:
    text: str
    source: str
    page_count: int


def extract_document(data: bytes, filename: str) -> DocumentText:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise IngestionError("Unsupported file type. Upload a PDF, PNG, or JPEG.")
    if not data:
        raise IngestionError("The uploaded file is empty.")
    if suffix == ".pdf":
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise IngestionError("The PDF is corrupted or unreadable.") from exc
        parts = []
        for n, page in enumerate(doc, 1):
            text = page.get_text("text").strip()
            if text:
                parts.append(f"[Page {n}]\n{text}")
        count = len(doc)
        if parts:
            return DocumentText("\n\n".join(parts), "digital_pdf", count)
        if not get_settings().ocr_enabled:
            raise IngestionError("No selectable text found in this PDF and OCR is disabled.")
        try:
            import pytesseract
            ocr_parts = []
            for n, page in enumerate(doc, 1):
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.open(BytesIO(pix.tobytes("png")))
                text = pytesseract.image_to_string(image).strip()
                if text:
                    ocr_parts.append(f"[Page {n}]\n{text}")
            if not ocr_parts:
                raise IngestionError("OCR found no readable text in the scanned PDF.")
            return DocumentText("\n\n".join(ocr_parts), "ocr", count)
        except IngestionError:
            raise
        except Exception as exc:
            raise IngestionError("Scanned PDF needs Tesseract installed and available on PATH. See README OCR setup.") from exc
    try:
        image = Image.open(BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise IngestionError("The image is corrupted or unreadable.") from exc
    if not get_settings().ocr_enabled:
        raise IngestionError("Image invoices require OCR, which is disabled.")
    try:
        import pytesseract
        text = pytesseract.image_to_string(image).strip()
    except Exception as exc:
        raise IngestionError("Image OCR needs Tesseract installed and available on PATH. See README OCR setup.") from exc
    if not text:
        raise IngestionError("OCR found no readable text in the image.")
    return DocumentText(f"[Page 1]\n{text}", "ocr", 1)

