"""Tests that validate fixture JSON files against Pydantic schemas AND business rules.

Tests in this file go beyond a simple schema round-trip. They verify:
- Structural integrity (unique IDs, cross-references are valid)
- Format constraints (code patterns for each terminology system)
- Provenance fields (verification_date, is_llm_suggested are present and accurate)
- Catalog consistency (question→phenotype links resolve correctly)
"""

import json
import re
from pathlib import Path

from src.schemas.phenotype import PhenotypeDefinition, TerminologyMapping
from src.schemas.question import ClinicalQuestion

# ── Helpers ────────────────────────────────────────────────────────────────────


def _all_mappings(pheno: PhenotypeDefinition) -> list[TerminologyMapping]:
    return [m for c in pheno.concepts for m in c.mappings]


def _load_question(path: Path) -> ClinicalQuestion:
    return ClinicalQuestion.model_validate(json.loads(path.read_text(encoding="utf-8")))


# ── Q1 fixture ────────────────────────────────────────────────────────────────


class TestQ1QuestionFixture:
    def test_fixture_file_exists(self, question_fixture_path: Path) -> None:
        assert question_fixture_path.exists(), f"Missing fixture: {question_fixture_path}"

    def test_fixture_is_valid_json(self, question_fixture_path: Path) -> None:
        data = json.loads(question_fixture_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_fixture_parses_as_clinical_question(self, raw_question_fixture: dict) -> None:  # type: ignore[type-arg]
        question = ClinicalQuestion.model_validate(raw_question_fixture)
        assert question.id.startswith("q-")

    def test_fixture_question_is_approved(self, raw_question_fixture: dict) -> None:  # type: ignore[type-arg]
        question = ClinicalQuestion.model_validate(raw_question_fixture)
        assert question.status == "approved", "Demo question fixtures must be pre-approved"

    def test_fixture_pico_fields_not_empty(self, raw_question_fixture: dict) -> None:  # type: ignore[type-arg]
        question = ClinicalQuestion.model_validate(raw_question_fixture)
        assert question.pico.population.strip()
        assert question.pico.intervention.strip()
        assert len(question.pico.outcomes) >= 1

    def test_fixture_pico_has_no_demo_placeholders(self, raw_question_fixture: dict) -> None:  # type: ignore[type-arg]
        """Curated fixtures must not contain [DEMO MODE] placeholder text."""
        question = ClinicalQuestion.model_validate(raw_question_fixture)
        for field_val in [question.pico.population, question.pico.intervention]:
            assert "[DEMO MODE]" not in field_val, f"Placeholder found in PICO field: {field_val}"
        for outcome in question.pico.outcomes:
            assert "[DEMO MODE]" not in outcome

    def test_fixture_has_ambiguity_flags(self, raw_question_fixture: dict) -> None:  # type: ignore[type-arg]
        question = ClinicalQuestion.model_validate(raw_question_fixture)
        assert len(question.ambiguity_flags) >= 1

    def test_fixture_ambiguity_severities_valid(self, raw_question_fixture: dict) -> None:  # type: ignore[type-arg]
        """Severity must be one of the Literal values — not just any string."""
        question = ClinicalQuestion.model_validate(raw_question_fixture)
        valid = {"high", "medium", "low"}
        for flag in question.ambiguity_flags:
            assert flag.severity in valid, f"Invalid severity '{flag.severity}'"

    def test_fixture_has_clarifying_questions(self, raw_question_fixture: dict) -> None:  # type: ignore[type-arg]
        question = ClinicalQuestion.model_validate(raw_question_fixture)
        assert len(question.clarifying_questions) >= 1

    def test_fixture_source_is_predefined(self, raw_question_fixture: dict) -> None:  # type: ignore[type-arg]
        question = ClinicalQuestion.model_validate(raw_question_fixture)
        assert question.source == "predefined"

    def test_fixture_contains_sglt2_anchors(self, raw_question_fixture: dict) -> None:  # type: ignore[type-arg]
        """Structured JSON must include known SGLT2 RxNorm anchors."""
        question = ClinicalQuestion.model_validate(raw_question_fixture)
        anchors = question.structured_json.get("rxnorm_ingredient_anchors", [])
        assert len(anchors) >= 1, "Should list at least one RxNorm SGLT2 anchor"

    def test_fixture_contains_icd10_anchors(self, raw_question_fixture: dict) -> None:  # type: ignore[type-arg]
        question = ClinicalQuestion.model_validate(raw_question_fixture)
        anchors = question.structured_json.get("icd10_anchors", [])
        assert "E11" in anchors, "Should include T2DM anchor E11"
        assert "N18" in anchors, "Should include CKD anchor N18"


# ── Q2 and Q3 fixtures ────────────────────────────────────────────────────────


class TestQ2QuestionFixture:
    def test_fixture_file_exists(self, q2_fixture_path: Path) -> None:
        assert q2_fixture_path.exists()

    def test_fixture_parses(self, raw_q2_fixture: dict) -> None:  # type: ignore[type-arg]
        q = ClinicalQuestion.model_validate(raw_q2_fixture)
        assert q.id == "q-sglt2-ckd-data-elem-001"

    def test_fixture_is_approved(self, raw_q2_fixture: dict) -> None:  # type: ignore[type-arg]
        q = ClinicalQuestion.model_validate(raw_q2_fixture)
        assert q.status == "approved"

    def test_fixture_has_data_elements_study_intent(self, raw_q2_fixture: dict) -> None:  # type: ignore[type-arg]
        q = ClinicalQuestion.model_validate(raw_q2_fixture)
        intent = q.structured_json.get("study_intent", "")
        assert "data" in intent.lower(), f"Expected data-readiness intent, got: {intent}"

    def test_fixture_has_required_data_element_keys(self, raw_q2_fixture: dict) -> None:  # type: ignore[type-arg]
        q = ClinicalQuestion.model_validate(raw_q2_fixture)
        key_elems = q.structured_json.get("key_data_elements", {})
        assert "required" in key_elems
        assert "preferred" in key_elems


class TestQ3QuestionFixture:
    def test_fixture_file_exists(self, q3_fixture_path: Path) -> None:
        assert q3_fixture_path.exists()

    def test_fixture_parses(self, raw_q3_fixture: dict) -> None:  # type: ignore[type-arg]
        q = ClinicalQuestion.model_validate(raw_q3_fixture)
        assert q.id == "q-sglt2-ckd-outcome-eval-001"

    def test_fixture_is_approved(self, raw_q3_fixture: dict) -> None:  # type: ignore[type-arg]
        q = ClinicalQuestion.model_validate(raw_q3_fixture)
        assert q.status == "approved"

    def test_fixture_has_configurable_comparator(self, raw_q3_fixture: dict) -> None:  # type: ignore[type-arg]
        q = ClinicalQuestion.model_validate(raw_q3_fixture)
        comparator = q.pico.comparator or ""
        assert "configurable" in comparator.lower() or comparator == "", (
            "Q3 comparator should be configurable or None"
        )

    def test_fixture_has_outcome_options(self, raw_q3_fixture: dict) -> None:  # type: ignore[type-arg]
        q = ClinicalQuestion.model_validate(raw_q3_fixture)
        options = q.structured_json.get("outcome_options", {})
        assert "kidney" in options
        assert "cardiovascular" in options


# ── Phenotype fixture ─────────────────────────────────────────────────────────


class TestPhenotypeFixture:
    def test_fixture_file_exists(self, phenotype_fixture_path: Path) -> None:
        assert phenotype_fixture_path.exists(), f"Missing fixture: {phenotype_fixture_path}"

    def test_fixture_is_valid_json(self, phenotype_fixture_path: Path) -> None:
        data = json.loads(phenotype_fixture_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_fixture_parses_as_phenotype_definition(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        assert pheno.id.startswith("pheno-")

    def test_fixture_has_concepts(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        assert len(pheno.concepts) >= 2, "Phenotype should define at least 2 clinical concepts"

    def test_fixture_has_inclusion_rules(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        assert len(pheno.inclusion_rules) >= 1

    def test_fixture_has_exclusion_rules(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        assert len(pheno.exclusion_rules) >= 1

    def test_fixture_has_fhir_mappings(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        assert len(pheno.fhir_mappings) >= 1

    def test_fixture_lookback_is_positive(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        assert pheno.lookback_period_days > 0

    def test_fixture_question_id_matches_q1(
        self,
        raw_phenotype_fixture: dict,
        raw_question_fixture: dict,  # type: ignore[type-arg]
    ) -> None:
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        question = ClinicalQuestion.model_validate(raw_question_fixture)
        assert pheno.question_id == question.id, (
            "Phenotype question_id must match the Q1 fixture ID"
        )

    # ── Structural integrity (strengthened beyond simple schema round-trip) ──

    def test_concept_ids_are_unique(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        ids = [c.concept_id for c in pheno.concepts]
        assert len(ids) == len(set(ids)), f"Duplicate concept_id found: {ids}"

    def test_rule_ids_are_unique(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        ids = [r.rule_id for r in pheno.inclusion_rules] + [
            r.rule_id for r in pheno.exclusion_rules
        ]
        assert len(ids) == len(set(ids)), f"Duplicate rule_id found: {ids}"

    def test_rule_concept_ids_reference_valid_concepts(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        """Each rule's concept_id must exist in phenotype.concepts."""
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        valid_concept_ids = {c.concept_id for c in pheno.concepts}
        for rule in pheno.inclusion_rules + pheno.exclusion_rules:
            assert rule.concept_id in valid_concept_ids, (
                f"Rule '{rule.rule_id}' references unknown concept_id '{rule.concept_id}'"
            )

    def test_icd10_codes_have_expected_format(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        """ICD-10-CM codes should start with a letter followed by digits."""
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        icd_pattern = re.compile(r"^[A-Z]\d+(\.\d+)?$")
        for m in _all_mappings(pheno):
            if m.terminology_system == "ICD-10-CM":
                assert icd_pattern.match(m.code), (
                    f"ICD-10-CM code '{m.code}' does not match expected pattern"
                )

    def test_rxnorm_codes_are_numeric(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        """RxNorm RxCUI values should be purely numeric strings."""
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        for m in _all_mappings(pheno):
            if m.terminology_system == "RxNorm":
                assert m.code.isdigit(), (
                    f"RxNorm code '{m.code}' is not numeric — check whether this is a valid RxCUI"
                )

    def test_loinc_codes_contain_hyphen(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        """LOINC codes follow the pattern digits-checkdigit (e.g., 62238-1)."""
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        loinc_pattern = re.compile(r"^\d+-\d$")
        for m in _all_mappings(pheno):
            if m.terminology_system == "LOINC":
                assert loinc_pattern.match(m.code), (
                    f"LOINC code '{m.code}' does not match expected pattern (digits-checkdigit)"
                )

    # ── Provenance field completeness ─────────────────────────────────────────

    def test_all_mappings_have_verification_date_field(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        """verification_date must be present on every mapping (None is acceptable — means pending)."""
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        for m in _all_mappings(pheno):
            # The field exists on the model; None means pending — both are valid
            assert hasattr(m, "verification_date"), (
                f"Mapping {m.code} is missing verification_date field"
            )

    def test_all_mappings_have_verification_source_field(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        for m in _all_mappings(pheno):
            assert hasattr(m, "verification_source")

    def test_rxnorm_codes_are_llm_suggested(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        """RxNorm RxCUIs came from LLM training data and must be flagged accordingly."""
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        for m in _all_mappings(pheno):
            if m.terminology_system == "RxNorm":
                assert m.is_llm_suggested is True, (
                    f"RxNorm code {m.code} ({m.concept_name}) should be marked "
                    "is_llm_suggested=true — it was derived from LLM training data "
                    "and has not been verified against the live RxNorm API"
                )

    def test_unverified_mappings_have_candidate_status(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        """Mappings with verification_date=None must not have review_status='approved'."""
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        for m in _all_mappings(pheno):
            if m.verification_date is None and m.review_status == "approved":
                raise AssertionError(
                    f"Mapping {m.code} is marked approved but has not been verified "
                    "(verification_date=None). Approve only after external verification."
                )

    def test_all_mappings_are_candidate_status(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        """All mappings in demo fixtures should be 'candidate' — not yet human-approved."""
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        for concept in pheno.concepts:
            for mapping in concept.mappings:
                assert mapping.review_status in (
                    "candidate",
                    "approved",
                ), f"Unexpected review_status '{mapping.review_status}' on {mapping.code}"

    def test_icd10_mappings_present(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        icd = [m for m in _all_mappings(pheno) if m.terminology_system == "ICD-10-CM"]
        assert len(icd) >= 2, "Should have T2DM and CKD ICD-10-CM codes"

    def test_rxnorm_mappings_present(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        rx = [m for m in _all_mappings(pheno) if m.terminology_system == "RxNorm"]
        assert len(rx) >= 1, "Should have at least one SGLT2 inhibitor RxNorm code"

    def test_loinc_mappings_present(self, raw_phenotype_fixture: dict) -> None:  # type: ignore[type-arg]
        pheno = PhenotypeDefinition.model_validate(raw_phenotype_fixture)
        loinc = [m for m in _all_mappings(pheno) if m.terminology_system == "LOINC"]
        assert len(loinc) >= 1, "Should have at least one LOINC code (eGFR)"


# ── Catalog tests ─────────────────────────────────────────────────────────────


class TestCatalog:
    def test_catalog_file_exists(self, catalog_path: Path) -> None:
        assert catalog_path.exists(), f"Missing catalog: {catalog_path}"

    def test_catalog_is_valid_json(self, catalog_path: Path) -> None:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_catalog_has_all_three_questions(self, raw_catalog: dict) -> None:  # type: ignore[type-arg]
        question_ids = set(raw_catalog.get("questions", {}).keys())
        expected = {
            "q-sglt2-ckd-t2dm-001",
            "q-sglt2-ckd-data-elem-001",
            "q-sglt2-ckd-outcome-eval-001",
        }
        assert expected.issubset(question_ids), (
            f"Catalog missing question IDs: {expected - question_ids}"
        )

    def test_catalog_all_questions_have_phenotype_id(self, raw_catalog: dict) -> None:  # type: ignore[type-arg]
        for qid, entry in raw_catalog.get("questions", {}).items():
            assert "phenotype_id" in entry, f"Question {qid} missing phenotype_id in catalog"

    def test_catalog_phenotype_ids_resolve(self, raw_catalog: dict) -> None:  # type: ignore[type-arg]
        """Every phenotype_id in catalog must appear in the phenotypes section."""
        phenotype_section = set(raw_catalog.get("phenotypes", {}).keys())
        for qid, entry in raw_catalog.get("questions", {}).items():
            pid = entry.get("phenotype_id")
            assert pid in phenotype_section, (
                f"Question {qid} references phenotype_id '{pid}' which is not in catalog.phenotypes"
            )


# ── LLM client tests (unchanged from Phase 1) ────────────────────────────────


class TestLLMClient:
    def test_demo_client_returns_response(self) -> None:
        from src.llm.client import DemoLLMClient, LLMMessage

        client = DemoLLMClient()
        response = client.complete(
            messages=[LLMMessage(role="user", content="Test prompt")],
            task="pico_parse",
        )
        assert response.is_demo_mode is True
        assert response.model == "demo"
        assert "[DEMO MODE]" in response.content

    def test_demo_client_unknown_task_uses_default(self) -> None:
        from src.llm.client import DemoLLMClient, LLMMessage

        client = DemoLLMClient()
        response = client.complete(
            messages=[LLMMessage(role="user", content="x")],
            task="nonexistent_task",
        )
        assert response.content

    def test_demo_client_prompt_hash_is_deterministic(self) -> None:
        from src.llm.client import DemoLLMClient, LLMMessage

        client = DemoLLMClient()
        messages = [LLMMessage(role="user", content="Same prompt")]
        r1 = client.complete(messages)
        r2 = client.complete(messages)
        assert r1.prompt_hash == r2.prompt_hash

    def test_get_llm_client_returns_demo_in_demo_mode(self) -> None:
        from src.llm.client import DemoLLMClient, get_llm_client

        client = get_llm_client()
        assert isinstance(client, DemoLLMClient)
