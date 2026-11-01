from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class FieldStatus(str, Enum):
    extracted = "extracted"
    missing = "missing"
    uncertain = "uncertain"
    invalid = "invalid"


class LineItem(BaseModel):
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    tax: Decimal | None = None
    tax_rate: Decimal | None = Field(default=None, description="Stated tax rate in percentage points, distinct from tax amount")
    line_total: Decimal | None = None


class Invoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_name: str | None = None
    supplier_address: str | None = None
    supplier_tax_id: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    customer_name: str | None = None
    customer_tax_id: str | None = None
    currency: str | None = Field(default=None, description="ISO 4217 currency code when identifiable")
    subtotal: Decimal | None = None
    tax_amount: Decimal | None = None
    discount: Decimal | None = None
    total_amount: Decimal | None = None
    payment_terms: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    field_status: dict[str, FieldStatus] = Field(default_factory=dict)
    source_pages: dict[str, list[int]] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    status: str
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    human_review_required: bool


class ProcessingMetadata(BaseModel):
    extraction_mode: str
    text_source: str
    elapsed_ms: float
    page_count: int


class ExtractionResponse(BaseModel):
    document_id: str
    invoice: Invoice
    validation: ValidationResult
    processing_status: str
    processing_errors: list[str] = Field(default_factory=list)
    metadata: ProcessingMetadata


class ValidationRequest(BaseModel):
    invoice: Invoice


class ToolReviewResponse(BaseModel):
    summary: str
    tool_results: list[dict[str, Any]]
    validation: ValidationResult

