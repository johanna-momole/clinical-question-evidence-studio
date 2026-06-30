"""Shared question service — used by both FastAPI routes and Streamlit pages."""

import json
from functools import lru_cache
from pathlib import Path

from src.question_parser.demo_parser import DemoQuestionParser
from src.question_parser.parser import BaseQuestionParser
from src.schemas.parsing import ParseResult
from src.schemas.question import ClinicalQuestion


class QuestionService:
    """Facade over the question parser with fixture loading and convenience helpers."""

    def __init__(self, parser: BaseQuestionParser, fixture_dir: Path) -> None:
        self._parser = parser
        self._fixture_dir = fixture_dir

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def parse(self, text: str, question_id: str | None = None) -> ParseResult:
        """Parse a clinical question. Delegates to the injected parser."""
        return self._parser.parse(text, question_id)

    def get_curated_questions(self) -> list[ClinicalQuestion]:
        """Return all three curated demo questions in canonical order."""
        ids = [
            "q-sglt2-ckd-t2dm-001",
            "q-sglt2-ckd-data-elem-001",
            "q-sglt2-ckd-outcome-eval-001",
        ]
        questions = []
        for qid in ids:
            q = self.get_curated_question(qid)
            if q is not None:
                questions.append(q)
        return questions

    def get_curated_question(self, question_id: str) -> ClinicalQuestion | None:
        """Load a single curated question by ID, or None if not found."""
        fixture_map: dict[str, str] = {
            "q-sglt2-ckd-t2dm-001": "questions/sglt2_ckd_t2dm.json",
            "q-sglt2-ckd-data-elem-001": "questions/sglt2_ckd_data_elements.json",
            "q-sglt2-ckd-outcome-eval-001": "questions/sglt2_ckd_outcome_eval.json",
        }
        rel = fixture_map.get(question_id)
        if rel is None:
            return None
        path = self._fixture_dir / rel
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ClinicalQuestion.model_validate(data)

    @property
    def is_demo_mode(self) -> bool:
        return self._parser.is_demo_mode


@lru_cache(maxsize=1)
def get_question_service() -> QuestionService:
    """Singleton factory — call from FastAPI dependencies and Streamlit pages."""
    from src.config.settings import get_settings

    settings = get_settings()
    fixture_dir = Path(settings.fixtures_dir)
    parser = DemoQuestionParser(fixture_dir)
    return QuestionService(parser=parser, fixture_dir=fixture_dir)
