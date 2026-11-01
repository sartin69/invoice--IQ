from time import perf_counter
from uuid import uuid4
from invoiceiq.models import ExtractionResponse, ProcessingMetadata
from invoiceiq.services.extraction import extract_invoice
from invoiceiq.services.ingestion import extract_document
from invoiceiq.services.validation import validate_invoice


def process_document(data: bytes, filename: str) -> ExtractionResponse:
    started = perf_counter()
    doc = extract_document(data, filename)
    invoice, mode = extract_invoice(doc.text)
    validation = validate_invoice(invoice)
    return ExtractionResponse(
        document_id=str(uuid4()), invoice=invoice, validation=validation,
        processing_status="completed" if not validation.errors else "failed",
        metadata=ProcessingMetadata(extraction_mode=mode, text_source=doc.source,
                                   elapsed_ms=round((perf_counter() - started) * 1000, 2), page_count=doc.page_count),
    )

