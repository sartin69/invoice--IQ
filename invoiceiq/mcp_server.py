"""Small stdio MCP server exposing safe InvoiceIQ business functions."""
from decimal import Decimal
from mcp.server.fastmcp import FastMCP
from invoiceiq.models import Invoice
from invoiceiq.services.validation import validate_invoice

mcp = FastMCP("InvoiceIQ")


@mcp.tool()
def validate_structured_invoice(invoice: dict) -> dict:
    """Check a supplied structured invoice for missing fields and arithmetic inconsistencies."""
    parsed = Invoice.model_validate(invoice)
    return validate_invoice(parsed).model_dump(mode="json")


@mcp.tool()
def calculate_invoice_total(subtotal: float, tax: float, discount: float = 0.0) -> dict:
    """Calculate subtotal plus tax minus discount. Does not edit or approve an invoice."""
    expected = Decimal(str(subtotal)) + Decimal(str(tax)) - Decimal(str(discount))
    return {"calculated_total": str(expected)}


@mcp.tool()
def list_missing_invoice_fields(invoice: dict) -> dict:
    """List important invoice fields absent from the supplied data."""
    parsed = Invoice.model_validate(invoice)
    fields = ("supplier_name", "invoice_number", "invoice_date", "currency", "total_amount")
    return {"missing_fields": [field for field in fields if getattr(parsed, field) is None]}


if __name__ == "__main__":
    mcp.run(transport="stdio")

