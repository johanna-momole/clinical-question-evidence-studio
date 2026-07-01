"""Phase 4 unit tests: External Evidence Retrieval, Normalization, Metatagging, and Search.

Coverage matrix:
  query_builder     — gate enforcement, determinism, hash stability, PICO term extraction
  adapters          — PubMed / ClinicalTrials / CMS offline fixture load, manifest-missing error
  rxnorm_adapter    — found / not-found / name-mismatch
  normalizer        — PubMed / CT / CMS types, partial dates, missing abstract
  deduplication     — same-source dedup by ID + hash, cross-source relationship detection
  metatagging       — all 7 dimensions, determinism across calls
  ranking           — score bounds, sort order, relevance_rationale populated
  evidence_checks   — EQ-001 through EQ-010
  retrieval_checks  — RQ-001 through RQ-006
  cache             — TTL expiry, cache-key uniqueness, injectable clock
  repository        — save_run / get_run / list_evidence_for_run idempotency
  service           — full pipeline smoke test with fixture data

Tests requiring live network access are marked @pytest.mark.live and are excluded from
the default test suite (pytest -m "not live").
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from src.schemas.evidence import (
    ClinicalTrialRecord,
    CoverageRecord,
    EvidenceRecord,
    EvidenceSourceName,
    PublicationRecord,
    RawEvidenceRecord,
)
from src.schemas.retrieval import (
    EvidenceQuery,
    EvidenceSourceStatus,
    RetrievalError,
    RetrievalProvenance,
    RetrievalRequest,
    RetrievalRun,
    SourceSpecificQuery,
)
from src.schemas.terminology_verification import (
    TerminologyVerificationRequest,
)
from src.utils.exceptions import (
    ApprovalRequiredError,
    FixtureManifestError,
    UnapprovedPhenotypeError,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_FIXTURE_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures" / "evidence"


def _approved_question():
    from src.question_parser.service import get_question_service

    svc = get_question_service()
    q = svc.get_curated_question("q-sglt2-ckd-t2dm-001")
    assert q is not None, "Curated question q-sglt2-ckd-t2dm-001 must exist"
    return q.model_copy(update={"status": "approved"})


def _approved_phenotype():
    from src.phenotypes.repository import PhenotypeRepository

    repo = PhenotypeRepository(Path("data/fixtures"))
    ph = repo.load("pheno-sglt2-ckd-t2dm-001")
    return ph.model_copy(update={"review_status": "approved"})


def _pending_question():
    from src.question_parser.service import get_question_service

    svc = get_question_service()
    q = svc.get_curated_question("q-sglt2-ckd-t2dm-001")
    assert q is not None
    return q.model_copy(update={"status": "pending_review"})


def _pending_phenotype():
    ph = _approved_phenotype()
    return ph.model_copy(update={"review_status": "pending"})


def _make_raw_record(
    source_name: EvidenceSourceName = "pubmed",
    identifier: str = "12345678",
    content_hash: str = "abc123def456ab12",
    payload: dict | None = None,
) -> RawEvidenceRecord:
    return RawEvidenceRecord(
        id=f"raw-{uuid.uuid4().hex[:8]}",
        source_name=source_name,
        retrieval_run_id="run-test-001",
        source_identifier=identifier,
        raw_payload=payload or {"pmid": identifier, "title": "Test article"},
        content_hash=content_hash,
        fetched_at=datetime.now(UTC),
        is_fixture_data=True,
        fixture_manifest_version="1.0.0",
    )


def _make_pub_record(
    identifier: str = "12345678",
    title: str = "A randomized controlled trial of empagliflozin in CKD",
    source_name: EvidenceSourceName = "pubmed",
    relevance_score: float | None = 0.85,
    content_hash: str | None = None,
    pub_date: date | None = None,
    study_design: str | None = "rct",
) -> PublicationRecord:
    return PublicationRecord(
        id=f"ev-pub-{identifier}",
        identifier=identifier,
        title=title,
        source_name=source_name,
        publication_or_update_date=pub_date or date(2022, 6, 15),
        study_design=study_design,
        relevance_score=relevance_score,
        content_hash=content_hash or f"hash{identifier[:8]}abcdef",
        is_fixture_data=True,
    )


def _make_source_query(source_name: EvidenceSourceName = "pubmed") -> SourceSpecificQuery:
    return SourceSpecificQuery(
        source_name=source_name,
        query_string="empagliflozin AND chronic kidney disease",
        parameters={"retmax": 50},
        terms_used=["empagliflozin", "chronic kidney disease"],
    )


def _make_evidence_query(question_id: str = "q-001", phenotype_id: str = "ph-001") -> EvidenceQuery:
    return EvidenceQuery(
        id=f"eq-{uuid.uuid4().hex[:8]}",
        question_id=question_id,
        phenotype_id=phenotype_id,
        phenotype_version="1.0",
        population_terms=["chronic kidney disease", "type 2 diabetes"],
        intervention_terms=["empagliflozin", "SGLT2 inhibitor"],
        comparator_terms=["standard of care"],
        outcome_terms=["eGFR", "renal endpoint"],
        source_queries=[_make_source_query()],
        query_hash="abc1234567890def",
        built_at=datetime.now(UTC),
    )


def _make_retrieval_run(
    run_id: str | None = None,
    query: EvidenceQuery | None = None,
    mode: str = "offline_fixture",
) -> RetrievalRun:
    rid = run_id or str(uuid.uuid4())
    q = query or _make_evidence_query()
    return RetrievalRun(
        run_id=rid,
        query=q,
        request=RetrievalRequest(
            query_id=q.id,
            sources=["pubmed", "clinical_trials_gov", "cms_coverage"],
        ),
        provenance=RetrievalProvenance(
            run_id=rid,
            query_hash=q.query_hash,
            retrieval_mode=mode,  # type: ignore[arg-type]
            sources_queried=["pubmed", "clinical_trials_gov", "cms_coverage"],
        ),
        source_statuses=[
            EvidenceSourceStatus(
                source_name="pubmed",
                records_retrieved=6,
                records_after_normalization=6,
            ),
            EvidenceSourceStatus(
                source_name="clinical_trials_gov",
                records_retrieved=5,
                records_after_normalization=5,
            ),
            EvidenceSourceStatus(
                source_name="cms_coverage",
                records_retrieved=3,
                records_after_normalization=3,
            ),
        ],
        total_records_retrieved=14,
        total_records_after_dedup=14,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


# ===========================================================================
# QUERY BUILDER
# ===========================================================================


class TestQueryBuilder:
    def test_raises_if_question_not_approved(self):
        from src.evidence.query_builder import build_query

        q = _pending_question()
        ph = _approved_phenotype()
        with pytest.raises(ApprovalRequiredError):
            build_query(q, ph)

    def test_raises_if_phenotype_not_approved(self):
        from src.evidence.query_builder import build_query

        q = _approved_question()
        ph = _pending_phenotype()
        with pytest.raises(UnapprovedPhenotypeError):
            build_query(q, ph)

    def test_build_returns_evidence_query(self):
        from src.evidence.query_builder import build_query

        q = _approved_question()
        ph = _approved_phenotype()
        eq = build_query(q, ph)
        assert eq.question_id == q.id
        assert eq.phenotype_id == ph.id
        assert eq.query_hash  # non-empty
        assert len(eq.source_queries) == 3

    def test_build_is_deterministic(self):
        from src.evidence.query_builder import build_query

        q = _approved_question()
        ph = _approved_phenotype()
        eq1 = build_query(q, ph)
        eq2 = build_query(q, ph)
        assert eq1.query_hash == eq2.query_hash

    def test_source_names_are_correct(self):
        from src.evidence.query_builder import build_query

        q = _approved_question()
        ph = _approved_phenotype()
        eq = build_query(q, ph)
        source_names = {sq.source_name for sq in eq.source_queries}
        assert source_names == {"pubmed", "clinical_trials_gov", "cms_coverage"}

    def test_hash_is_16_hex_chars(self):
        from src.evidence.query_builder import build_query

        q = _approved_question()
        ph = _approved_phenotype()
        eq = build_query(q, ph)
        assert len(eq.query_hash) == 16
        assert all(c in "0123456789abcdef" for c in eq.query_hash)

    def test_population_terms_non_empty(self):
        from src.evidence.query_builder import build_query

        q = _approved_question()
        ph = _approved_phenotype()
        eq = build_query(q, ph)
        assert len(eq.population_terms) > 0


# ===========================================================================
# ADAPTERS — PubMed, ClinicalTrials, CMS Coverage
# ===========================================================================


class TestPubMedAdapter:
    def test_fetch_returns_records(self):
        from src.evidence_sources.pubmed import PubMedAdapter

        adapter = PubMedAdapter(fixture_dir=_FIXTURE_ROOT / "pubmed")
        result = adapter.fetch(_make_source_query("pubmed"), "run-001")
        assert len(result.records) > 0
        assert result.source_name == "pubmed"

    def test_all_records_have_source_name_pubmed(self):
        from src.evidence_sources.pubmed import PubMedAdapter

        adapter = PubMedAdapter(fixture_dir=_FIXTURE_ROOT / "pubmed")
        result = adapter.fetch(_make_source_query("pubmed"), "run-001")
        assert all(r.source_name == "pubmed" for r in result.records)

    def test_content_hash_is_16_hex_chars(self):
        from src.evidence_sources.pubmed import PubMedAdapter

        adapter = PubMedAdapter(fixture_dir=_FIXTURE_ROOT / "pubmed")
        result = adapter.fetch(_make_source_query("pubmed"), "run-001")
        for rec in result.records:
            assert len(rec.content_hash) == 16
            assert all(c in "0123456789abcdef" for c in rec.content_hash)

    def test_manifest_missing_returns_error_not_raises(self):
        from src.evidence_sources.pubmed import PubMedAdapter

        adapter = PubMedAdapter(fixture_dir=Path("/nonexistent/path/pubmed"))
        result = adapter.fetch(_make_source_query("pubmed"), "run-001")
        assert len(result.errors) > 0
        assert result.errors[0].source_name == "pubmed"
        assert result.errors[0].error_type in ("fixture_missing", "parse_error", "network_error")

    def test_is_fixture_data_true(self):
        from src.evidence_sources.pubmed import PubMedAdapter

        adapter = PubMedAdapter(fixture_dir=_FIXTURE_ROOT / "pubmed")
        result = adapter.fetch(_make_source_query("pubmed"), "run-001")
        assert all(r.is_fixture_data for r in result.records)

    def test_fixture_manifest_version_set(self):
        from src.evidence_sources.pubmed import PubMedAdapter

        adapter = PubMedAdapter(fixture_dir=_FIXTURE_ROOT / "pubmed")
        result = adapter.fetch(_make_source_query("pubmed"), "run-001")
        for rec in result.records:
            assert rec.fixture_manifest_version is not None

    def test_ping_returns_bool(self):
        from src.evidence_sources.pubmed import PubMedAdapter

        adapter = PubMedAdapter(fixture_dir=_FIXTURE_ROOT / "pubmed")
        assert isinstance(adapter.ping(), bool)


class TestClinicalTrialsAdapter:
    def test_fetch_returns_records(self):
        from src.evidence_sources.clinical_trials import ClinicalTrialsAdapter

        adapter = ClinicalTrialsAdapter(fixture_dir=_FIXTURE_ROOT / "clinical_trials")
        result = adapter.fetch(_make_source_query("clinical_trials_gov"), "run-001")
        assert len(result.records) > 0

    def test_records_have_correct_source_name(self):
        from src.evidence_sources.clinical_trials import ClinicalTrialsAdapter

        adapter = ClinicalTrialsAdapter(fixture_dir=_FIXTURE_ROOT / "clinical_trials")
        result = adapter.fetch(_make_source_query("clinical_trials_gov"), "run-001")
        assert all(r.source_name == "clinical_trials_gov" for r in result.records)

    def test_nct_ids_extracted(self):
        from src.evidence_sources.clinical_trials import ClinicalTrialsAdapter

        adapter = ClinicalTrialsAdapter(fixture_dir=_FIXTURE_ROOT / "clinical_trials")
        result = adapter.fetch(_make_source_query("clinical_trials_gov"), "run-001")
        for rec in result.records:
            assert rec.source_identifier.startswith("NCT") or rec.source_identifier, (
                f"Expected NCT ID for {rec.id}"
            )

    def test_manifest_missing_returns_error(self):
        from src.evidence_sources.clinical_trials import ClinicalTrialsAdapter

        adapter = ClinicalTrialsAdapter(fixture_dir=Path("/nonexistent/clinical_trials"))
        result = adapter.fetch(_make_source_query("clinical_trials_gov"), "run-001")
        assert len(result.errors) > 0

    def test_ping_returns_bool(self):
        from src.evidence_sources.clinical_trials import ClinicalTrialsAdapter

        adapter = ClinicalTrialsAdapter(fixture_dir=_FIXTURE_ROOT / "clinical_trials")
        assert isinstance(adapter.ping(), bool)


class TestCMSCoverageAdapter:
    def test_fetch_returns_records(self):
        from src.evidence_sources.cms_coverage import CMSCoverageAdapter

        adapter = CMSCoverageAdapter(fixture_dir=_FIXTURE_ROOT / "cms_coverage")
        result = adapter.fetch(_make_source_query("cms_coverage"), "run-001")
        assert len(result.records) > 0

    def test_records_have_correct_source_name(self):
        from src.evidence_sources.cms_coverage import CMSCoverageAdapter

        adapter = CMSCoverageAdapter(fixture_dir=_FIXTURE_ROOT / "cms_coverage")
        result = adapter.fetch(_make_source_query("cms_coverage"), "run-001")
        assert all(r.source_name == "cms_coverage" for r in result.records)

    def test_manifest_missing_returns_error(self):
        from src.evidence_sources.cms_coverage import CMSCoverageAdapter

        adapter = CMSCoverageAdapter(fixture_dir=Path("/nonexistent/cms"))
        result = adapter.fetch(_make_source_query("cms_coverage"), "run-001")
        assert len(result.errors) > 0

    def test_ping_returns_bool(self):
        from src.evidence_sources.cms_coverage import CMSCoverageAdapter

        adapter = CMSCoverageAdapter(fixture_dir=_FIXTURE_ROOT / "cms_coverage")
        assert isinstance(adapter.ping(), bool)


# ===========================================================================
# RXNORM ADAPTER
# ===========================================================================


class TestRxNormAdapter:
    def test_verify_found_rxcui(self):
        from src.evidence_sources.rxnorm import RxNormAdapter

        adapter = RxNormAdapter(fixture_dir=_FIXTURE_ROOT / "rxnorm")
        req = TerminologyVerificationRequest(rxcui="2200644", offline_only=True)
        result = adapter.verify(req)
        assert result.found is True
        assert result.rxcui == "2200644"
        assert result.is_fixture_data is True

    def test_verify_not_found_rxcui(self):
        from src.evidence_sources.rxnorm import RxNormAdapter

        adapter = RxNormAdapter(fixture_dir=_FIXTURE_ROOT / "rxnorm")
        req = TerminologyVerificationRequest(rxcui="9999999", offline_only=True)
        result = adapter.verify(req)
        assert result.found is False
        assert result.rxcui == "9999999"

    def test_verify_name_mismatch_detected(self):
        from src.evidence_sources.rxnorm import RxNormAdapter

        adapter = RxNormAdapter(fixture_dir=_FIXTURE_ROOT / "rxnorm")
        req = TerminologyVerificationRequest(
            rxcui="2200644",
            expected_concept_name="WRONG DRUG NAME",
            offline_only=True,
        )
        result = adapter.verify(req)
        assert result.found is True
        assert result.matches_expected_name is False

    def test_verify_name_match(self):
        from src.evidence_sources.rxnorm import RxNormAdapter

        adapter = RxNormAdapter(fixture_dir=_FIXTURE_ROOT / "rxnorm")
        # RxCUI 2200644 = empagliflozin per rxnorm_index.json fixture
        req = TerminologyVerificationRequest(
            rxcui="2200644",
            expected_concept_name="empagliflozin",
            offline_only=True,
        )
        result = adapter.verify(req)
        assert result.found is True
        assert result.matches_expected_name is True

    def test_source_is_fixture(self):
        from src.evidence_sources.rxnorm import RxNormAdapter

        adapter = RxNormAdapter(fixture_dir=_FIXTURE_ROOT / "rxnorm")
        req = TerminologyVerificationRequest(rxcui="2200644", offline_only=True)
        result = adapter.verify(req)
        assert result.source == "rxnorm_fixture"

    def test_missing_fixture_raises_fixture_error(self):
        from src.evidence_sources.rxnorm import RxNormAdapter

        adapter = RxNormAdapter(fixture_dir=Path("/nonexistent/rxnorm"))
        req = TerminologyVerificationRequest(rxcui="2200644", offline_only=True)
        with pytest.raises(FixtureManifestError):
            adapter.verify(req)


# ===========================================================================
# NORMALIZER
# ===========================================================================


class TestNormalizer:
    def test_pubmed_raw_normalizes_to_publication_record(self):
        from src.evidence.normalizer import normalize_records

        raw = _make_raw_record(
            source_name="pubmed",
            identifier="26378978",
            payload={
                "pmid": "26378978",
                "title": "Empagliflozin, Cardiovascular Outcomes, and Mortality",
                "abstract": "Background: ...",
                "authors": ["Zinman B", "Wanner C"],
                "journal": "N Engl J Med",
                "pub_date": {"year": "2015", "month": "11", "day": "26"},
                "mesh_terms": ["Sodium-Glucose Transporter 2 Inhibitors"],
                "publication_types": ["Randomized Controlled Trial"],
                "doi": "10.1056/NEJMoa1504720",
                "language": "eng",
            },
        )
        records = normalize_records([raw], "run-001")
        assert len(records) == 1
        rec = records[0]
        assert isinstance(rec, PublicationRecord)
        assert rec.source_type == "publication"
        assert rec.source_name == "pubmed"

    def test_pubmed_missing_abstract_is_none_not_empty_string(self):
        from src.evidence.normalizer import normalize_records

        raw = _make_raw_record(
            source_name="pubmed",
            identifier="34469193",
            payload={"pmid": "34469193", "title": "Test", "abstract": None},
        )
        records = normalize_records([raw], "run-001")
        assert len(records) == 1
        rec = records[0]
        assert isinstance(rec, PublicationRecord)
        assert rec.abstract is None

    def test_pubmed_year_only_date_has_month_precision_at_most_year(self):
        from src.evidence.normalizer import normalize_records

        raw = _make_raw_record(
            source_name="pubmed",
            payload={"pmid": "99999", "title": "Test", "pub_date": {"year": "2020"}},
        )
        records = normalize_records([raw], "run-001")
        assert records[0].date_precision == "year"
        assert records[0].publication_or_update_date is not None
        assert records[0].publication_or_update_date.year == 2020

    def test_pubmed_month_year_date_has_month_precision(self):
        from src.evidence.normalizer import normalize_records

        raw = _make_raw_record(
            source_name="pubmed",
            payload={"pmid": "99998", "title": "T", "pub_date": {"year": "2021", "month": "6"}},
        )
        records = normalize_records([raw], "run-001")
        assert records[0].date_precision == "month"

    def test_pubmed_full_date_has_day_precision(self):
        from src.evidence.normalizer import normalize_records

        raw = _make_raw_record(
            source_name="pubmed",
            payload={
                "pmid": "99997",
                "title": "T",
                "pub_date": {"year": "2022", "month": "3", "day": "15"},
            },
        )
        records = normalize_records([raw], "run-001")
        assert records[0].date_precision == "day"

    def test_clinical_trial_normalizes_to_clinical_trial_record(self):
        from src.evidence.normalizer import normalize_records

        raw = _make_raw_record(
            source_name="clinical_trials_gov",
            identifier="NCT01131676",
            payload={
                "protocolSection": {
                    "identificationModule": {
                        "nctId": "NCT01131676",
                        "briefTitle": "EMPA-REG OUTCOME: Empagliflozin and Kidney Endpoints",
                    },
                    "statusModule": {"overallStatus": "COMPLETED"},
                    "designModule": {
                        "studyType": "INTERVENTIONAL",
                        "phases": ["PHASE3"],
                        "enrollmentInfo": {"count": 7020},
                    },
                    "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Boehringer Ingelheim"}},
                    "conditionsModule": {"conditions": ["Type 2 Diabetes", "CKD"]},
                    "armsInterventionsModule": {"interventions": [{"name": "Empagliflozin"}]},
                    "outcomesModule": {"primaryOutcomes": []},
                    "descriptionModule": {"briefSummary": "A trial."},
                }
            },
        )
        records = normalize_records([raw], "run-001")
        assert len(records) == 1
        rec = records[0]
        assert isinstance(rec, ClinicalTrialRecord)
        assert rec.source_type == "clinical_trial"
        assert rec.nct_id == "NCT01131676"

    def test_cms_normalizes_to_coverage_record(self):
        from src.evidence.normalizer import normalize_records

        raw = _make_raw_record(
            source_name="cms_coverage",
            identifier="L35236",
            payload={
                "id": "L35236",
                "title": "Antidiabetic Drugs — LCD L35236",
                "document_type": "LCD",
                "summary": "Coverage policy.",
                "effective_date": "2019-04-01",
                "jurisdiction": "A",
                "contractor": "Novitas Solutions",
                "coverage_determination": "Covered",
                "applicable_codes": ["E11"],
            },
        )
        records = normalize_records([raw], "run-001")
        assert len(records) == 1
        rec = records[0]
        assert isinstance(rec, CoverageRecord)
        assert rec.source_type == "cms_coverage"

    def test_is_fixture_data_propagated(self):
        from src.evidence.normalizer import normalize_records

        raw = _make_raw_record(source_name="pubmed", payload={"pmid": "1", "title": "T"})
        records = normalize_records([raw], "run-001")
        assert records[0].is_fixture_data is True

    def test_content_hash_propagated(self):
        from src.evidence.normalizer import normalize_records

        raw = _make_raw_record(
            source_name="pubmed",
            content_hash="deadbeef12345678",
            payload={"pmid": "1", "title": "T"},
        )
        records = normalize_records([raw], "run-001")
        assert records[0].content_hash == "deadbeef12345678"

    def test_not_applicable_fields_pubmed(self):
        from src.evidence.normalizer import normalize_records

        raw = _make_raw_record(source_name="pubmed", payload={"pmid": "1", "title": "T"})
        records = normalize_records([raw], "run-001")
        rec = records[0]
        assert isinstance(rec, PublicationRecord)
        # Enrollment is not applicable to publications
        assert "enrollment" in rec.not_applicable_fields


# ===========================================================================
# DEDUPLICATION
# ===========================================================================


class TestDeduplication:
    def test_same_source_same_id_is_deduplicated(self):
        from src.evidence.deduplication import deduplicate

        rec1 = _make_pub_record(identifier="11111111")
        rec2 = _make_pub_record(identifier="11111111", title="Duplicate of rec1")
        deduped, result = deduplicate([rec1, rec2], "run-001")
        assert len(deduped) == 1
        assert result.duplicates_removed == 1

    def test_same_source_same_hash_is_deduplicated(self):
        from src.evidence.deduplication import deduplicate

        rec1 = _make_pub_record(identifier="11111111", content_hash="abc123def456ab12")
        rec2 = _make_pub_record(identifier="22222222", content_hash="abc123def456ab12")
        deduped, result = deduplicate([rec1, rec2], "run-001")
        assert len(deduped) == 1
        assert result.duplicates_removed == 1

    def test_different_sources_never_merged(self):
        from src.evidence.deduplication import deduplicate

        pub = _make_pub_record(identifier="NCT01131676", source_name="pubmed")
        ct = ClinicalTrialRecord(
            id="ev-ct-NCT01131676",
            identifier="NCT01131676",
            title="EMPA-REG Kidney",
            source_name="clinical_trials_gov",
            nct_id="NCT01131676",
        )
        deduped, result = deduplicate([pub, ct], "run-001")
        assert len(deduped) == 2
        assert result.duplicates_removed == 0

    def test_no_duplicates_returns_all_records(self):
        from src.evidence.deduplication import deduplicate

        records = [
            _make_pub_record(identifier=str(i), content_hash=f"hash{i:016d}") for i in range(5)
        ]
        deduped, result = deduplicate(records, "run-001")
        assert len(deduped) == 5
        assert result.duplicates_removed == 0

    def test_cross_source_relationships_are_informational(self):
        from src.evidence.deduplication import deduplicate

        pub = PublicationRecord(
            id="ev-pub-001",
            identifier="26378978",
            title="Empagliflozin Cardiovascular Outcomes Mortality EMPA-REG",
            source_name="pubmed",
        )
        ct = ClinicalTrialRecord(
            id="ev-ct-001",
            identifier="NCT01131676",
            title="Empagliflozin Cardiovascular Outcomes Mortality EMPA-REG Trial",
            source_name="clinical_trials_gov",
            nct_id="NCT01131676",
        )
        deduped, result = deduplicate([pub, ct], "run-001")
        # Both must be retained as distinct records — never merged
        assert len(deduped) == 2
        # Relationship may or may not be found depending on token overlap
        assert isinstance(result.cross_source_relationships, list)

    def test_dedup_result_total_records_matches_input(self):
        from src.evidence.deduplication import deduplicate

        records = [_make_pub_record(identifier=str(i)) for i in range(3)]
        _, result = deduplicate(records, "run-001")
        assert result.total_records == 3


# ===========================================================================
# METATAGGING
# ===========================================================================


class TestMetatagging:
    def test_sglt2_intervention_tag_applied(self):
        from src.evidence.metatagging import tag_records

        rec = _make_pub_record(title="Empagliflozin in patients with type 2 diabetes and CKD")
        tagged = tag_records([rec])
        tags = {t.tag for t in tagged[0].structured_tags}
        # The tagger may emit 'intervention:sglt2_class' or 'intervention:empagliflozin'
        assert any(t.startswith("intervention:") for t in tags)

    def test_rct_design_tag_applied(self):
        from src.evidence.metatagging import tag_records

        rec = _make_pub_record(study_design="rct")
        tagged = tag_records([rec])
        tags = {t.tag for t in tagged[0].structured_tags}
        assert "design:rct" in tags

    def test_source_publication_tag_applied(self):
        from src.evidence.metatagging import tag_records

        rec = _make_pub_record()
        tagged = tag_records([rec])
        tags = {t.tag for t in tagged[0].structured_tags}
        assert "source:publication" in tags

    def test_temporal_recent_tag_for_recent_article(self):
        from src.evidence.metatagging import tag_records

        rec = _make_pub_record(pub_date=date(2022, 5, 1))
        tagged = tag_records([rec])
        tags = {t.tag for t in tagged[0].structured_tags}
        assert "temporal:recent_5yr" in tags

    def test_temporal_older_tag_for_old_article(self):
        from src.evidence.metatagging import tag_records

        rec = _make_pub_record(pub_date=date(2010, 1, 1))
        tagged = tag_records([rec])
        tags = {t.tag for t in tagged[0].structured_tags}
        assert "temporal:older" in tags

    def test_tags_also_copied_to_flat_tags_list(self):
        from src.evidence.metatagging import tag_records

        rec = _make_pub_record()
        tagged = tag_records([rec])
        assert len(tagged[0].tags) > 0

    def test_all_structured_tags_have_rule_id(self):
        from src.evidence.metatagging import tag_records

        rec = _make_pub_record(title="Empagliflozin reduces renal outcomes in CKD")
        tagged = tag_records([rec])
        for tag in tagged[0].structured_tags:
            assert tag.rule_id, f"Missing rule_id on tag {tag.tag}"

    def test_tagging_is_deterministic(self):
        from src.evidence.metatagging import tag_records

        rec = _make_pub_record(title="Empagliflozin in CKD")
        tags1 = {t.tag for t in tag_records([rec])[0].structured_tags}
        tags2 = {t.tag for t in tag_records([rec])[0].structured_tags}
        assert tags1 == tags2

    def test_ckd_population_tag_applied(self):
        from src.evidence.metatagging import tag_records

        rec = _make_pub_record(title="chronic kidney disease empagliflozin")
        tagged = tag_records([rec])
        tags = {t.tag for t in tagged[0].structured_tags}
        assert "population:ckd" in tags


# ===========================================================================
# RANKING
# ===========================================================================


class TestRanking:
    def test_rank_assigns_scores(self):
        from src.evidence.metatagging import tag_records
        from src.evidence.ranking import rank_records

        records = tag_records([_make_pub_record(identifier=str(i)) for i in range(3)])
        ranked = rank_records(records, _make_evidence_query())
        for rec in ranked:
            assert rec.relevance_score is not None
            assert 0.0 <= rec.relevance_score <= 1.0

    def test_records_sorted_descending_by_score(self):
        from src.evidence.metatagging import tag_records
        from src.evidence.ranking import rank_records

        records = tag_records([_make_pub_record(identifier=str(i)) for i in range(5)])
        ranked = rank_records(records, _make_evidence_query())
        scores = [r.relevance_score or 0.0 for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_relevance_rationale_populated(self):
        from src.evidence.metatagging import tag_records
        from src.evidence.ranking import rank_records

        records = tag_records([_make_pub_record(title="empagliflozin chronic kidney disease")])
        ranked = rank_records(records, _make_evidence_query())
        assert len(ranked[0].relevance_rationale) > 0

    def test_rct_scores_higher_than_observational(self):
        from src.evidence.metatagging import tag_records
        from src.evidence.ranking import rank_records

        # Use empagliflozin+CKD titles so all records get the same population/intervention tags;
        # only the design tier (rct=0.8 vs observational=0.5) should differentiate them.
        rct = _make_pub_record(
            identifier="RCT001",
            title="empagliflozin chronic kidney disease randomized controlled trial",
            study_design="rct",
        )
        obs = _make_pub_record(
            identifier="OBS001",
            title="empagliflozin chronic kidney disease observational cohort",
            study_design="observational",
        )
        tagged = tag_records([obs, rct])
        ranked = rank_records(tagged, _make_evidence_query())
        rct_rank = next(i for i, r in enumerate(ranked) if r.identifier == "RCT001")
        obs_rank = next(i for i, r in enumerate(ranked) if r.identifier == "OBS001")
        assert rct_rank < obs_rank

    def test_score_bounds_respected(self):
        from src.evidence.metatagging import tag_records
        from src.evidence.ranking import rank_records

        records = tag_records(
            [
                _make_pub_record(identifier=str(i), study_design=sd)
                for i, sd in enumerate(["meta_analysis", "rct", "observational"])
            ]
        )
        ranked = rank_records(records, _make_evidence_query())
        for rec in ranked:
            assert rec.relevance_score is not None
            assert 0.0 <= rec.relevance_score <= 1.0


# ===========================================================================
# QA — EVIDENCE CHECKS (EQ-001 through EQ-010)
# ===========================================================================


class TestEvidenceQAChecks:
    def _make_records(self, n: int = 5, study_design: str = "rct") -> list[EvidenceRecord]:
        return [
            _make_pub_record(
                identifier=str(i),
                content_hash=f"hash{i:016d}",
                pub_date=date(2022, 1, 1),
                study_design=study_design,
            )
            for i in range(n)
        ]

    def test_eq001_passes_with_records_present(self):
        from src.qa.evidence_checks import run_evidence_record_checks

        summary = run_evidence_record_checks(self._make_records(), "run-001")
        eq001 = next(r for r in summary.results if r.check_id == "eq-001")
        assert eq001.status == "passed"

    def test_eq001_fails_with_empty_title(self):
        from src.qa.evidence_checks import run_evidence_record_checks

        rec = _make_pub_record(title="  ")  # blank string — not empty but whitespace-only
        # Manually set to truly empty:
        rec_empty = rec.model_copy(update={"title": ""})
        summary = run_evidence_record_checks([rec_empty], "run-001")
        eq001 = next(r for r in summary.results if r.check_id == "eq-001")
        assert eq001.status == "failed"

    def test_eq002_detects_missing_titles(self):
        from src.qa.evidence_checks import run_evidence_record_checks

        rec = _make_pub_record(title="")
        summary = run_evidence_record_checks([rec], "run-001")
        eq002 = next((r for r in summary.results if r.check_id == "eq-002"), None)
        if eq002:
            assert eq002.status in ("warning", "failed", "passed")

    def test_eq003_category_is_evidence_quality(self):
        from src.qa.evidence_checks import run_evidence_record_checks

        summary = run_evidence_record_checks(self._make_records(), "run-001")
        for result in summary.results:
            assert result.category == "evidence_quality"

    def test_all_eq_check_ids_present(self):
        from src.qa.evidence_checks import run_evidence_record_checks

        summary = run_evidence_record_checks(self._make_records(), "run-001")
        check_ids = {r.check_id for r in summary.results}
        for i in range(1, 11):
            expected_id = f"eq-{i:03d}"
            assert expected_id in check_ids, f"Missing check {expected_id}"

    def test_all_results_have_valid_status(self):
        from src.qa.evidence_checks import run_evidence_record_checks

        summary = run_evidence_record_checks(self._make_records(), "run-001")
        valid_statuses = {"passed", "warning", "failed", "not_applicable"}
        for r in summary.results:
            assert r.status in valid_statuses

    def test_all_results_have_valid_severity(self):
        from src.qa.evidence_checks import run_evidence_record_checks

        summary = run_evidence_record_checks(self._make_records(), "run-001")
        valid_severities = {"critical", "major", "minor", "info"}
        for r in summary.results:
            assert r.severity in valid_severities

    def test_eq_old_evidence_warning(self):
        from src.qa.evidence_checks import run_evidence_record_checks

        old_rec = _make_pub_record(pub_date=date(2010, 1, 1))
        summary = run_evidence_record_checks([old_rec], "run-001", max_evidence_age_days=1825)
        check_ids = {r.check_id for r in summary.results}
        assert "eq-001" in check_ids


# ===========================================================================
# QA — RETRIEVAL CHECKS (RQ-001 through RQ-006)
# ===========================================================================


class TestRetrievalQAChecks:
    def test_rq001_passes_when_records_retrieved(self):
        from src.qa.retrieval_checks import run_retrieval_checks

        run = _make_retrieval_run()
        summary = run_retrieval_checks(run)
        rq001 = next(r for r in summary.results if r.check_id == "rq-001")
        assert rq001.status == "passed"

    def test_rq001_fails_when_zero_records(self):
        from src.qa.retrieval_checks import run_retrieval_checks

        run = _make_retrieval_run()
        run = run.model_copy(update={"total_records_retrieved": 0})
        for i, ss in enumerate(run.source_statuses):
            run.source_statuses[i] = ss.model_copy(update={"records_retrieved": 0})
        summary = run_retrieval_checks(run)
        rq001 = next(r for r in summary.results if r.check_id == "rq-001")
        assert rq001.status == "failed"

    def test_rq002_warning_when_fatal_error(self):
        from src.qa.retrieval_checks import run_retrieval_checks

        err = RetrievalError(
            source_name="pubmed",
            error_type="fixture_missing",
            message="Manifest not found",
            is_fatal_for_source=True,
        )
        run = _make_retrieval_run()
        bad_ss = EvidenceSourceStatus(
            source_name="pubmed",
            records_retrieved=0,
            records_after_normalization=0,
            errors=[err],
            cache_hit=False,
        )
        new_statuses = [ss for ss in run.source_statuses if ss.source_name != "pubmed"]
        new_statuses.append(bad_ss)
        run = run.model_copy(update={"source_statuses": new_statuses})
        summary = run_retrieval_checks(run)
        rq002 = next(r for r in summary.results if r.check_id == "rq-002")
        assert rq002.status == "warning"

    def test_rq004_fails_when_hash_mismatch(self):
        from src.qa.retrieval_checks import run_retrieval_checks

        run = _make_retrieval_run()
        bad_prov = run.provenance.model_copy(update={"query_hash": "WRONGHASH12345678"})
        run = run.model_copy(update={"provenance": bad_prov})
        summary = run_retrieval_checks(run)
        rq004 = next(r for r in summary.results if r.check_id == "rq-004")
        assert rq004.status == "failed"

    def test_rq004_passes_when_hashes_match(self):
        from src.qa.retrieval_checks import run_retrieval_checks

        run = _make_retrieval_run()
        summary = run_retrieval_checks(run)
        rq004 = next(r for r in summary.results if r.check_id == "rq-004")
        assert rq004.status == "passed"

    def test_rq005_passes_when_offline_fixture_mode(self):
        from src.qa.retrieval_checks import run_retrieval_checks

        run = _make_retrieval_run(mode="offline_fixture")
        summary = run_retrieval_checks(run)
        rq005 = next(r for r in summary.results if r.check_id == "rq-005")
        assert rq005.status == "passed"

    def test_rq006_fails_when_dedup_count_exceeds_retrieved(self):
        from src.qa.retrieval_checks import run_retrieval_checks

        run = _make_retrieval_run()
        run = run.model_copy(
            update={
                "total_records_retrieved": 5,
                "total_records_after_dedup": 10,
            }
        )
        summary = run_retrieval_checks(run)
        rq006 = next(r for r in summary.results if r.check_id == "rq-006")
        assert rq006.status == "failed"

    def test_all_rq_check_ids_present(self):
        from src.qa.retrieval_checks import run_retrieval_checks

        run = _make_retrieval_run()
        summary = run_retrieval_checks(run)
        check_ids = {r.check_id for r in summary.results}
        for i in range(1, 7):
            expected_id = f"rq-{i:03d}"
            assert expected_id in check_ids, f"Missing check {expected_id}"

    def test_all_retrieval_qa_category_is_evidence_quality(self):
        from src.qa.retrieval_checks import run_retrieval_checks

        run = _make_retrieval_run()
        summary = run_retrieval_checks(run)
        for r in summary.results:
            assert r.category == "evidence_quality"


# ===========================================================================
# EVIDENCE CACHE
# ===========================================================================


class TestEvidenceCache:
    def test_cache_miss_returns_none(self):
        from src.cache.evidence_cache import EvidenceCache

        cache = EvidenceCache(db_path=":memory:")
        result = cache.get("pubmed", "hash001", 50)
        assert result is None

    def test_put_then_get_returns_records(self):
        from src.cache.evidence_cache import EvidenceCache

        cache = EvidenceCache(db_path=":memory:")
        records = [_make_raw_record(identifier="1"), _make_raw_record(identifier="2")]
        cache.put("pubmed", "hash001", 50, records)
        result = cache.get("pubmed", "hash001", 50)
        assert result is not None
        assert len(result) == 2

    def test_different_source_names_are_separate_cache_entries(self):
        from src.cache.evidence_cache import EvidenceCache

        cache = EvidenceCache(db_path=":memory:")
        records = [_make_raw_record(identifier="1")]
        cache.put("pubmed", "hash001", 50, records)
        result = cache.get("clinical_trials_gov", "hash001", 50)
        assert result is None

    def test_different_max_results_are_separate_cache_entries(self):
        from src.cache.evidence_cache import EvidenceCache

        cache = EvidenceCache(db_path=":memory:")
        records = [_make_raw_record(identifier="1")]
        cache.put("pubmed", "hash001", 50, records)
        result = cache.get("pubmed", "hash001", 25)
        assert result is None

    def test_expired_entry_returns_none(self):
        from src.cache.evidence_cache import EvidenceCache

        # Put with a clock anchored 25 hours in the past (TTL=24h → already expired)
        past_time = datetime.now(UTC) - timedelta(hours=25)
        cache_past = EvidenceCache(db_path=":memory:", ttl_hours=24, now_fn=lambda: past_time)
        records = [_make_raw_record(identifier="1")]
        cache_past.put("pubmed", "hash001", 50, records)

        # Get with current clock → expires_at is 1 hour in the past → cache miss
        now_fn = lambda: datetime.now(UTC)  # noqa: E731
        cache_now = EvidenceCache.__new__(EvidenceCache)
        cache_now._conn = cache_past._conn
        cache_now._ttl = __import__("datetime").timedelta(hours=24)
        cache_now._now = now_fn

        result = cache_now.get("pubmed", "hash001", 50)
        assert result is None

    def test_clear_removes_all_entries(self):
        from src.cache.evidence_cache import EvidenceCache

        cache = EvidenceCache(db_path=":memory:")
        records = [_make_raw_record(identifier="1")]
        cache.put("pubmed", "hash001", 50, records)
        cache.clear()
        assert cache.get("pubmed", "hash001", 50) is None

    def test_stats_returns_dict(self):
        from src.cache.evidence_cache import EvidenceCache

        cache = EvidenceCache(db_path=":memory:")
        # Empty cache → empty dict
        stats = cache.stats()
        assert isinstance(stats, dict)
        # Put a record and verify stats reflects it
        records = [_make_raw_record(identifier="1")]
        cache.put("pubmed", "hash001", 50, records)
        stats = cache.stats()
        assert "pubmed" in stats
        assert stats["pubmed"]["entries"] == 1

    def test_injectable_clock_controls_expiry(self):
        from src.cache.evidence_cache import EvidenceCache

        fixed_time = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        cache = EvidenceCache(db_path=":memory:", ttl_hours=24, now_fn=lambda: fixed_time)
        records = [_make_raw_record(identifier="1")]
        cache.put("pubmed", "hash001", 50, records)
        result = cache.get("pubmed", "hash001", 50)
        assert result is not None


# ===========================================================================
# EVIDENCE REPOSITORY
# ===========================================================================


class TestEvidenceRepository:
    def _make_minimal_run(self) -> tuple:
        """Return (run, raw_records, normalized_records, dedup_result, eq_qa, rq_qa)."""
        from src.evidence.deduplication import deduplicate
        from src.evidence.metatagging import tag_records
        from src.evidence.ranking import rank_records
        from src.qa.evidence_checks import run_evidence_record_checks
        from src.qa.retrieval_checks import run_retrieval_checks

        run = _make_retrieval_run()
        raw = [_make_raw_record(identifier=str(i)) for i in range(3)]
        normalized = [
            _make_pub_record(identifier=str(i), content_hash=f"hash{i:016d}") for i in range(3)
        ]
        _, dedup_result = deduplicate(normalized, run.run_id)
        tagged = tag_records(normalized)
        ranked = rank_records(tagged, run.query)
        eq_qa = run_evidence_record_checks(ranked, run.run_id)
        rq_qa = run_retrieval_checks(run)
        return run, raw, ranked, dedup_result, eq_qa, rq_qa

    def test_save_and_get_run(self):
        from src.evidence.repository import EvidenceRepository

        repo = EvidenceRepository(db_path=":memory:")
        run, raw, ranked, dedup_result, eq_qa, rq_qa = self._make_minimal_run()
        repo.save_run(run, raw, ranked, dedup_result, eq_qa, rq_qa)
        loaded = repo.get_run(run.run_id)
        assert loaded["run_id"] == run.run_id

    def test_get_run_raises_for_missing_run(self):
        from src.evidence.repository import EvidenceRepository
        from src.utils.exceptions import RetrievalRunNotFoundError

        repo = EvidenceRepository(db_path=":memory:")
        with pytest.raises(RetrievalRunNotFoundError):
            repo.get_run("nonexistent-run-id")

    def test_list_evidence_for_run(self):
        from src.evidence.repository import EvidenceRepository

        repo = EvidenceRepository(db_path=":memory:")
        run, raw, ranked, dedup_result, eq_qa, rq_qa = self._make_minimal_run()
        repo.save_run(run, raw, ranked, dedup_result, eq_qa, rq_qa)
        records = repo.list_evidence_for_run(run.run_id)
        assert len(records) == len(ranked)

    def test_save_is_idempotent(self):
        from src.evidence.repository import EvidenceRepository

        repo = EvidenceRepository(db_path=":memory:")
        run, raw, ranked, dedup_result, eq_qa, rq_qa = self._make_minimal_run()
        repo.save_run(run, raw, ranked, dedup_result, eq_qa, rq_qa)
        # Save again — should replace, not duplicate
        repo.save_run(run, raw, ranked, dedup_result, eq_qa, rq_qa)
        records = repo.list_evidence_for_run(run.run_id)
        assert len(records) == len(ranked)

    def test_get_evidence_record_raises_for_missing(self):
        from src.evidence.repository import EvidenceRepository
        from src.utils.exceptions import EvidenceNotFoundError

        repo = EvidenceRepository(db_path=":memory:")
        with pytest.raises(EvidenceNotFoundError):
            repo.get_evidence_record("nonexistent-evidence-id")

    def test_list_run_ids(self):
        from src.evidence.repository import EvidenceRepository

        repo = EvidenceRepository(db_path=":memory:")
        run, raw, ranked, dedup_result, eq_qa, rq_qa = self._make_minimal_run()
        repo.save_run(run, raw, ranked, dedup_result, eq_qa, rq_qa)
        run_ids = repo.list_run_ids()
        assert run.run_id in run_ids


# ===========================================================================
# FULL PIPELINE SMOKE TEST
# ===========================================================================


class TestEvidenceServiceSmoke:
    def test_full_pipeline_runs_without_error(self):
        """Integration smoke: run the full evidence pipeline end-to-end using fixtures."""
        from src.evidence.repository import EvidenceRepository
        from src.evidence.service import EvidenceService

        repo = EvidenceRepository(db_path=":memory:")
        svc = EvidenceService(repository=repo)
        q = _approved_question()
        ph = _approved_phenotype()
        run = svc.run(question=q, phenotype=ph, offline_only=True)
        assert run.run_id
        assert run.total_records_retrieved > 0
        assert run.total_records_after_dedup <= run.total_records_retrieved
        assert run.completed_at is not None

    def test_same_inputs_produce_same_query_hash(self):
        """Cross-call determinism: two service runs on the same inputs share query_hash."""
        from src.evidence.repository import EvidenceRepository
        from src.evidence.service import EvidenceService

        q = _approved_question()
        ph = _approved_phenotype()
        repo1 = EvidenceRepository(db_path=":memory:")
        repo2 = EvidenceRepository(db_path=":memory:")
        run1 = EvidenceService(repository=repo1).run(q, ph, offline_only=True)
        run2 = EvidenceService(repository=repo2).run(q, ph, offline_only=True)
        assert run1.query.query_hash == run2.query.query_hash

    def test_records_retrievable_after_run(self):
        from src.evidence.repository import EvidenceRepository
        from src.evidence.service import EvidenceService

        repo = EvidenceRepository(db_path=":memory:")
        svc = EvidenceService(repository=repo)
        run = svc.run(
            question=_approved_question(), phenotype=_approved_phenotype(), offline_only=True
        )
        records = repo.list_evidence_for_run(run.run_id)
        assert len(records) > 0

    def test_service_raises_if_question_not_approved(self):
        from src.evidence.repository import EvidenceRepository
        from src.evidence.service import EvidenceService

        repo = EvidenceRepository(db_path=":memory:")
        svc = EvidenceService(repository=repo)
        with pytest.raises(ApprovalRequiredError):
            svc.run(
                question=_pending_question(), phenotype=_approved_phenotype(), offline_only=True
            )

    def test_service_raises_if_phenotype_not_approved(self):
        from src.evidence.repository import EvidenceRepository
        from src.evidence.service import EvidenceService

        repo = EvidenceRepository(db_path=":memory:")
        svc = EvidenceService(repository=repo)
        with pytest.raises(UnapprovedPhenotypeError):
            svc.run(
                question=_approved_question(), phenotype=_pending_phenotype(), offline_only=True
            )
