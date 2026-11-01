from decimal import Decimal
import json
from pathlib import Path
import pytest
from invoiceiq.agent import run_review_tools
from invoiceiq.models import FieldStatus, Invoice
from invoiceiq.service import process_document
from invoiceiq.services.extraction import demo_extract, extract_invoice
from invoiceiq.services.ingestion import IngestionError, extract_document
from invoiceiq.services.validation import validate_invoice
from invoiceiq.agent import MAX_TOOL_ROUNDS


def sample(**overrides):
    values = {"supplier_name": "Acme LLC", "customer_name": "Example Buyer LLC", "invoice_number": "A-1", "invoice_date": "2026-01-01", "due_date": "2026-02-01", "currency": "AED", "subtotal": "100.00", "tax_amount": "5.00", "total_amount": "105.00"}
    values.update(overrides)
    return Invoice.model_validate(values)


def test_balanced_invoice_validates_without_review():
    result = validate_invoice(sample())
    assert result.status == "validated"
    assert not result.human_review_required


def test_missing_fields_and_currency_require_review():
    result = validate_invoice(Invoice())
    assert result.status == "review_required"
    assert result.human_review_required
    assert any("supplier name" in warning for warning in result.warnings)


def test_missing_or_uncertain_party_identity_requires_review():
    missing_customer = validate_invoice(sample(customer_name=None))
    assert missing_customer.status == "review_required"
    assert "required:customer_name" in missing_customer.checks_failed

    uncertain_supplier = sample()
    uncertain_supplier.field_status["supplier_name"] = FieldStatus.uncertain
    uncertain_result = validate_invoice(uncertain_supplier)
    assert uncertain_result.status == "review_required"
    assert "required:supplier_name" in uncertain_result.checks_failed


def test_conflicting_supplier_or_customer_candidates_remain_uncertain():
    invoice = demo_extract("""Supplier Name: First Supplier LLC
Supplier Name: Second Supplier LLC
Invoice Number: I-44
Invoice Date: 2026-05-04
Currency: AED
BILL TO
Customer: First Buyer LLC
Customer: Second Buyer LLC
Subtotal: 100.00
Tax: 5.00
Total: 105.00""")
    assert invoice.supplier_name is None
    assert invoice.customer_name is None
    assert invoice.field_status["supplier_name"] == FieldStatus.uncertain
    assert invoice.field_status["customer_name"] == FieldStatus.uncertain
    result = validate_invoice(invoice)
    assert result.status == "review_required"
    assert "required:supplier_name" in result.checks_failed
    assert "required:customer_name" in result.checks_failed


@pytest.mark.parametrize(
    ("party_block", "expected_customer"),
    [
        ("BILL TO\nCedar & Finch Design Studio FZ-LLC", "Cedar & Finch Design Studio FZ-LLC"),
        ("Customer: Orchard Studio FZE", "Orchard Studio FZE"),
        ("Customer:\nMaple Ridge Trading Ltd", "Maple Ridge Trading Ltd"),
        ("BILL TO: Willow & Pine Supplies LLC", "Willow & Pine Supplies LLC"),
    ],
)
def test_customer_name_layout_variants_stop_before_tax_and_address(party_block, expected_customer):
    text = f"""Supplier: Harbor Stationery LLC
Invoice Number: HS-502
Invoice Date: 2026-09-12
Currency: AED
{party_block}
Customer Address: Suite 4, Market Street
Customer TRN: 100500600700800
ITEMS
Subtotal: 100.00
Tax Amount: 5.00
Total: 105.00"""
    invoice = demo_extract(text)
    assert invoice.supplier_name == "Harbor Stationery LLC"
    assert invoice.customer_name == expected_customer
    assert invoice.customer_tax_id == "100500600700800"
    assert validate_invoice(invoice).status == "validated"


def test_customer_name_without_other_required_data_still_requires_review():
    invoice = demo_extract("Supplier: Harbor Stationery LLC\nCustomer: Orchard Studio FZE\nInvoice Date: 2026-09-12\nCurrency: AED\nSubtotal: 100.00\nTax: 5.00\nTotal: 105.00")
    assert invoice.customer_name == "Orchard Studio FZE"
    result = validate_invoice(invoice)
    assert result.status == "review_required"
    assert "required:invoice_number" in result.checks_failed


