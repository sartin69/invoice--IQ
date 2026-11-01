from invoiceiq.mcp_server import calculate_invoice_total


def test_mcp_calculation_function():
    assert calculate_invoice_total(100, 5, 2) == {"calculated_total": "103"}

