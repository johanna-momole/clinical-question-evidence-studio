"""Phenotype Builder — review and annotate the computable phenotype for an approved question.

Page 3 of the Clinical Question-Evidence Studio.
Requires an approved question in session state (from Question Builder).
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
    calculate_review_stats,
    concept_display_name,
    mapping_review_summary,
    phenotype_to_json_bytes,
)
from src.phenotypes.service import get_phenotype_service

st.set_page_config(
    page_title="Phenotype Builder | Clinical Q-E Studio",
    page_icon="🧬",
    layout="wide",
)

st.markdown(
    """
<style>
.candidate-badge  { background:#f39c12; color:white; padding:2px 8px;
                    border-radius:10px; font-size:0.78em; }
.approved-badge   { background:#27ae60; color:white; padding:2px 8px;
                    border-radius:10px; font-size:0.78em; }
.llm-badge        { background:#8e44ad; color:white; padding:2px 8px;
                    border-radius:10px; font-size:0.78em; }
.unverified-badge { background:#c0392b; color:white; padding:2px 8px;
                    border-radius:10px; font-size:0.78em; }
.demo-banner      { background:#fff3cd; border-left:4px solid #ffc107;
                    padding:8px 14px; border-radius:4px; margin-bottom:12px; }
</style>
""",
    unsafe_allow_html=True,
)

st.title("🧬 Phenotype Builder")
st.markdown(
    "Review the candidate terminology mappings and phenotype rules for the approved question. "
    "All mappings start as **candidate** — they require human clinical review before production use."
)

# ──────────────────────────────────────────────
# Guard: requires approved question
# ──────────────────────────────────────────────
approved_question = st.session_state.get(SESSION_KEY_QUESTION)
if approved_question is None:
    st.warning(
        "⚠ No approved question found in session. "
        "Please approve a question on the **Question Builder** page first."
    )
    if st.button("Go to Question Builder"):
        st.switch_page("pages/2_Question_Builder.py")
    st.stop()

run_id = st.session_state.get(SESSION_KEY_RUN_ID, "—")

st.markdown(
    '<div class="demo-banner">🔬 <strong>Demo mode active</strong> — phenotype is loaded from '
    "a curated fixture file. All terminology mappings are candidate status pending clinical review.</div>",
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# Load phenotype
# ──────────────────────────────────────────────
service = get_phenotype_service()

if SESSION_KEY_PHENOTYPE not in st.session_state:
    with st.spinner("Loading phenotype…"):
        pheno_result = service.build_from_question(approved_question)
    if not pheno_result.is_available:
        st.error(f"Phenotype unavailable: {pheno_result.unavailable_reason}")
        for w in pheno_result.warnings:
            st.warning(w)
        st.stop()
    st.session_state[SESSION_KEY_PHENOTYPE] = pheno_result.phenotype

phenotype = st.session_state[SESSION_KEY_PHENOTYPE]

# ──────────────────────────────────────────────
# Header metrics
# ──────────────────────────────────────────────
st.header("1 · Phenotype Overview")

st.markdown(f"**Name:** {phenotype.name}")
st.markdown(
    f"**Version:** `{phenotype.version}` &nbsp; | &nbsp; **Status:** `{phenotype.review_status}`"
)
st.markdown(f"**Run ID:** `{run_id}`")
st.markdown(f"**Linked question:** `{approved_question.id}`")
st.markdown(f"**Index date:** {phenotype.index_date_definition}")
st.markdown(f"**Lookback:** {phenotype.lookback_period_days} days")

stats = calculate_review_stats(phenotype)
mc1, mc2, mc3, mc4 = st.columns(4)
mc1.metric("Total mappings", stats["total"])
mc2.metric("Candidate", stats["candidate"])
mc3.metric("LLM-suggested", stats["llm_suggested"], help="Require human review")
mc4.metric("Unverified", stats["unverified"], help="No verification_date set")

if stats["unverified"] > 0:
    st.warning(
        f"⚠ {stats['unverified']} mapping(s) have not been verified against an authoritative source "
        "(verification_date = null). Do not use in production without verification."
    )

# ──────────────────────────────────────────────
# Terminology concepts
# ──────────────────────────────────────────────
st.header("2 · Terminology Concepts & Candidate Mappings")
st.caption(
    "All mappings below are **candidate** status — they were derived from published terminology "
    "tables and/or LLM training data. Clinical review is required before production use."
)

for concept in phenotype.concepts:
    with st.expander(
        f"**{concept.name}** ({concept.fhir_resource}) — {mapping_review_summary(concept.mappings)}"
    ):
        st.markdown(f"*Clinical intent:* {concept.clinical_intent}")
        if concept.notes:
            st.info(concept.notes)

        for m in concept.mappings:
            col_code, col_desc, col_badges, col_conf = st.columns([2, 4, 2, 1])
            col_code.code(f"[{m.terminology_system}] {m.code}")
            col_desc.markdown(m.description)
            badges = []
            if m.review_status == "candidate":
                badges.append('<span class="candidate-badge">candidate</span>')
            elif m.review_status == "approved":
                badges.append('<span class="approved-badge">approved</span>')
            if m.is_llm_suggested:
                badges.append('<span class="llm-badge">LLM-suggested</span>')
            if m.verification_date is None:
                badges.append('<span class="unverified-badge">unverified</span>')
            col_badges.markdown(" ".join(badges), unsafe_allow_html=True)
            col_conf.markdown(f"`{m.confidence}`")

            with st.container():
                st.caption(f"Source: {m.source_or_rationale}")
                if m.notes:
                    st.caption(f"Note: {m.notes}")
                if m.verification_date is None:
                    st.caption("Verification: pending — not checked against authoritative source")
                else:
                    st.caption(
                        f"Verified: {m.verification_date} via {m.verification_source or 'unspecified'}"
                    )
            st.divider()

# ──────────────────────────────────────────────
# Rules
# ──────────────────────────────────────────────
st.header("3 · Inclusion & Exclusion Rules")

inc_tab, exc_tab = st.tabs(
    [
        f"Inclusion ({len(phenotype.inclusion_rules)})",
        f"Exclusion ({len(phenotype.exclusion_rules)})",
    ]
)

with inc_tab:
    for rule in phenotype.inclusion_rules:
        with st.expander(f"`{rule.rule_id}` — {rule.label}"):
            st.markdown(f"**Logic:** {rule.logic}")
            st.markdown(
                f"**Concept:** `{rule.concept_id}` ({concept_display_name(rule.concept_id, phenotype)})"
            )
            if rule.lookback_days:
                st.markdown(f"**Lookback:** {rule.lookback_days} days")
            if rule.temporal_relationship:
                st.markdown(f"**Temporal relationship:** `{rule.temporal_relationship}`")
            st.markdown(f"**Required:** {'Yes' if rule.required else 'No'}")

with exc_tab:
    for rule in phenotype.exclusion_rules:
        with st.expander(f"`{rule.rule_id}` — {rule.label}"):
            st.markdown(f"**Logic:** {rule.logic}")
            st.markdown(
                f"**Concept:** `{rule.concept_id}` ({concept_display_name(rule.concept_id, phenotype)})"
            )
            if rule.temporal_relationship:
                st.markdown(f"**Temporal relationship:** `{rule.temporal_relationship}`")
            st.markdown(f"**Required:** {'Yes' if rule.required else 'Yes'}")

# ──────────────────────────────────────────────
# FHIR mappings
# ──────────────────────────────────────────────
st.header("4 · FHIR Resource Mappings")

fhir_data = [
    {
        "Resource": m.resource_type,
        "Element path": m.element_path,
        "System URL": m.terminology_system_url or "",
        "Value/prefix": m.value or "(any)",
        "Concept": m.concept_id,
    }
    for m in phenotype.fhir_mappings
]
st.table(fhir_data)

# ──────────────────────────────────────────────
# Download
# ──────────────────────────────────────────────
st.divider()

# ──────────────────────────────────────────────
# Demo approval gate
# ──────────────────────────────────────────────
st.header("5 · Approve for Synthetic Demo")
st.markdown(
    """
