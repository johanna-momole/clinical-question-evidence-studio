"""Question Builder — parse, review, and approve a clinical research question.

Page 2 of the Clinical Question-Evidence Studio.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from app.components.ui_helpers import (
    SESSION_KEY_PHENOTYPE,
    SESSION_KEY_QUESTION,
    SESSION_KEY_RUN_ID,
    ambiguity_severity_order,
    format_ambiguity_label,
    new_run_id,
    question_to_json_bytes,
    validate_pico_completeness,
)
from src.question_parser.service import get_question_service

st.set_page_config(
    page_title="Question Builder | Clinical Q-E Studio",
    page_icon="📋",
    layout="wide",
)

# ──────────────────────────────────────────────
# Minimal CSS
# ──────────────────────────────────────────────
st.markdown(
    """
<style>
.severity-high  { color: #c0392b; font-weight: bold; }
.severity-medium { color: #e67e22; font-weight: bold; }
.severity-low   { color: #27ae60; font-weight: bold; }
.approved-pill  { background: #27ae60; color: white; padding: 2px 10px;
                  border-radius: 12px; font-size: 0.82em; }
.demo-banner    { background: #fff3cd; border-left: 4px solid #ffc107;
                  padding: 8px 14px; border-radius: 4px; margin-bottom: 12px; }
</style>
""",
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# Header
# ──────────────────────────────────────────────
st.title("📋 Question Builder")
st.markdown(
    "Select one of the three curated demo questions **or** enter your own text. "
    "Review the PICO breakdown, address ambiguity flags, then **Approve** to continue to "
    "the Phenotype Builder."
)

st.markdown(
    '<div class="demo-banner">🔬 <strong>Demo mode active</strong> — all parsing is deterministic. '
    "No live LLM API call is made. PICO for custom text is a placeholder only.</div>",
    unsafe_allow_html=True,
)

service = get_question_service()
curated = service.get_curated_questions()

# ──────────────────────────────────────────────
# Input section
# ──────────────────────────────────────────────
st.header("1 · Select or Enter a Question")

curated_labels = {
    "q-sglt2-ckd-t2dm-001": "Curated Q1 — SGLT2 cohort definition & evidence search",
    "q-sglt2-ckd-data-elem-001": "Curated Q2 — Data elements for SGLT2 initiation study",
    "q-sglt2-ckd-outcome-eval-001": "Curated Q3 — Outcome evaluation cohort template",
    "__custom__": "Enter my own question (demo placeholder — not a clinical assessment)",
}

choice = st.radio(
    "Choose a question source:",
    options=list(curated_labels.keys()),
    format_func=lambda k: curated_labels[k],
    key="qb_choice",
)

custom_text = ""
if choice == "__custom__":
    custom_text = st.text_area(
        "Your question:",
        placeholder="e.g. Among adults with heart failure, does sacubitril/valsartan …",
        height=90,
        key="qb_custom_text",
    )

# ──────────────────────────────────────────────
# Parse
# ──────────────────────────────────────────────
parse_disabled = choice == "__custom__" and not custom_text.strip()
if st.button("Parse Question", disabled=parse_disabled, type="primary"):
    with st.spinner("Parsing…"):
        if choice == "__custom__":
            result = service.parse(custom_text)
        else:
            result = service.parse("", question_id=choice)
    st.session_state["qb_parse_result"] = result
    # Clear any previously approved question if input changed
    if SESSION_KEY_QUESTION in st.session_state:
        prev = st.session_state[SESSION_KEY_QUESTION]
        if prev.id != result.question.id:
            del st.session_state[SESSION_KEY_QUESTION]
            st.session_state.pop(SESSION_KEY_PHENOTYPE, None)

# ──────────────────────────────────────────────
# Results
# ──────────────────────────────────────────────
if "qb_parse_result" not in st.session_state:
    st.info("Select a question source and click **Parse Question** to begin.")
    st.stop()

result = st.session_state["qb_parse_result"]
question = result.question

if result.warnings:
    for w in result.warnings:
        st.warning(w)

if not result.is_supported_question:
    st.error(
        "This question is outside the curated demo scope. "
        "PICO fields below are **placeholders only** — not a clinical assessment. "
        "Approval is disabled for unsupported questions."
    )

# ──────────────────────────────────────────────
# PICO display
# ──────────────────────────────────────────────
st.header("2 · PICO Breakdown")

pico = question.pico
col1, col2 = st.columns(2)
with col1:
    st.subheader("Population (P)")
    st.write(pico.population)
    if pico.population_detail:
        st.caption(pico.population_detail)

    st.subheader("Intervention (I)")
    st.write(pico.intervention)

    st.subheader("Comparator (C)")
    st.write(pico.comparator or "_None specified_")

with col2:
    st.subheader("Outcomes (O)")
    for o in pico.outcomes:
        st.write(f"• {o}")

    st.subheader("Timeframe (T)")
    st.write(pico.timeframe or "_Not specified_")

    st.subheader("Study Intent")
    st.write(pico.study_intent or "_Not specified_")

# ──────────────────────────────────────────────
# Ambiguity flags
# ──────────────────────────────────────────────
if question.ambiguity_flags:
    st.header("3 · Ambiguity Flags")
    flags = sorted(question.ambiguity_flags, key=lambda f: ambiguity_severity_order(f.severity))
    for flag in flags:
        label = format_ambiguity_label(flag.severity)
        with st.expander(f"[{label}] {flag.field} — {flag.description[:70]}…"):
            st.markdown(f"**Field:** `{flag.field}`")
            st.markdown(f"**Issue:** {flag.description}")
            st.markdown(f"**Suggestion:** {flag.suggested_clarification}")

# ──────────────────────────────────────────────
# Clarifying questions
# ──────────────────────────────────────────────
if question.clarifying_questions:
    st.header("4 · Clarifying Questions")
    for i, cq in enumerate(question.clarifying_questions, 1):
        st.markdown(f"{i}. {cq}")

# ──────────────────────────────────────────────
# Approval
# ──────────────────────────────────────────────
st.header("5 · Approve Question")

pico_dict = pico.model_dump()
pico_errors = validate_pico_completeness(pico_dict)

already_approved = (
    st.session_state.get(SESSION_KEY_QUESTION) is not None
    and st.session_state[SESSION_KEY_QUESTION].id == question.id
)

if already_approved:
    st.success("✅ Question is approved and stored in session.")
elif pico_errors:
    for e in pico_errors:
        st.warning(e)
    st.button("Approve Question", disabled=True)
elif not result.is_supported_question:
    st.button("Approve Question", disabled=True, help="Approval disabled for unsupported questions")
else:
    if st.button("Approve Question", type="primary"):
        run_id = new_run_id()
        # Set status to approved on the question object by rebuilding it
        approved_q = question.model_copy(update={"status": "approved"})
        st.session_state[SESSION_KEY_QUESTION] = approved_q
        st.session_state[SESSION_KEY_RUN_ID] = run_id
        st.session_state.pop(SESSION_KEY_PHENOTYPE, None)
        st.success(f"✅ Question approved — run ID `{run_id}`")
        st.info("Proceed to **Phenotype Builder** to view the computable phenotype.")

# ──────────────────────────────────────────────
# Download
# ──────────────────────────────────────────────
st.divider()
st.download_button(
    label="⬇ Download question JSON",
    data=question_to_json_bytes(question),
    file_name=f"question_{question.id}.json",
    mime="application/json",
)

# ──────────────────────────────────────────────
# Disclaimer
# ──────────────────────────────────────────────
with st.expander("Disclaimer"):
    st.markdown(
        "This application uses **entirely synthetic patient data** generated for portfolio "
        "demonstration purposes. It is not clinically validated, has not been deployed in a "
        "healthcare organization, and must not be used for patient care or clinical decisions. "
        "Terminology mappings are candidate suggestions requiring human clinical review."
    )