def test_customer_registration_number_does_not_pollute_tax_amount():
    invoice = demo_extract("""Supplier: Harbor Stationery LLC
Invoice Number: HS-503
Invoice Date: 2026-09-12
Currency: AED
BILL TO
Customer: Orchard Studio FZE
Tax Registration Number: 100500600700800
Subtotal: 100.00
Tax Amount: 5.00
Total: 105.00""")
    assert invoice.customer_name == "Orchard Studio FZE"
    assert invoice.customer_tax_id == "100500600700800"
    assert invoice.tax_amount == Decimal("5.00")
    assert validate_invoice(invoice).status == "validated"


def test_discrepant_total_is_flagged_and_not_changed():
    inv = sample(total_amount="999")
    result = validate_invoice(inv)
    assert "totals:reconcile" in result.checks_failed
    assert inv.total_amount == Decimal("999")


def test_date_order_is_flagged():
    result = validate_invoice(sample(due_date="2025-01-01"))
    assert "dates:logical_order" in result.checks_failed


def test_unsupported_empty_and_corrupt_inputs():
    with pytest.raises(IngestionError, match="Unsupported"):
        extract_document(b"x", "invoice.docx")
    with pytest.raises(IngestionError, match="empty"):
        extract_document(b"", "invoice.pdf")
    with pytest.raises(IngestionError, match="corrupted"):
        extract_document(b"not pdf", "invoice.pdf")


def test_empty_extraction_rejected():
    with pytest.raises(ValueError, match="No usable text"):
        extract_invoice("  ")


def test_malformed_structured_invoice_is_rejected():
    with pytest.raises(Exception):
        Invoice.model_validate({"total_amount": "not money"})


def test_demo_parser_extracts_expected_values():
    text = "Supplier: Sample LLC\nInvoice Number: INV-5\nInvoice Date: 2026-01-02\nCurrency: AED\nSubtotal: 100.00\nTax: 5.00\nTotal: 105.00"
    inv = demo_extract(text)
    assert inv.supplier_name == "Sample LLC"
    assert inv.total_amount == Decimal("105.00")
    assert inv.due_date is None


def test_synthetic_pdf_ingests_and_extracts_all_fields_and_line_items():
    path = Path(__file__).parents[1] / "examples" / "invoiceiq-synthetic-test-invoice.pdf"
    document = extract_document(path.read_bytes(), path.name)
    assert document.source == "digital_pdf"
    # Verify what the PDF layer handed to the parser before checking parser output.
    for value in ("Gulf Horizon Office Supplies LLC", "DEMO-2026-1042", "2026-10-01", "A4 recycled paper", "Subtotal: 800.00", "Total: 840.00"):
        assert value in document.text
    invoice = demo_extract(document.text)
    assert invoice.supplier_name == "Gulf Horizon Office Supplies LLC"
    assert invoice.invoice_number == "DEMO-2026-1042"
    assert str(invoice.invoice_date) == "2026-10-01"
    assert invoice.currency == "AED"
    assert invoice.subtotal == Decimal("800.00")
    assert invoice.tax_amount == Decimal("40.00")
    assert invoice.discount == Decimal("0.00")
    assert invoice.total_amount == Decimal("840.00")
    assert [item.description for item in invoice.line_items] == ["A4 recycled paper, cartons", "Laser toner cartridge, black"]
    result = validate_invoice(invoice)
    assert result.status == "validated"
    assert "totals:reconcile" in result.checks_passed
    response = process_document(path.read_bytes(), path.name)
    assert response.metadata.extraction_mode == "demo"
    assert response.metadata.text_source == "digital_pdf"
    assert response.invoice.total_amount == Decimal("840.00")
    assert response.validation.status == "validated"
    payload = response.model_dump(mode="json")
    assert payload["invoice"]["invoice_date"] == "2026-10-01"
    assert payload["invoice"]["total_amount"] == "840.00"


