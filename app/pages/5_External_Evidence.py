"""External Evidence — retrieve and explore real external evidence for the clinical question.

Page 5 of the Clinical Question-Evidence Studio.
Gated on: approved clinical question (Page 2) + approved phenotype (Page 3).
Requires a completed cohort run (Page 4) to be in session state.

Evidence content is REAL publicly available source data (PubMed, ClinicalTrials.gov, CMS).
In this demo environment records are served from versioned offline fixtures.
Only the patient cohort is synthetic.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from app.components.ui_helpers import (
    SESSION_KEY_COHORT_RUN,
    SESSION_KEY_EVIDENCE_RECORDS,
    SESSION_KEY_PHENOTYPE,
    SESSION_KEY_QUESTION,
    SESSION_KEY_RETRIEVAL_RUN,
    evidence_qa_rows,
    evidence_record_to_display_row,
    sidebar_data_note_text,
    sidebar_disclaimer_text,
    source_status_to_display_rows,
)

st.set_page_config(
    page_title="External Evidence | Clinical Q-E Studio",
    page_icon="📚",
    layout="wide",
)

with st.sidebar:
    st.markdown("---")
    st.warning(sidebar_disclaimer_text())
    st.caption(sidebar_data_note_text())

# ------------------------------------------------------------------
# Gate checks
# ------------------------------------------------------------------

question = st.session_state.get(SESSION_KEY_QUESTION)
phenotype = st.session_state.get(SESSION_KEY_PHENOTYPE)
cohort_run = st.session_state.get(SESSION_KEY_COHORT_RUN)

if question is None or phenotype is None:
    st.warning(
        "An approved clinical question and reviewed phenotype are required. "
        "Complete Pages 2 and 3 first."
    )
    st.stop()

if cohort_run is None:
    st.warning(
        "A completed cohort run is required before retrieving external evidence. "
        "Complete Page 4 first."
    )
    st.stop()

# ------------------------------------------------------------------
# Header
# ------------------------------------------------------------------

st.title("External Evidence Retrieval")
st.markdown(
    f"""
**Question:** {question.question_text}

