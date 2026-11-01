from fastapi.testclient import TestClient
from invoiceiq.api import app

client = TestClient(app)


def test_health_reports_demo_mode_by_default():
    assert client.get("/health").json()["status"] == "ok"


def test_validate_route():
    payload = {"invoice": {"supplier_name": "A", "customer_name": "Buyer LLC", "invoice_number": "1", "invoice_date": "2026-01-01", "currency": "AED", "subtotal": "10", "tax_amount": "0.5", "total_amount": "10.5"}}
    response = client.post("/validate", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "validated"


def test_extract_route_accepts_digital_pdf():
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Supplier: Acme LLC\nInvoice Number: A-3\nInvoice Date: 2026-02-01\nDue Date: 2026-03-01\nCurrency: AED\nSubtotal: 10.00\nTax: 0.50\nTotal: 10.50")
    data = doc.tobytes()
    response = client.post("/extract", files={"file": ("invoice.pdf", data, "application/pdf")})
    assert response.status_code == 200
    assert response.json()["invoice"]["supplier_name"] == "Acme LLC"
    assert response.json()["metadata"]["text_source"] == "digital_pdf"


def test_extract_route_recovers_customer_name_before_customer_trn():
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), """NORTHWIND SUPPLY LLC
Invoice Number: NW-504
Invoice Date: 2026-10-12
Currency: AED
BILL TO
Customer: Cedar Grove Design FZE
Customer Address: Office 8, Business Bay
Customer TRN: 100123456700003
Subtotal: 100.00
VAT: 5.00
Total: 105.00""")
    response = client.post("/extract", files={"file": ("invoice.pdf", doc.tobytes(), "application/pdf")})
    assert response.status_code == 200
    body = response.json()
    assert body["invoice"]["supplier_name"] == "NORTHWIND SUPPLY LLC"
    assert body["invoice"]["customer_name"] == "Cedar Grove Design FZE"
    assert body["invoice"]["customer_tax_id"] == "100123456700003"
    assert body["validation"]["status"] == "validated"


def test_extract_rejects_bad_extension():
    response = client.post("/extract", files={"file": ("invoice.docx", b"x", "application/octet-stream")})
    assert response.status_code == 400