@pytest.mark.parametrize("number", ["INV-ALPHA-7", "2026/INV/042"])
def test_demo_parser_handles_common_labels_dates_and_currency(number):
    text = f"""From: Northwind Paper Ltd.
Invoice No.: {number}
Date of Issue: 17 October 2026
Payment Due Date: 2026-11-16
Bill To: Example Retail LLC
Invoice Currency: USD
Sub Total: USD 1,250.00
VAT Amount: USD 100.00
Discount Amount: USD 25.00
Grand Total: USD 1,325.00"""
    invoice = demo_extract(text)
    assert invoice.supplier_name == "Northwind Paper Ltd."
    assert invoice.invoice_number == number
    assert str(invoice.invoice_date) == "2026-10-17"
    assert str(invoice.due_date) == "2026-11-16"
    assert invoice.customer_name == "Example Retail LLC"
    assert invoice.currency == "USD"
    assert invoice.subtotal == Decimal("1250.00")
    assert invoice.tax_amount == Decimal("100.00")
    assert invoice.discount == Decimal("25.00")
    assert invoice.total_amount == Decimal("1325.00")
    assert validate_invoice(invoice).status == "validated"


def test_demo_parser_leaves_optional_fields_missing_and_flags_ambiguous_date():
    invoice = demo_extract("Supplier: Plain Goods\nInvoice Number: P-4\nInvoice Date: 03/04/2026\nTotal: 19.99")
    assert invoice.supplier_name == "Plain Goods"
    assert invoice.total_amount == Decimal("19.99")
    assert invoice.currency is None
    assert invoice.due_date is None
    assert invoice.discount is None
    assert invoice.invoice_date is None
    assert invoice.field_status["invoice_date"].value == "uncertain"
    assert validate_invoice(invoice).status == "review_required"


def test_inconsistent_extracted_total_is_preserved_for_review():
    invoice = demo_extract("Supplier: Northwind\nInvoice Number: N-9\nInvoice Date: 2026-05-04\nCurrency: EUR\nSubtotal: 100.00\nVAT (5%): 5.00\nTotal Due: 110.00")
    original_values = (invoice.subtotal, invoice.tax_amount, invoice.total_amount)
    result = validate_invoice(invoice)
    assert "totals:reconcile" in result.checks_failed
    assert (invoice.subtotal, invoice.tax_amount, invoice.total_amount) == original_values
    assert invoice.total_amount == Decimal("110.00")


def test_conflicting_labelled_totals_are_not_guessed():
    invoice = demo_extract("Supplier: Northwind\nInvoice Number: N-10\nInvoice Date: 2026-05-04\nGrand Total: 105.00\nAmount Due: 80.00")
    assert invoice.total_amount is None
    assert invoice.field_status["total_amount"].value == "uncertain"


def test_demo_parser_reads_simple_inline_line_item_table():
    invoice = demo_extract("""Supplier: Paper Co
Invoice Number: PC-1
Invoice Date: 2026-05-04
Subtotal: 20.00
Tax: 1.00
Total: 21.00
Description     Qty     Unit Price     Amount
Notebook        2       10.00          20.00""")
    assert len(invoice.line_items) == 1
    assert invoice.line_items[0].description == "Notebook"
    assert invoice.line_items[0].quantity == Decimal("2")
    assert invoice.line_items[0].unit_price == Decimal("10.00")
    assert invoice.line_items[0].line_total == Decimal("20.00")


def test_demo_parser_handles_invoice_heading_sections_and_combined_supplier_trn():
    text = """NORTHSTAR OFFICE SUPPLIES LLC
Dubai, United Arab Emirates
TRN: 100598765400003 | Tel: +971 4 555 0184 | Email: billing@example.test
TAX INVOICE
INVOICE NO.
NS-2026-1042
Invoice Date: 2026-10-12
Due Date: 2026-11-11
Currency: AED
BILL TO
Cedar & Finch Design Studio FZ-LLC
TRN: 100412398700003
ITEM DETAILS
DESCRIPTION
UNIT PRICE
QUANTITY
AMOUNT
Office paper cartons
100.00
10
1000.00
Design notebooks
170.00
2
340.00
Subtotal: AED 1,340.00
VAT (5%):
67.00
Discount: AED 0.00
Total: AED 1,407.00"""
    invoice = demo_extract(text)
    assert invoice.supplier_name == "NORTHSTAR OFFICE SUPPLIES LLC"
    assert invoice.supplier_tax_id == "100598765400003"
    assert invoice.invoice_number == "NS-2026-1042"
    assert str(invoice.invoice_date) == "2026-10-12"
    assert str(invoice.due_date) == "2026-11-11"
    assert invoice.customer_name == "Cedar & Finch Design Studio FZ-LLC"
    assert invoice.customer_tax_id == "100412398700003"
    assert invoice.currency == "AED"
    assert invoice.subtotal == Decimal("1340.00")
    assert invoice.tax_amount == Decimal("67.00")
    assert invoice.discount == Decimal("0.00")
    assert invoice.total_amount == Decimal("1407.00")
    assert len(invoice.line_items) == 2
    result = validate_invoice(invoice)
    assert result.status == "validated"
    assert "totals:reconcile" in result.checks_passed


