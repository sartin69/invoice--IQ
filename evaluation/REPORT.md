# InvoiceIQ synthetic evaluation

Generated with `python -m invoiceiq.evaluation` on 2026-10-13. This evaluates the deterministic demo parser on synthetic text fixtures only. It is not a real-world, OCR, or LLM benchmark.

## Dataset audit

The set contains 46 cases: the original 30 plus 8 complete valid and 8 invalid customer-generalization cases. The original `known_valid` values are preserved. All 30 original texts omit the customer name required by current validation; 22 were historically labeled valid under the earlier rules. Their current expected status is therefore `review_required`, and the evaluation reports the 22 label conflicts rather than counting them as valid acceptances.

Current expected statuses: 8 `validated`, 38 `review_required`. The added cohort has 8 valid and 8 review-required examples across `BILL TO`, inline `Customer:`, next-line customer labels, customer address/tax-ID boundaries, missing or ambiguous names, inconsistent totals, dates, and line arithmetic.

## Results

| Metric | Baseline | Improved |
|---|---:|---:|
| Schema-valid / processing success | 100% / 100% | 100% / 100% |
| Complete-invoice accuracy | 28.26% (13/46) | 100% (46/46) |
| Financial reconciliation accuracy | 86.96% (40/46) | 100% (46/46) |
| False reconciliation acceptance | 0/7 (0%) | 0/7 (0%) |
| False reconciliation rejection | 6/39 (15.38%) | 0/39 (0%) |
| False acceptance of review-required invoices | 1/38 (2.63%) | 0/38 (0%) |
| False review of valid invoices | 0/8 (0%) | 0/8 (0%) |
| Review-required detection | 97.37% (37/38) | 100% (38/38) |
| Valid invoice acceptance | 100% (8/8) | 100% (8/8) |
| Evaluation exceptions | 0 | 0 |

Improved field-level exact/numeric accuracy was 100% for supplier/customer names and tax IDs, invoice number and dates, currency, subtotal, tax amount, discount, total, and line items. Baseline accuracy was 100% on those same fields except due date (32.61%) and discount (80.43%); the baseline configuration deliberately suppresses those two values. Both configurations achieved 100% customer-name accuracy on these fixtures.

The improved parser's 100% results are on this small, synthetic dataset and should not be interpreted as expected production accuracy. The original fixtures mirror simple labeled text, and the new cases are designed coverage rather than a statistically representative sample. The browser interface and OCR/scanned-PDF performance were not evaluated by this run.
