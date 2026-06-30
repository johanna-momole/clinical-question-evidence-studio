"""Deterministic demo question parser — no API key required.

Returns curated, pre-authored ParseResults for the three supported demo questions.
For unsupported questions, returns a controlled draft result labelled [DEMO MODE]
rather than hallucinating a PICO breakdown.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from src.question_parser.parser import BaseQuestionParser
from src.schemas.parsing import ParseProvenance, ParseResult
from src.schemas.question import AmbiguityFlag, ClinicalQuestion, PICOFramework

_SUPPORTED_IDS = frozenset(
    [
        "q-sglt2-ckd-t2dm-001",
        "q-sglt2-ckd-data-elem-001",
        "q-sglt2-ckd-outcome-eval-001",
    ]
)

# Keyword sets for text-based question routing (order matters — most specific first)
_KEYWORD_ROUTES: list[tuple[tuple[str, ...], tuple[str, ...], str]] = [
    # (required_any, required_all_of_another_set, question_id)
    # data elements question
    (("sglt2",), ("data element",), "q-sglt2-ckd-data-elem-001"),
    (("sglt2",), ("data readiness",), "q-sglt2-ckd-data-elem-001"),
    # outcome evaluation question
    (("sglt2",), ("outcome", "follow"), "q-sglt2-ckd-outcome-eval-001"),
    (("sglt2",), ("outcome", "evaluate"), "q-sglt2-ckd-outcome-eval-001"),
    # cohort definition / general sglt2 ckd question (least specific — matches last)
    (("sglt2",), ("ckd",), "q-sglt2-ckd-t2dm-001"),
    (("sglt2",), ("kidney",), "q-sglt2-ckd-t2dm-001"),
    (("sglt2",), ("chronic kidney",), "q-sglt2-ckd-t2dm-001"),
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DemoQuestionParser(BaseQuestionParser):
    """Returns curated ParseResults for supported demo questions.

    For unsupported questions, returns a controlled draft with clear
    [DEMO MODE] labels rather than generating a fabricated PICO.
    """

    def __init__(self, fixture_dir: Path) -> None:
        self._fixture_dir = Path(fixture_dir)

    @property
    def parser_name(self) -> str:
        return "DemoQuestionParser"

    @property
    def is_demo_mode(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, text: str, question_id: str | None = None) -> ParseResult:
        run_id = str(uuid.uuid4())
        resolved_id = self._resolve_id(text, question_id)
        warnings: list[str] = []

        if resolved_id:
            question = self._load_fixture(resolved_id)
            is_supported = True
        else:
            question = self._build_unsupported_question(text)
            is_supported = False
            warnings.append(
                "[DEMO MODE] Question did not match any curated demo question. "
                "PICO fields are placeholders only — not a clinical assessment."
            )

        provenance = ParseProvenance(  # type: ignore[call-arg]  # pydantic Field defaults opaque via __future__ annotations
            parser_name=self.parser_name,
            is_demo_mode=True,
            model_id=None,
            warnings=warnings,
        )

        return ParseResult(
            run_id=run_id,
            question=question,
            provenance=provenance,
            is_supported_question=is_supported,
            curated_question_id=resolved_id,
            warnings=warnings,
        )

    def supported_question_ids(self) -> list[str]:
        return sorted(_SUPPORTED_IDS)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_id(self, text: str, question_id: str | None) -> str | None:
        if question_id and question_id in _SUPPORTED_IDS:
            return question_id
        normalized = text.lower()
        for required_any, required_all, qid in _KEYWORD_ROUTES:
            if any(k in normalized for k in required_any) and all(
                k in normalized for k in required_all
            ):
                return qid
        return None

    def _load_fixture(self, question_id: str) -> ClinicalQuestion:
        fixture_map: dict[str, str] = {
            "q-sglt2-ckd-t2dm-001": "questions/sglt2_ckd_t2dm.json",
            "q-sglt2-ckd-data-elem-001": "questions/sglt2_ckd_data_elements.json",
            "q-sglt2-ckd-outcome-eval-001": "questions/sglt2_ckd_outcome_eval.json",
        }
        path = self._fixture_dir / fixture_map[question_id]
        data = json.loads(path.read_text(encoding="utf-8"))
        return ClinicalQuestion.model_validate(data)

    def _build_unsupported_question(self, text: str) -> ClinicalQuestion:
        """Return a clearly-labelled draft question for out-of-scope text."""
        return ClinicalQuestion(
            id=f"q-unsupported-{uuid.uuid4().hex[:8]}",
            raw_question=text,
            pico=PICOFramework(  # type: ignore[call-arg]  # optional fields have defaults; mypy false positive
                population="[DEMO MODE] Population not extracted — question is outside the curated demo scope.",
                intervention="[DEMO MODE] Intervention not extracted.",
                comparator=None,
                outcomes=["[DEMO MODE] Outcomes not extracted — question outside demo scope."],
                timeframe=None,
                study_intent="[DEMO MODE] Study intent not determined.",
            ),
            ambiguity_flags=[
                AmbiguityFlag(
                    field="raw_question",
                    description=(
                        "This question does not match any of the three curated demo questions "
                        "(SGLT2 cohort definition, data elements, outcome evaluation). "
                        "PICO extraction is not available for arbitrary questions in demo mode."
                    ),
                    suggested_clarification=(
                        "Please select one of the three curated questions from the Question Builder "
                        "dropdown, or enter a question about SGLT2 inhibitors in type 2 diabetes "
                        "and chronic kidney disease."
                    ),
                    severity="high",
                )
            ],
            clarifying_questions=[
                "Is this question about SGLT2 inhibitors in type 2 diabetes and chronic kidney disease?",
                "If so, which aspect are you studying: cohort definition, data elements, or outcome evaluation?",
            ],
            status="draft",
            source="user_input",
        )