def test_invoice_sections_do_not_mix_supplier_and_customer_and_accept_other_number():
    text = """BIRCHWAY TECHNOLOGY TRADING LLC
TRN: 100000000000007 | Tel: +971 4 555 0100 | Email: accounts@birchway.test
INVOICE NUMBER: BT-88/2026
Invoice Date: 2026-09-01
Currency: AED
BILL TO:
Orchard Studio FZE
TRN: 100000000000009
Subtotal: 200.00
Tax Amount: AED 10.00
Total Due: AED 210.00"""
    invoice = demo_extract(text)
    assert invoice.supplier_name == "BIRCHWAY TECHNOLOGY TRADING LLC"
    assert invoice.supplier_tax_id == "100000000000007"
    assert invoice.invoice_number == "BT-88/2026"
    assert invoice.customer_name == "Orchard Studio FZE"
    assert invoice.customer_tax_id == "100000000000009"
    assert invoice.tax_amount == Decimal("10.00")
    assert invoice.total_amount == Decimal("210.00")


def test_line_items_recover_column_major_pdf_text_with_reordered_headers():
    invoice = demo_extract("""Supplier: Cedar Supply LLC
Invoice Number: CS-7
Invoice Date: 2026-09-01
ITEMS
DESCRIPTION
AMOUNT
UNIT PRICE
QUANTITY
Widget Alpha
Widget Beta
30.00
40.00
10.00
20.00
3
2
Subtotal: 50.00
Tax: 0.00
Total: 50.00""")
    assert [(item.description, item.quantity, item.unit_price, item.line_total) for item in invoice.line_items] == [
        ("Widget Alpha", Decimal("3"), Decimal("10.00"), Decimal("30.00")),
        ("Widget Beta", Decimal("2"), Decimal("20.00"), Decimal("40.00")),
    ]


def test_party_headings_ignore_disclaimers_and_capture_bill_to_customer_label():
    invoice = demo_extract("""SYNTHETIC TEST DOCUMENT — NOT A REAL INVOICE
NORTHSTAR OFFICE SUPPLIES LLC
Dubai, United Arab Emirates
INVOICE NO.: NS-2026-1042
Invoice Date: 2026-10-12
Currency: AED
BILL TO
Customer:
Cedar & Finch Design Studio FZ-LLC
TRN: 100412398700003
ITEMS
Subtotal: 1,340.00
VAT: 67.00
Total: 1,407.00
SYNTHETIC TEST DOCUMENT — NOT A REAL INVOICE
InvoiceIQ demo fixture | Fictional supplier, buyer and transaction""")
    assert invoice.supplier_name == "NORTHSTAR OFFICE SUPPLIES LLC"
    assert invoice.supplier_name != "SYNTHETIC TEST DOCUMENT — NOT A REAL INVOICE"
    assert invoice.customer_name == "Cedar & Finch Design Studio FZ-LLC"


