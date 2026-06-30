# Portfolio Case Study: Clinical Question-Evidence Studio

## 1. Overview

The Clinical Question-Evidence Studio is a portfolio prototype that demonstrates end-to-end clinical informatics engineering skills. It converts a natural-language clinical research question into a structured PICO framework, computable phenotype, synthetic cohort, and cited evidence brief — with full provenance tracking and automated quality assurance.

**Disclaimer:** This project uses entirely synthetic patient data and publicly available evidence. It is an educational portfolio prototype, has not been clinically validated, and does not provide medical advice.

## 2. Problem

Healthcare researchers spend significant time manually translating clinical questions into computable cohort definitions, searching literature across multiple databases, and assembling evidence summaries. Each step is error-prone, time-consuming, and lacks standardized provenance documentation.

## 3. Why It Matters

Real-world evidence (RWE) studies require rigorous phenotype definitions, systematic evidence retrieval, and transparent quality assurance. Demonstrating the ability to build a structured, auditable workflow at this intersection of clinical informatics, ontologies, AI, and software engineering directly addresses hiring needs in clinical data science, RWE, and healthcare analytics.

## 4. Solution Architecture

A modular Python application with three layers:
- **FastAPI** for reusable REST endpoints
- **Streamlit** for an interactive portfolio-quality interface
- **Shared source modules** with Pydantic-validated schemas connecting every layer

## 5. Clinical Question Workflow

The demo question — T2DM + CKD + SGLT2 inhibitors — was chosen because it maps to multiple completed landmark trials (EMPA-REG OUTCOME, CREDENCE, DAPA-CKD) and has well-established ICD-10-CM, RxNorm, and LOINC representations.

## 6. Ontology and FHIR Mapping

ICD-10-CM, RxNorm, and LOINC codes are mapped at the ingredient/concept level with explicit version tracking. All candidate mappings are labeled and require human review — the application does not silently promote LLM-suggested codes to approved status.

## 7. Synthetic Cohort Construction

A deterministic, seeded synthetic FHIR R4 dataset (160 fictional patients, modeled on Synthea-style generation patterns but produced by a custom generator bundled with this project, not the Synthea tool itself) is loaded, normalized, and run through a cohort engine that applies an approved phenotype's inclusion/exclusion rules as a sequential attrition waterfall. The attrition math is mathematically validated at the schema level (Pydantic `model_validator` enforces `records_out == records_in - records_excluded`) and independently re-checked by a QA layer (`coh-001`–`coh-008`). Two safety gates prevent an LLM from silently defining cohort membership: an unapproved phenotype cannot be executed, and concepts backed only by LLM-suggested, unverified terminology mappings (e.g., the SGLT2 RxNorm codes) are demoted to an explicit, opt-in exploratory filter rather than a required criterion. See [cohort_methodology.md](cohort_methodology.md) and [synthetic_data_methodology.md](synthetic_data_methodology.md) for full detail. All patient data is synthetic; this pipeline has not been run against, or validated with, real Synthea output or real patient data.

## 8. Evidence Retrieval

Adapters for PubMed, ClinicalTrials.gov, and CMS Coverage use `tenacity` for retries, `diskcache` for local caching, and preserve raw API responses for audit. Offline fixtures allow the application to run without internet access.

## 9. Quality Assurance

QA is implemented as a first-class feature. Every pipeline step emits `QAResult` objects with severity levels (critical / major / minor / info). Critical failures block pipeline progression. AI-quality checks enforce citation coverage and detect uncited clinical claims.

## 10. Technical Skills Demonstrated

- Python 3.12, FastAPI, Streamlit, Pydantic v2
- FHIR R4 resource handling (Patient, Condition, MedicationRequest, Observation)
- Clinical terminologies: ICD-10-CM, RxNorm, LOINC
- Provider-agnostic LLM interface with demo fallback
- DuckDB for analytical storage with clean repository pattern
- Docker and Docker Compose
- GitHub Actions CI (lint, typecheck, test, Docker build)
- Comprehensive test suite with pytest and schema-level invariants
- Evidence synthesis with provenance and citation tracking