**Phenotype:** {phenotype.name} (v{phenotype.version})
"""
)
st.info(
    "Evidence content is **real, publicly available source data** "
    "(PubMed, ClinicalTrials.gov, CMS). "
    "In this demo environment records are served from **versioned offline fixtures** "
    "rather than live API calls. Only the patient cohort is synthetic."
)

# ------------------------------------------------------------------
# Retrieve evidence (or use cached run from session)
# ------------------------------------------------------------------

existing_run = st.session_state.get(SESSION_KEY_RETRIEVAL_RUN)
records_cache = st.session_state.get(SESSION_KEY_EVIDENCE_RECORDS)

col_run, col_reset = st.columns([4, 1])
with col_run:
    run_btn = st.button(
        "Retrieve External Evidence",
        type="primary",
        disabled=(existing_run is not None),
        help="Run the full evidence retrieval pipeline for this question + phenotype combination.",
    )
with col_reset:
    if existing_run is not None:
        if st.button("Reset", help="Clear cached evidence run and run again"):
            st.session_state.pop(SESSION_KEY_RETRIEVAL_RUN, None)
            st.session_state.pop(SESSION_KEY_EVIDENCE_RECORDS, None)
            st.rerun()

if run_btn:
    from src.evidence.service import EvidenceService, get_evidence_repository

    with st.spinner("Running evidence retrieval pipeline..."):
        try:
            # Approve question + phenotype for demo (they were approved in their respective pages)
            demo_question = question.model_copy(update={"status": "approved"})
            demo_phenotype = phenotype.model_copy(update={"review_status": "approved"})

            svc = EvidenceService(repository=get_evidence_repository())
            run = svc.run(
                question=demo_question,
                phenotype=demo_phenotype,
                offline_only=True,
            )
            st.session_state[SESSION_KEY_RETRIEVAL_RUN] = run

            # Retrieve evidence records from repo for display
            repo = get_evidence_repository()
            records = repo.list_evidence_for_run(run.run_id)
            st.session_state[SESSION_KEY_EVIDENCE_RECORDS] = records

            st.success(
                f"Retrieved {run.total_records_retrieved} records "
                f"({run.total_records_after_dedup} after deduplication) from "
                f"{len(run.provenance.sources_queried)} sources."
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Evidence retrieval failed: {exc}")

# ------------------------------------------------------------------
# Display results
# ------------------------------------------------------------------

run = st.session_state.get(SESSION_KEY_RETRIEVAL_RUN)
records_list = st.session_state.get(SESSION_KEY_EVIDENCE_RECORDS, [])

if run is None:
    st.markdown("Click **Retrieve External Evidence** to run the pipeline.")
    st.stop()

# ------------------------------------------------------------------
# Run summary metrics
# ------------------------------------------------------------------

st.divider()
st.subheader("Retrieval Summary")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Records Retrieved", run.total_records_retrieved)
m2.metric("After Dedup", run.total_records_after_dedup)
m3.metric("Sources", len(run.provenance.sources_queried))
m4.metric("Mode", run.provenance.retrieval_mode.replace("_", " ").title())

# Source breakdown
st.markdown("**Source breakdown:**")
source_rows = source_status_to_display_rows(
    [
        {
            "source_name": ss.source_name,
            "records_retrieved": ss.records_retrieved,
            "records_after_normalization": ss.records_after_normalization,
            "cache_hit": ss.cache_hit,
            "error_count": len(ss.errors),
        }
        for ss in run.source_statuses
    ]
)
if source_rows:
    st.dataframe(source_rows, use_container_width=True, hide_index=True)

# ------------------------------------------------------------------
# Evidence records browser
# ------------------------------------------------------------------

st.divider()
st.subheader("Evidence Records")

if not records_list:
    st.info("No records to display.")
else:
    # Filter controls
    with st.expander("Filter options", expanded=False):
        filt_col1, filt_col2, filt_col3 = st.columns(3)
        with filt_col1:
            source_types = sorted(
                {r.get("source_type", "") for r in records_list if r.get("source_type")}
            )
            source_filter = st.selectbox(
                "Filter by source type",
                ["All"] + source_types,
                key="ev_source_filter",
            )
        with filt_col2:
            min_score = st.slider(
                "Minimum relevance score",
                min_value=0.0,
                max_value=1.0,
                value=0.0,
                step=0.05,
                key="ev_min_score",
            )
        with filt_col3:
            tag_options = sorted({t for r in records_list for t in r.get("tags", [])})
            tag_filter = st.multiselect(
                "Filter by tags",
                tag_options,
                key="ev_tag_filter",
            )

    # Apply filters
    filtered = records_list
    if source_filter != "All":
        filtered = [r for r in filtered if r.get("source_type") == source_filter]
    if min_score > 0.0:
        filtered = [r for r in filtered if (r.get("relevance_score") or 0.0) >= min_score]
    if tag_filter:
        tag_set = set(tag_filter)
        filtered = [r for r in filtered if set(r.get("tags", [])) & tag_set]

    st.caption(f"Showing {len(filtered)} of {len(records_list)} records")

    # Summary table
    display_rows = [evidence_record_to_display_row(r) for r in filtered]
    st.dataframe(display_rows, use_container_width=True, hide_index=True)

    # Detail expander for each record
    st.subheader("Record Detail")
    record_titles = [
        f"{i + 1}. {r.get('title', r.get('identifier', ''))[:80]}" for i, r in enumerate(filtered)
    ]
    if record_titles:
        selected_idx = st.selectbox(
            "Select record to view detail",
            range(len(record_titles)),
            format_func=lambda i: record_titles[i],
        )
        selected = filtered[selected_idx]
        with st.container(border=True):
            detail_c1, detail_c2 = st.columns([3, 1])
            with detail_c1:
                st.markdown(f"**{selected.get('title', '')}**")
                if selected.get("url"):
                    st.markdown(f"[View source]({selected['url']})")
                if selected.get("population"):
                    st.markdown(f"**Population:** {selected['population']}")
                if selected.get("intervention"):
                    st.markdown(f"**Intervention:** {selected['intervention']}")
                if selected.get("outcomes"):
                    st.markdown(f"**Outcomes:** {', '.join(selected['outcomes'])}")
                if selected.get("relevance_rationale"):
                    with st.expander("Relevance rationale", expanded=False):
                        for rationale in selected["relevance_rationale"]:
                            st.markdown(f"- {rationale}")
                if selected.get("not_applicable_fields"):
                    with st.expander("Not applicable fields", expanded=False):
                        st.markdown(
                            "The following fields are structurally not applicable to this record type: "
                            f"{', '.join(selected['not_applicable_fields'])}"
                        )
            with detail_c2:
                st.metric("Relevance", f"{selected.get('relevance_score') or 0.0:.2f}")
                st.markdown(f"**Identifier:** `{selected.get('identifier', '')}`")
                st.markdown(
                    f"**Design:** {selected.get('study_design', 'Not reported') or 'Not reported'}"
                )
                st.markdown(
                    f"**Date:** {selected.get('publication_or_update_date', 'Not reported') or 'Not reported'}"
                )
                st.markdown(
                    f"**Fixture data:** {'Yes' if selected.get('is_fixture_data') else 'No'}"
                )

            if selected.get("structured_tags"):
                st.markdown("**Tags:**")
                tag_cols = st.columns(min(len(selected["structured_tags"]), 5))
                for i, tag_obj in enumerate(selected["structured_tags"][:5]):
                    tag_cols[i % 5].markdown(f"`{tag_obj.get('tag', '')}`")

# ------------------------------------------------------------------
# QA panels
# ------------------------------------------------------------------

st.divider()
qa_tab1, qa_tab2 = st.tabs(["Evidence Record QA", "Retrieval Run QA"])

from src.evidence.repository import get_evidence_repository as _get_repo

_repo = _get_repo()

with qa_tab1:
    try:
        eq_results = _repo.get_evidence_qa(run.run_id)
        if eq_results:
            eq_rows = evidence_qa_rows(eq_results)
            st.dataframe(eq_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No evidence record QA results found for this run.")
    except Exception as exc:
        st.warning(f"Could not load evidence QA results: {exc}")

with qa_tab2:
    try:
        rq_results = _repo.get_retrieval_qa(run.run_id)
        if rq_results:
            rq_rows = evidence_qa_rows(rq_results)
            st.dataframe(rq_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No retrieval QA results found for this run.")
    except Exception as exc:
        st.warning(f"Could not load retrieval QA results: {exc}")

# ------------------------------------------------------------------
# Export
# ------------------------------------------------------------------

st.divider()
st.subheader("Export")

import json as _json

if records_list:
    export_data = {
        "run_id": run.run_id,
        "query_hash": run.query.query_hash,
        "retrieval_mode": run.provenance.retrieval_mode,
        "data_authenticity_note": run.provenance.data_authenticity_note,
        "total_records_retrieved": run.total_records_retrieved,
        "total_records_after_dedup": run.total_records_after_dedup,
        "records": records_list,
    }
    st.download_button(
        label="Download evidence records (JSON)",
        data=_json.dumps(export_data, default=str, indent=2).encode("utf-8"),
        file_name=f"evidence_{run.run_id[:8]}.json",
        mime="application/json",
    )
