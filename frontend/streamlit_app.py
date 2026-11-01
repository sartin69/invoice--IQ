import json
import os
import requests
import streamlit as st

API = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
st.set_page_config(page_title="InvoiceIQ", page_icon="🧾", layout="wide")
st.title("InvoiceIQ")
st.caption("AI powered invoice extraction with deterministic financial checks")
try:
    health = requests.get(f"{API}/health", timeout=3).json()
    mode = health["mode"]
except Exception:
    health = None
    mode = "API unavailable"
st.info(f"Processing mode: **{mode}** · API: `{API}`")
page = st.sidebar.radio("Workspace", ["Process invoice", "Evaluation", "About & limitations"])

if page == "Process invoice":
    st.subheader("Upload an invoice")
    uploaded = st.file_uploader("PDF, PNG, or JPEG", type=["pdf", "png", "jpg", "jpeg"], max_upload_size=15)
    if uploaded and st.button("Extract and validate", type="primary", disabled=health is None):
        with st.spinner("Reading document and checking invoice fields…"):
            try:
                result = requests.post(f"{API}/extract", files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)}, timeout=120)
                result.raise_for_status()
                payload = result.json()
                st.session_state["result"] = payload
            except requests.RequestException as exc:
                st.error(f"API request failed: {exc}")
    payload = st.session_state.get("result")
    if payload:
        invoice = payload["invoice"]
        validation = payload["validation"]
        st.subheader("Extracted invoice")
        c1, c2, c3 = st.columns(3)
        c1.metric("Supplier", invoice.get("supplier_name") or "Missing")
        c2.metric("Invoice number", invoice.get("invoice_number") or "Missing")
        c3.metric("Total", f"{invoice.get('currency') or ''} {invoice.get('total_amount') or 'Missing'}")
        st.write({key: invoice.get(key) for key in ["supplier_address", "supplier_tax_id", "invoice_date", "due_date", "customer_name", "customer_tax_id", "currency", "subtotal", "tax_amount", "discount", "payment_terms"]})
        if invoice.get("line_items"):
            st.dataframe(invoice["line_items"], use_container_width=True)
        st.subheader(f"Validation: {validation['status']}")
        if validation["human_review_required"]:
            st.warning("Human review required. This system does not approve payments or change invoice values.")
        for warning in validation["warnings"]:
            st.warning(warning)
        for error in validation["errors"]:
            st.error(error)
        st.caption(f"Source: {payload['metadata']['text_source']} · Mode: {payload['metadata']['extraction_mode']} · {payload['metadata']['elapsed_ms']} ms")
        raw = json.dumps(payload, indent=2)
        st.download_button("Download validated JSON", raw, file_name="invoiceiq-result.json", mime="application/json")
        with st.expander("Raw API response"):
            st.code(raw, language="json")

elif page == "Evaluation":
    st.subheader("Measured fixture evaluation")
    try:
        summary = requests.get(f"{API}/evaluation/summary", timeout=5).json()
        if summary.get("status") == "not_run":
            st.info(summary["message"])
        else:
            st.caption(f"Dataset: {summary['dataset_size']} synthetic text fixtures · mode: {summary['mode']}")
            for name, config in summary["configurations"].items():
                st.markdown(f"#### {name.title()} configuration")
                classification = config["validation_classification"]
                financial = config["financial_reconciliation"]
                complete = config["complete_invoice_accuracy"]
                c1, c2, c3 = st.columns(3)
                c1.metric("Schema validity", f"{config['schema_validity_rate']:.1%}")
                c2.metric("Processing success", f"{config['end_to_end_success_rate']:.1%}")
                c3.metric("Complete invoice accuracy", f"{complete['accuracy']:.1%}" if complete["accuracy"] is not None else "N/A")
                c1, c2, c3 = st.columns(3)
                c1.metric("Financial reconciliation accuracy", f"{financial['accuracy']:.1%}" if financial["accuracy"] is not None else "N/A")
                c2.metric("False acceptance rate", f"{classification['false_acceptance_rate']:.1%}" if classification["false_acceptance_rate"] is not None else "N/A")
                c3.metric("False review rate", f"{classification['false_review_rate']:.1%}" if classification["false_review_rate"] is not None else "N/A")
                st.caption(
                    f"Validation classification: {classification['evaluated']} fixtures · "
                    f"review detection {classification['review_detection_rate']:.1%} · "
                    f"valid acceptance {classification['valid_acceptance_rate']:.1%}"
                )
                if config["legacy_label_conflicts"]:
                    st.warning(
                        f"{config['legacy_label_conflicts']} legacy fixtures were originally labeled valid "
                        "but omit the now-required customer name. Their original labels are retained for audit; "
                        "current expected outcomes require review."
                    )
                st.dataframe(config["field_exact_or_numeric_accuracy"], use_container_width=True)
                st.dataframe(config["cohort_counts"], use_container_width=True)
                st.caption(config["note"])
    except requests.RequestException:
        st.error("Start the API to load the evaluation summary.")

else:
    st.subheader("About InvoiceIQ")
    st.write("InvoiceIQ extracts invoice fields from PDF or image documents, then independently validates completeness and financial arithmetic.")
    st.markdown("""**Architecture:** Streamlit → FastAPI → PDF text extraction / OCR → structured extractor → Pydantic schema → deterministic validation.

**Mode:** The banner reports whether the API uses demo parsing or a configured OpenAI model. Demo mode makes no external provider calls. Live mode sends extracted document text to OpenAI.

**Limitations:** This is an assistive prototype, not accounting advice or a payment approval system. OCR requires the Tesseract executable. Demo extraction uses deterministic label and simple table heuristics; it is not an LLM or general-purpose invoice understanding model. Ambiguity and arithmetic discrepancies require human review. No production privacy/compliance claim is made.""")

