import logging
from typing import Annotated
from fastapi import FastAPI, File, HTTPException, UploadFile
from invoiceiq.config import get_settings
from invoiceiq.models import ExtractionResponse, Invoice, ValidationRequest, ValidationResult
from invoiceiq.service import process_document
from invoiceiq.services.ingestion import IngestionError
from invoiceiq.services.validation import validate_invoice

logger = logging.getLogger("invoiceiq")
app = FastAPI(title="InvoiceIQ API", version="0.1.0", description="Invoice extraction and deterministic validation prototype")


@app.get("/health")
def health():
    settings = get_settings()
    return {"status": "ok", "mode": "live" if settings.live_llm else "demo", "model": settings.model if settings.live_llm else None}


@app.post("/extract", response_model=ExtractionResponse)
async def extract(file: Annotated[UploadFile, File(description="Invoice PDF, PNG or JPEG")]):
    filename = file.filename or "upload"
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds {get_settings().max_upload_mb} MB limit.")
    try:
        return process_document(data, filename)
    except IngestionError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        logger.warning("Extraction provider failed: %s", str(exc))
        raise HTTPException(502, "Extraction provider failed. Check server configuration and retry.") from exc


@app.post("/validate", response_model=ValidationResult)
def validate(request: ValidationRequest):
    return validate_invoice(request.invoice)


@app.get("/evaluation/summary")
def evaluation_summary():
    from invoiceiq.evaluation import load_latest_summary
    return load_latest_summary() or {"status": "not_run", "message": "Run python -m invoiceiq.evaluation to produce measured results."}


@app.post("/review")
def review(invoice: Invoice):
    from invoiceiq.agent import review_invoice
    return review_invoice(invoice)

