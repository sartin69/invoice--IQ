"""Reproducible local fixture evaluation; demo-parser metrics are not LLM metrics."""
import json
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from invoiceiq.models import Invoice
from invoiceiq.services.extraction import demo_extract
from invoiceiq.services.validation import validate_invoice

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evaluation" / "fixtures.jsonl"
RESULTS = ROOT / "evaluation" / "results"
FIELDS = (
    "supplier_name", "customer_name", "supplier_tax_id", "customer_tax_id",
    "invoice_number", "invoice_date", "due_date", "currency", "subtotal",
    "tax_amount", "discount", "total_amount", "line_items",
)
NUMERIC = {"subtotal", "tax_amount", "discount", "total_amount"}
OPTIONAL_MISSING_FIELDS = set(FIELDS) - {"supplier_name", "customer_name", "invoice_number", "invoice_date", "total_amount", "line_items"}
TOLERANCE = Decimal("0.02")


def _expected_status(case: dict) -> str:
    """Use the current explicit outcome label, with a safe legacy fallback."""
    value = case.get("expected_status")
    if value in {"validated", "review_required", "failed"}:
        return value
    return "validated" if case.get("known_valid") else "review_required"


def _field_matches(field: str, expected, actual) -> bool:
    if field in NUMERIC:
        if expected is None or actual is None:
            return expected is None and actual is None
        return abs(Decimal(str(actual)) - Decimal(str(expected))) <= TOLERANCE
    if field in {"invoice_date", "due_date"}:
        return str(actual) == expected if expected is not None else actual is None
    if field == "line_items":
        return actual == (expected or [])
    return actual == expected


def _expected_reconciliation(expected: dict) -> bool | None:
    subtotal = expected.get("subtotal")
    tax = expected.get("tax_amount")
    total = expected.get("total_amount")
    if subtotal is None or tax is None or total is None:
        return None
    discount = Decimal(str(expected.get("discount") or "0"))
    return abs(Decimal(str(subtotal)) + Decimal(str(tax)) - discount - Decimal(str(total))) <= TOLERANCE


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _new_confusion() -> dict[str, int]:
    return {"true_review": 0, "false_acceptance": 0, "false_review": 0, "true_acceptance": 0}