def test_line_item_tax_rate_is_separate_from_tax_amount():
    invoice = demo_extract("""Supplier: Northstar Office Supplies LLC
Invoice Number: NS-2026-1042
Invoice Date: 2026-10-12
Currency: AED
BILL TO
Example Buyer LLC
ITEMS
DESCRIPTION | QTY | UNIT PRICE | TAX RATE | AMOUNT
Office paper cartons | 10 | 100.00 | 5% | 1,000.00
Design notebooks | 2 | 170.00 | 5% | 340.00
Desk organizers | 3 | 50.00 | 5% | 150.00
Subtotal: 1,490.00
Tax Amount: 74.50
Total: 1,564.50""")
    assert [item.tax_rate for item in invoice.line_items] == [Decimal("5"), Decimal("5"), Decimal("5")]
    assert all(item.tax is None for item in invoice.line_items)
    assert [item.line_total for item in invoice.line_items] == [Decimal("1000.00"), Decimal("340.00"), Decimal("150.00")]
    result = validate_invoice(invoice)
    assert result.status == "validated"


def test_generated_digital_pdf_reaches_validated_invoice_with_party_names_and_rates():
    import fitz

    text = """SYNTHETIC TEST DOCUMENT — NOT A REAL INVOICE
NORTHSTAR OFFICE SUPPLIES LLC
INVOICE NO.: NS-2026-1042
Invoice Date: 2026-10-12
Due Date: 2026-11-11
Currency: AED
BILL TO
Customer: Cedar & Finch Design Studio FZ-LLC
ITEMS
DESCRIPTION | QTY | UNIT PRICE | TAX RATE | AMOUNT
Office paper cartons | 10 | 100.00 | 5% | 1,000.00
Design notebooks | 2 | 150.00 | 5% | 300.00
Desk organizers | 2 | 20.00 | 5% | 40.00
Subtotal: AED 1,340.00
VAT (5%): AED 67.00
Discount: AED 0.00
Total: AED 1,407.00
SYNTHETIC TEST DOCUMENT — NOT A REAL INVOICE"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 40), text, fontsize=7)
    payload = doc.tobytes()
    result = process_document(payload, "identity-and-tax-rate-regression.pdf")

    assert result.metadata.text_source == "digital_pdf"
    assert result.invoice.supplier_name == "NORTHSTAR OFFICE SUPPLIES LLC"
    assert result.invoice.customer_name == "Cedar & Finch Design Studio FZ-LLC"
    assert result.invoice.invoice_number == "NS-2026-1042"
    assert result.invoice.subtotal == Decimal("1340.00")
    assert result.invoice.tax_amount == Decimal("67.00")
    assert result.invoice.total_amount == Decimal("1407.00")
    assert [item.tax_rate for item in result.invoice.line_items] == [Decimal("5"), Decimal("5"), Decimal("5")]
    assert result.validation.status == "validated"


def test_tax_percent_in_a_generic_tax_column_is_not_treated_as_money():
    invoice = demo_extract("""Supplier: Orchard Supply Ltd
Invoice Number: OS-7
Invoice Date: 2026-10-12
ITEMS
DESCRIPTION | QTY | UNIT PRICE | VAT | AMOUNT
Paper | 2 | 10.00 | 5% | 20.00""")
    assert len(invoice.line_items) == 1
    assert invoice.line_items[0].tax_rate == Decimal("5")
    assert invoice.line_items[0].tax is None


def test_tool_arguments_allowlist_and_results():
    invoice = sample()
    result = run_review_tools({"invoice": invoice.model_dump(mode="json"), "actions": ["calculate_totals", "flag_missing_fields"]})
    assert result["tool_results"][0]["result"]["computed_total"] == "105.00"
    with pytest.raises(ValueError, match="Unsupported tools"):
        run_review_tools({"invoice": invoice.model_dump(mode="json"), "actions": ["shell"]})
    assert MAX_TOOL_ROUNDS == 2


def test_fixture_set_preserves_legacy_labels_and_adds_generalization_cases():
    path = Path(__file__).parents[1] / "evaluation" / "fixtures.jsonl"
    cases = [json.loads(line.lstrip("\ufeff")) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(cases) == 46
    assert any(not item["known_valid"] for item in cases)
    legacy = [item for item in cases if item["cohort"] == "legacy_customer_missing"]
    added = [item for item in cases if item["cohort"] == "customer_generalization"]
    assert len(legacy) == 30
    assert sum(item["known_valid"] and item["expected_status"] == "review_required" for item in legacy) == 22
    assert sum(item["expected_status"] == "validated" for item in added) == 8
    assert sum(item["expected_status"] == "review_required" for item in added) == 8