<div class="demo-banner">
<strong>Demo approval</strong> sets <code>review_status = "approved"</code> on the phenotype
structure in session state. This is required before executing the synthetic cohort on Page 4.

<strong>This approval is for portfolio demonstration purposes only.</strong>
It does <em>not</em> certify individual terminology codes, does <em>not</em> constitute clinical
validation, and must <em>not</em> be used for real patient care or decisions.
</div>
""",
    unsafe_allow_html=True,
)

current_status = st.session_state.get(SESSION_KEY_PHENOTYPE, phenotype).review_status
st.markdown(f"**Current phenotype review status:** `{current_status}`")

if current_status != "approved":
    if st.button("Approve phenotype structure for synthetic demo", type="primary"):
        from src.cohorts.service import get_cohort_service

        svc = get_cohort_service()
        approved = svc.approve_phenotype_for_demo(phenotype)
        st.session_state[SESSION_KEY_PHENOTYPE] = approved
        st.success(
            "Phenotype approved for synthetic cohort demo. "
            "Navigate to Page 4 (Synthetic Cohort) to run the pipeline."
        )
        st.rerun()
else:
    st.success("Phenotype is approved for synthetic demo. Proceed to Page 4.")

st.download_button(
    label="Download phenotype JSON",
    data=phenotype_to_json_bytes(phenotype),
    file_name=f"phenotype_{phenotype.id}_v{phenotype.version}.json",
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
        "Terminology mappings are candidate suggestions requiring human clinical review before any use. "
        "RxNorm codes marked 'LLM-suggested' and 'unverified' must be confirmed against the live "
        "RxNorm API before production use."
    )
