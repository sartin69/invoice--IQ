from decimal import Decimal
from invoiceiq.models import FieldStatus, Invoice, ValidationResult
from invoiceiq.config import get_settings

REQUIRED_FIELDS = ("supplier_name", "customer_name", "invoice_number", "invoice_date", "total_amount")
MONEY_FIELDS = ("subtotal", "tax_amount", "discount", "total_amount")


def validate_invoice(invoice: Invoice, tolerance: Decimal | None = None) -> ValidationResult:
    """Check completeness, date ordering, line arithmetic, and balance without changing values."""
    tol = tolerance if tolerance is not None else Decimal(str(get_settings().validation_tolerance))
    warnings: list[str] = []
    errors: list[str] = []
    passed: list[str] = []
    failed: list[str] = []
    for field in REQUIRED_FIELDS:
        status = invoice.field_status.get(field)
        if getattr(invoice, field) is None or status in {FieldStatus.uncertain, FieldStatus.invalid}:
            reason = "missing or uncertain" if getattr(invoice, field) is not None else "missing"
            warnings.append(f"Important field is {reason}: {field.replace('_', ' ')}")
            failed.append(f"required:{field}")
        else:
            passed.append(f"required:{field}")
    if invoice.currency:
        passed.append("currency:identified")
    else:
        warnings.append("Currency is not identified.")
        failed.append("currency:identified")
    if invoice.invoice_date and invoice.due_date:
        if invoice.due_date < invoice.invoice_date:
            warnings.append("Due date is earlier than invoice date; verify both dates.")
            failed.append("dates:logical_order")
        else:
            passed.append("dates:logical_order")
    elif invoice.invoice_date:
        passed.append("dates:invoice_date_parseable")
    if invoice.subtotal is not None and invoice.tax_amount is not None and invoice.total_amount is not None:
        expected = invoice.subtotal + invoice.tax_amount - (invoice.discount or Decimal("0"))
        if abs(expected - invoice.total_amount) <= tol:
            passed.append("totals:reconcile")
        else:
            warnings.append(f"Subtotal + tax - discount differs from total by {abs(expected - invoice.total_amount)} {invoice.currency or ''}. This is a discrepancy to review, not a fraud finding.")
            failed.append("totals:reconcile")
    else:
        warnings.append("Totals could not be reconciled because subtotal, tax, discount, or total is missing.")
        failed.append("totals:reconcile")
    for index, item in enumerate(invoice.line_items, 1):
        if item.quantity is not None and item.unit_price is not None and item.line_total is not None:
            expected = item.quantity * item.unit_price + (item.tax or Decimal("0"))
            if abs(expected - item.line_total) <= tol:
                passed.append(f"line_item:{index}:calculation")
            else:
                warnings.append(f"Line item {index} calculation differs from its stated line total.")
                failed.append(f"line_item:{index}:calculation")
    if not failed and not warnings:
        return ValidationResult(status="validated", warnings=[], errors=errors, checks_passed=passed, checks_failed=[], human_review_required=False)
    status = "failed" if errors else "review_required"
    return ValidationResult(status=status, warnings=warnings, errors=errors, checks_passed=passed, checks_failed=failed, human_review_required=True)

