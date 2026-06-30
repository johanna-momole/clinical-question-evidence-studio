"""Clinical Question-Evidence Studio — Overview page (Page 1 of 8).

This is the Streamlit entry point. Run with:
    streamlit run app/Home.py
"""

import sys
from pathlib import Path

# Ensure project root is importable when running without installation
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src.config.settings import get_settings

st.set_page_config(
    page_title="Clinical Question-Evidence Studio",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
    /* Global tone */
    .main .block-container { padding-top: 1.5rem; }

    /* Metric cards */
    [data-testid="metric-container"] {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
    }

    /* Section dividers */
    hr { border: none; border-top: 1px solid #e2e8f0; margin: 1.5rem 0; }

    /* Workflow step badges */
    .step-badge {
        display: inline-block;
        background: #1e40af;
        color: white;
        border-radius: 50%;
        width: 28px;
        height: 28px;
        line-height: 28px;
        text-align: center;
        font-weight: 700;
        font-size: 13px;
        margin-right: 8px;
    }

    /* Demo mode pill */
    .demo-pill {
        display: inline-block;
        background: #fef3c7;
        color: #92400e;
        border: 1px solid #fcd34d;
        border-radius: 20px;
        padding: 2px 10px;
        font-size: 12px;
        font-weight: 600;
    }

    /* Status badge */
    .status-ok {
        display: inline-block;
        background: #d1fae5;
        color: #065f46;
        border-radius: 4px;
        padding: 1px 8px;
        font-size: 12px;
        font-weight: 600;
    }
</style>
""",
    unsafe_allow_html=True,
)

settings = get_settings()

# ── Header ─────────────────────────────────────────────────────────────────────
col_title, col_badges = st.columns([4, 1])
with col_title:
    st.title("Clinical Question-Evidence Studio")
    st.markdown(
        "**An educational clinical informatics prototype** · "
        "Natural-language question → PICO → computable phenotype → synthetic cohort → evidence brief"
    )
with col_badges:
    st.markdown("<br>", unsafe_allow_html=True)
    if settings.is_demo_mode:
        st.markdown('<span class="demo-pill">DEMO MODE</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-ok">LIVE MODE</span>', unsafe_allow_html=True)

# ── Disclaimer ─────────────────────────────────────────────────────────────────
st.warning(
    "**Disclaimer:** This project uses entirely synthetic patient data and publicly available "
    "evidence. It is an educational portfolio prototype, has not been clinically validated, "
    "and does not provide medical advice.",
    icon="⚠️",
)

st.divider()

# ── Key metrics ────────────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
m1.metric("Demo Questions", "3", help="Curated clinical questions in this prototype")
m2.metric("Terminology Systems", "4", help="ICD-10-CM, RxNorm, LOINC, SNOMED-CT (candidate)")
m3.metric("Evidence Sources", "3", help="PubMed, ClinicalTrials.gov, CMS Coverage")
m4.metric("Export Formats", "4", help="JSON, Markdown, PDF, PowerPoint")

st.divider()

# ── About ──────────────────────────────────────────────────────────────────────
st.subheader("About This Project")
col_about, col_question = st.columns([2, 1])

with col_about:
    st.markdown(
        """
This prototype demonstrates an end-to-end clinical informatics workflow:

1. A clinician or researcher enters a natural-language research question.
2. The application structures it using the PICO framework and identifies ambiguities.
3. A computable phenotype is constructed with ICD-10-CM, RxNorm, and LOINC mappings.
4. The phenotype runs against synthetic FHIR R4 patient data (Synthea) to produce a cohort.
5. External evidence is retrieved from PubMed and ClinicalTrials.gov.
6. A cited evidence brief is generated with full provenance tracking.
7. Quality assurance checks run at every step.
8. Results export to JSON, Markdown, PDF, and PowerPoint.

**This is an academic demonstration prototype.** It shows methodology and engineering
approach — not a validated or deployed clinical decision support system.
"""
    )

with col_question:
    st.info(
        """
**Demo Question:**

*"Among adults with type 2 diabetes and chronic kidney disease, how would a computable
cohort for SGLT2 inhibitor research be defined, and what external evidence is available?"*

**Population:** T2DM + CKD adults

**Intervention:** SGLT2 inhibitors

**Comparator:** None (descriptive)

**Data:** Synthetic (Synthea)
"""
    )

st.divider()

# ── Workflow ───────────────────────────────────────────────────────────────────
st.subheader("Pipeline Workflow")

steps = [
    ("Question Intake", "Enter or select a research question; extract PICO; flag ambiguities"),
    (
        "Phenotype Builder",
        "Map concepts to ICD-10-CM, RxNorm, LOINC; define inclusion/exclusion rules",
    ),
    ("Synthetic Cohort", "Apply phenotype to Synthea FHIR data; produce attrition waterfall"),
    ("External Evidence", "Retrieve publications, trials, and coverage documents from public APIs"),
    ("Metatagging & Search", "Tag all content; enable full-text search and filtering"),
    (
        "Evidence Synthesis",
        "Generate cited brief distinguishing retrieved facts from LLM summaries",
    ),
    ("QA & Provenance", "Validate data quality, citation coverage, and AI governance"),
    ("Export Center", "Download JSON, Markdown, PDF, and PowerPoint outputs"),
]

for i, (step_name, step_desc) in enumerate(steps, 1):
    col_num, col_content = st.columns([1, 12])
    with col_num:
        st.markdown(f'<div class="step-badge">{i}</div>', unsafe_allow_html=True)
    with col_content:
        st.markdown(f"**{step_name}** — {step_desc}")

st.divider()

# ── Data sources ───────────────────────────────────────────────────────────────
with st.expander("Data Sources", expanded=False):
    src_col1, src_col2 = st.columns(2)
    with src_col1:
        st.markdown(
            """
**Patient Data (Synthetic)**
- Synthea v3.x — FHIR R4 synthetic patient records
- Resources: Patient, Condition, Encounter, Observation, MedicationRequest
- No real patient data is used anywhere in this application

**Terminology & Ontologies**
- ICD-10-CM — Diagnosis coding
- RxNorm (NLM) — Medication normalization
- LOINC — Laboratory and clinical concepts
- SNOMED-CT — Candidate clinical concepts
"""
        )
    with src_col2:
        st.markdown(
            """
**External Evidence (Public APIs)**
- PubMed / NCBI E-utilities — Peer-reviewed literature metadata
- ClinicalTrials.gov API v2 — Active and completed trials
- CMS Medicare Coverage Database — LCD/NCD documents

**Offline Mode**
All external sources have local fixture files so the application
runs without internet access or API keys.
"""
        )

# ── Technical stack ────────────────────────────────────────────────────────────
with st.expander("Technical Stack", expanded=False):
    tech_col1, tech_col2, tech_col3 = st.columns(3)
    with tech_col1:
        st.markdown(
            """
**Backend**
- Python 3.12
- FastAPI + Uvicorn
- Pydantic v2
- DuckDB (analytical store)
- Tenacity (retries)
- DiskCache (local caching)
"""
        )
    with tech_col2:
        st.markdown(
            """
**Frontend**
- Streamlit
- Plotly (charts)
- python-pptx (PowerPoint)
- reportlab (PDF)

**AI / LLM**
- Provider-agnostic interface
- Anthropic Claude (optional)
- OpenAI GPT (optional)
- Demo mode (always available)
"""
        )
    with tech_col3:
        st.markdown(
            """
**Infrastructure**
- Docker + Docker Compose
- GitHub Actions CI
- Ruff (linting/formatting)
- mypy (type checking)
- pytest + pytest-cov

**Data**
- Synthea synthetic FHIR R4
- Pandas / Polars
"""
        )

# ── Limitations ────────────────────────────────────────────────────────────────
with st.expander("Limitations & Scope", expanded=False):
    st.markdown(
        """
**What this prototype does NOT do:**
- Use or display real patient data
- Provide clinical recommendations
- Claim clinical validation or regulatory approval
- Imply deployment in a healthcare organization
- Make causal claims from observational or synthetic data
- Allow LLM to silently define the final phenotype without human review

**Technical scope limitations:**
- Supports three curated questions; does not generalize to all medical domains
- Terminology mappings are candidate suggestions requiring expert review
- Cohort results reflect synthetic data patterns, not real-world epidemiology
- Evidence retrieval is limited by public API rate limits and availability
- PDF and PowerPoint output is functional but not fully styled in Phase 1
- LLM summaries are labeled and separated from retrieved facts

**Evidence limitations:**
- Retrieved evidence is not systematically reviewed
- Evidence recency flags items older than 5 years
- Citation coverage varies by source availability
"""
    )

# ── Navigation hint ────────────────────────────────────────────────────────────
st.divider()
st.markdown(
    "**Use the sidebar to navigate** through the pipeline steps. "
    "Start with **Question Builder** to begin the workflow, or explore each page independently."
)
st.caption(
    f"Clinical Question-Evidence Studio v{settings.app_version} · "
    "Educational prototype · Synthetic data · Not for clinical use"
)