def _evaluate_cases(cases: list[dict], configuration: str) -> dict:
    field_stats = {field: {"correct": 0, "evaluated": 0, "accuracy": 0.0} for field in FIELDS}
    schema_valid = succeeded = complete_correct = complete_evaluated = 0
    missing_tp = missing_fp = missing_fn = 0
    confusion = _new_confusion()
    financial = {"correct": 0, "evaluated": 0, "expected_reconciled": 0, "expected_discrepant": 0,
                 "false_reconciliation_acceptance": 0, "false_reconciliation_rejection": 0}
    latency_ms: list[float] = []
    failures: list[dict[str, str]] = []
    cohort_counts: dict[str, dict[str, int]] = {}

    for case in cases:
        cohort = case.get("cohort", "unclassified")
        cohort_counts.setdefault(cohort, {"fixtures": 0, "expected_validated": 0, "expected_review": 0})
        cohort_counts[cohort]["fixtures"] += 1
        expected_status = _expected_status(case)
        expects_review = expected_status != "validated"
        cohort_counts[cohort]["expected_review" if expects_review else "expected_validated"] += 1
        started = perf_counter()
        try:
            invoice = demo_extract(case["text"], configuration)
            invoice = Invoice.model_validate(invoice.model_dump())
            schema_valid += 1
            succeeded += 1
            expected = case.get("expected", {})
            normalized_expected = {field: expected.get(field) for field in FIELDS}
            actual_values = invoice.model_dump(mode="json")
            matches: list[bool] = []
            for field in FIELDS:
                expected_value = normalized_expected[field]
                actual_value = actual_values[field]
                correct = _field_matches(field, expected_value, actual_value)
                field_stats[field]["evaluated"] += 1
                field_stats[field]["correct"] += int(correct)
                matches.append(correct)
                if field in OPTIONAL_MISSING_FIELDS:
                    expected_missing = expected_value is None
                    actual_missing = actual_value is None
                    missing_tp += int(expected_missing and actual_missing)
                    missing_fp += int(not expected_missing and actual_missing)
                    missing_fn += int(expected_missing and not actual_missing)
            complete_evaluated += 1
            complete_correct += int(all(matches))

            result = validate_invoice(invoice)
            actual_review = result.human_review_required
            if expects_review and actual_review:
                confusion["true_review"] += 1
            elif expects_review and not actual_review:
                confusion["false_acceptance"] += 1
            elif not expects_review and actual_review:
                confusion["false_review"] += 1
            else:
                confusion["true_acceptance"] += 1

            expected_balanced = _expected_reconciliation(expected)
            if expected_balanced is not None:
                financial["evaluated"] += 1
                actual_balanced = "totals:reconcile" in result.checks_passed
                financial["correct"] += int(actual_balanced == expected_balanced)
                financial["expected_reconciled"] += int(expected_balanced)
                financial["expected_discrepant"] += int(not expected_balanced)
                financial["false_reconciliation_acceptance"] += int(not expected_balanced and actual_balanced)
                financial["false_reconciliation_rejection"] += int(expected_balanced and not actual_balanced)
            latency_ms.append((perf_counter() - started) * 1000)
        except Exception as exc:
            failures.append({"id": str(case.get("id", "unknown")), "error": type(exc).__name__})

    for stats in field_stats.values():
        stats["accuracy"] = _ratio(stats["correct"], stats["evaluated"])
    review_cases = confusion["true_review"] + confusion["false_acceptance"]
    valid_cases = confusion["true_acceptance"] + confusion["false_review"]
    classified = sum(confusion.values())
    return {
        "field_exact_or_numeric_accuracy": field_stats,
        "complete_invoice_accuracy": {
            "correct": complete_correct,
            "evaluated": complete_evaluated,
            "accuracy": _ratio(complete_correct, complete_evaluated),
        },
        "financial_reconciliation": {
            **financial,
            "accuracy": _ratio(financial["correct"], financial["evaluated"]),
            "expected_reconciled_rate": _ratio(financial["expected_reconciled"], financial["evaluated"]),
        },
        "validation_classification": {
            **confusion,
            "evaluated": classified,
            "accuracy": _ratio(confusion["true_review"] + confusion["true_acceptance"], classified),
            "false_acceptance_rate": _ratio(confusion["false_acceptance"], review_cases),
            "false_review_rate": _ratio(confusion["false_review"], valid_cases),
            "review_detection_rate": _ratio(confusion["true_review"], review_cases),
            "valid_acceptance_rate": _ratio(confusion["true_acceptance"], valid_cases),
        },
        "missing_field_detection": {
            "precision": _ratio(missing_tp, missing_tp + missing_fp),
            "recall": _ratio(missing_tp, missing_tp + missing_fn),
            "true_positive": missing_tp,
            "false_positive": missing_fp,
            "false_negative": missing_fn,
        },
        "schema_validity_rate": _ratio(schema_valid, len(cases)),
        "end_to_end_success_rate": _ratio(succeeded, len(cases)),
        "cohort_counts": cohort_counts,
        "legacy_label_conflicts": sum(bool(case.get("known_valid")) and _expected_status(case) != "validated" for case in cases),
        "evaluation_failures": failures,
        "average_latency_ms": round(sum(latency_ms) / len(latency_ms), 3) if latency_ms else None,
        "api_cost_usd": None,
        "note": "Synthetic text-fixture results for the deterministic demo parser only; not real-world, OCR, or LLM accuracy. Original known_valid labels are retained for audit, while current validation scores use expected_status.",
    }


def run_evaluation() -> dict:
    cases = [json.loads(row.lstrip("\ufeff")) for row in FIXTURES.read_text(encoding="utf-8").splitlines() if row.strip()]
    output = {
        "mode": "deterministic_demo_parser",
        "dataset_size": len(cases),
        "expected_outcomes": {status: sum(_expected_status(case) == status for case in cases) for status in ("validated", "review_required", "failed")},
        "positive_class": "invoice requires human review",
        "configurations": {config: _evaluate_cases(cases, config) for config in ("baseline", "improved")},
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    target = RESULTS / "latest.json"
    target.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def load_latest_summary() -> dict | None:
    path = RESULTS / "latest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


if __name__ == "__main__":
    print(json.dumps(run_evaluation(), indent=2))
