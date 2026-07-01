"""Synthetic Cohort — execute and inspect the phenotype-defined cohort pipeline.

Page 4 of the Clinical Question-Evidence Studio.
Requires an approved phenotype in session state (from Phenotype Builder, Page 3).

All data is synthetic (fictional). No real patient information is processed.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from app.components.ui_helpers import (
    SESSION_KEY_COHORT_QA,
    SESSION_KEY_COHORT_RUN,
    SESSION_KEY_FHIR_QA,
    SESSION_KEY_PHENOTYPE,
    attrition_table_rows,
    cohort_run_to_json_bytes,
    format_attrition_pct,
    qa_summary_rows,
    sidebar_data_note_text,
    sidebar_disclaimer_text,
)

st.set_page_config(
    page_title="Synthetic Cohort | Clinical Q-E Studio",
    page_icon="🧪",
    layout="wide",
)

with st.sidebar:
    st.markdown("---")
    st.warning(sidebar_disclaimer_text())
    st.caption(sidebar_data_note_text())

st.markdown(
    """
<style>
.synth-banner { background:#e8f5e9; border-left:4px solid #4caf50;
                padding:10px 14px; border-radius:4px; margin-bottom:12px; }
.warn-banner  { background:#fff8e1; border-left:4px solid #ffc107;
                padding:10px 14px; border-radius:4px; margin-bottom:12px; }
.qa-pass   { color:#27ae60; font-weight:bold; }
.qa-warn   { color:#e67e22; font-weight:bold; }
.qa-fail   { color:#c0392b; font-weight:bold; }
.qa-na     { color:#7f8c8d; }
</style>
""",
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────────────────────────
# Section 1: Synthetic data notice
# ──────────────────────────────────────────────────────────────────
st.title("Synthetic Cohort Construction")
st.markdown(
    """
<div class="synth-banner">
<strong>SYNTHETIC DATA ONLY</strong> &mdash; All patients in this cohort are fictional characters
generated from a seeded random process (seed=42, reference_date=2025-06-01). No real patient
health information is present. This application is an educational portfolio prototype and has
<strong>not been clinically validated</strong>.
</div>
""",
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────────────────────────
# Section 2: Phenotype gate check
# ──────────────────────────────────────────────────────────────────
phenotype = st.session_state.get(SESSION_KEY_PHENOTYPE)
if phenotype is None:
    st.warning(
        "No phenotype found in session. Please complete the Question Builder (Page 2) "
        "and Phenotype Builder (Page 3) first."
    )
    if st.button("Go to Phenotype Builder"):
        st.switch_page("pages/3_Phenotype_Builder.py")
    st.stop()

if phenotype.review_status != "approved":
    st.error(
        f"Phenotype '{phenotype.id}' has review_status='{phenotype.review_status}'. "
        "The cohort pipeline requires an approved phenotype. "
        "Return to the Phenotype Builder and click 'Approve phenotype structure for synthetic demo'."
    )
    if st.button("Go to Phenotype Builder"):
        st.switch_page("pages/3_Phenotype_Builder.py")
    st.stop()

st.success(f"Phenotype **{phenotype.id}** v{phenotype.version} is approved. Ready to run.")

# ──────────────────────────────────────────────────────────────────
# Section 3: Cohort configuration
# ──────────────────────────────────────────────────────────────────
st.header("1 · Cohort Configuration")

with st.form("cohort_config_form"):
    col1, col2 = st.columns(2)
    with col1:
        dataset_id = st.selectbox(
            "Synthetic dataset",
            options=["synthetic-cohort-v1"],
            help="Bundled synthetic FHIR dataset (160 fictional patients, seed=42)",
        )
        min_age = st.number_input("Minimum age (years)", min_value=0, max_value=120, value=18)
        obs_days = st.number_input(
            "Minimum observation history (days)", min_value=0, max_value=3650, value=365
        )
    with col2:
        ref_date = st.date_input(
            "Reference date (index date)",
            value=date(2025, 6, 1),
            help="All temporal criteria are evaluated at this date",
        )
        include_med_filter = st.checkbox(
            "Include SGLT2 exploratory filter (UNVERIFIED CODES)",
            value=False,
            help=(
                "Apply an optional medication exposure filter using LLM-suggested, "
                "unverified RxNorm codes. Results are provisional — NOT confirmed exposure."
            ),
        )
        require_lab = st.checkbox(
            "Require eGFR lab availability",
            value=False,
            help="Restrict cohort to patients with at least one eGFR observation in the lookback window",
        )

    if include_med_filter:
        st.markdown(
            """
<div class="warn-banner">
<strong>Provisional medication filter</strong>: The SGLT2 filter uses RxNorm codes that are
LLM-suggested and have NOT been verified against the live RxNorm API. Results show
<em>candidate medication exposure only</em> and must not be used for clinical decisions.
</div>
""",
            unsafe_allow_html=True,
        )

    submitted = st.form_submit_button("Run Cohort Pipeline", type="primary")

if not submitted:
    existing_run = st.session_state.get(SESSION_KEY_COHORT_RUN)
    if existing_run is None:
        st.info("Configure the cohort parameters above and click 'Run Cohort Pipeline'.")
        st.stop()
    # Show prior run results without re-running
    run = existing_run
    fhir_qa = st.session_state.get(SESSION_KEY_FHIR_QA)
    cohort_qa = st.session_state.get(SESSION_KEY_COHORT_QA)
else:
    # Execute cohort pipeline
    from src.cohorts.service import get_cohort_service
    from src.schemas.cohort import CohortConfiguration
    from src.utils.exceptions import UnapprovedPhenotypeError, UnresolvedConceptError

    config = CohortConfiguration(
        reference_date=ref_date,
        min_age_years=int(min_age),
        observation_lookback_days=int(obs_days),
        include_medication_exposure_filter=include_med_filter,
        medication_lookback_days=365,
        require_lab_availability=require_lab,
        lab_lookback_days=365,
        dataset_id=dataset_id,
    )

    with st.spinner("Running cohort pipeline..."):
        try:
            svc = get_cohort_service()
            run, fhir_qa, cohort_qa = svc.run(phenotype, config)
            st.session_state[SESSION_KEY_COHORT_RUN] = run
            st.session_state[SESSION_KEY_FHIR_QA] = fhir_qa
            st.session_state[SESSION_KEY_COHORT_QA] = cohort_qa
        except UnapprovedPhenotypeError as exc:
            st.error(f"Phenotype gate failed: {exc}")
            st.stop()
        except UnresolvedConceptError as exc:
            st.error(f"Concept resolution error: {exc}")
            st.stop()
        except Exception as exc:
            st.error(f"Cohort execution failed: {exc}")
            st.stop()

    st.success(
        f"Cohort pipeline complete — final cohort: **{run.summary.final_cohort_count}** patients "
        f"(from {run.summary.initial_population} starting)."
    )

# ──────────────────────────────────────────────────────────────────
# Section 4: Attrition waterfall
# ──────────────────────────────────────────────────────────────────
st.header("2 · Cohort Attrition")
st.markdown(
    f"Attrition reconciles: **{'Yes' if run.attrition.reconciles else 'No (QA failure)'}** &nbsp;|&nbsp; "
    f"Final cohort: **{run.summary.final_cohort_count}** / {run.summary.initial_population} patients "
    f"({format_attrition_pct(run.summary.initial_population, run.summary.final_cohort_count)})"
)

attrition_rows = attrition_table_rows(run.attrition)
st.dataframe(attrition_rows, use_container_width=True)

# Simple bar chart of patient counts per step
step_labels = [f"Step {r['Step']}" for r in attrition_rows]
step_out = [r["Records Out"] for r in attrition_rows]
import pandas as pd

attrition_df = pd.DataFrame({"Step": step_labels, "Patients Remaining": step_out})
st.bar_chart(attrition_df.set_index("Step"))

# ──────────────────────────────────────────────────────────────────
# Section 5: Cohort profile
# ──────────────────────────────────────────────────────────────────
st.header("3 · Cohort Profile")

demo = run.summary.demographic_summary
col1, col2, col3, col4 = st.columns(4)
col1.metric("Final cohort (N)", run.summary.final_cohort_count)
col2.metric("Mean age (years)", demo.age_mean or "N/A")
col3.metric("Median age", demo.age_median or "N/A")
col4.metric("Age range", f"{demo.age_min}–{demo.age_max}" if demo.age_min is not None else "N/A")

if demo.sex_distribution:
    sex_df = pd.DataFrame([{"Sex": k, "Count": v} for k, v in demo.sex_distribution.items()])
    st.subheader("Sex distribution")
    st.bar_chart(sex_df.set_index("Sex"))

# Condition prevalence
if run.summary.condition_prevalence:
    st.subheader("Condition code prevalence (final cohort)")
    prev_df = pd.DataFrame(
        [
            {"ICD-10 Code": code, "Prevalence": f"{pct * 100:.1f}%"}
            for code, pct in sorted(run.summary.condition_prevalence.items(), key=lambda x: -x[1])[
                :15
            ]
        ]
    )
    st.dataframe(prev_df, use_container_width=True)

# Missingness report
if run.summary.missingness_report:
    st.subheader("Data availability")
    miss_rows = [
        {
            "Variable": r.variable,
            "Available": r.available_count,
            "Missing": r.missing_count,
            "Total": r.total_count,
            "Availability %": f"{r.availability_pct}%",
        }
        for r in run.summary.missingness_report
    ]
    st.dataframe(miss_rows, use_container_width=True)

st.caption(f"Data source: {run.summary.data_source}")

# ──────────────────────────────────────────────────────────────────
# Section 6: QA results
# ──────────────────────────────────────────────────────────────────
st.header("4 · Quality Assurance")

fhir_qa = st.session_state.get(SESSION_KEY_FHIR_QA)
cohort_qa = st.session_state.get(SESSION_KEY_COHORT_QA)

if run.warnings:
    st.markdown(
        """<div class="warn-banner"><strong>QA Warnings</strong></div>""",
        unsafe_allow_html=True,
    )
    for w in run.warnings:
        st.warning(w)

col_fhir, col_cohort = st.columns(2)

with col_fhir:
    st.subheader("FHIR Ingestion QA")
    if fhir_qa:
        st.markdown(
            f"Passed: **{fhir_qa.passed}** | Warnings: **{fhir_qa.warnings}** | "
            f"Failed: **{fhir_qa.failed}**"
        )
        st.dataframe(qa_summary_rows(fhir_qa), use_container_width=True)
    else:
        st.info("No FHIR QA results available.")

with col_cohort:
    st.subheader("Cohort Execution QA")
    if cohort_qa:
        critical_flag = " — CRITICAL FAILURE" if cohort_qa.has_critical_failure else ""
        st.markdown(
            f"Passed: **{cohort_qa.passed}** | Warnings: **{cohort_qa.warnings}** | "
            f"Failed: **{cohort_qa.failed}**{critical_flag}"
        )
        st.dataframe(qa_summary_rows(cohort_qa), use_container_width=True)
    else:
        st.info("No cohort QA results available.")

# ──────────────────────────────────────────────────────────────────
# Section 7: Export
# ──────────────────────────────────────────────────────────────────
st.header("5 · Export")

st.download_button(
    label="Download cohort run JSON",
    data=cohort_run_to_json_bytes(run),
    file_name=f"cohort_run_{run.run_id[:8]}.json",
    mime="application/json",
)

st.markdown(
    f"""
**Provenance summary:**
- Run ID: `{run.run_id}`
- Phenotype: `{run.provenance.phenotype_id}` v{run.provenance.phenotype_version}
- Dataset: `{run.provenance.dataset_id}`
- Reference date: `{run.configuration.reference_date}`
- Configuration hash: `{run.provenance.configuration_hash}`
- Synthetic: `{run.provenance.is_synthetic}`
"""
)

# ──────────────────────────────────────────────────────────────────
# Disclaimer
# ──────────────────────────────────────────────────────────────────
with st.expander("Disclaimer"):
    st.markdown(
        "This application uses **entirely synthetic patient data** generated for portfolio "
        "demonstration purposes. It is not clinically validated, has not been deployed in a "
        "healthcare organization, and must not be used for patient care or clinical decisions. "
        "All patient counts, demographic statistics, and prevalence estimates are derived from "
        "fictional data and have no clinical meaning. "
        "RxNorm codes marked 'LLM-suggested' are unverified candidate codes requiring review "
        "against the live RxNorm API before any use."
    )
