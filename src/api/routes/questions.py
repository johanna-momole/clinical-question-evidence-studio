"""FastAPI routes for clinical question parsing (Phase 2)."""

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from src.question_parser.service import QuestionService, get_question_service
from src.schemas.parsing import ParseResult
from src.schemas.question import ClinicalQuestion

router = APIRouter(prefix="/questions", tags=["questions"])


class ParseRequest(BaseModel):
    text: str
    question_id: str | None = None


@router.post(
    "/parse",
    response_model=ParseResult,
    summary="Parse a clinical question into PICO structure",
    description=(
        "Accepts free-form clinical question text (and an optional curated question ID). "
        "In demo mode, returns a deterministic ParseResult. "
        "Supported questions include the three curated SGLT2/T2DM/CKD demo questions. "
        "Unsupported questions return is_supported_question=false with a placeholder PICO."
    ),
)
def parse_question(
    body: Annotated[ParseRequest, Body(...)],
) -> ParseResult:
    if not body.text.strip() and not body.question_id:
        raise HTTPException(
            status_code=422,
            detail="Either 'text' or 'question_id' must be provided.",
        )
    service: QuestionService = get_question_service()
    return service.parse(body.text, body.question_id)


@router.get(
    "/curated",
    response_model=list[ClinicalQuestion],
    summary="List all curated demo questions",
)
def list_curated_questions() -> list[ClinicalQuestion]:
    service: QuestionService = get_question_service()
    return service.get_curated_questions()


@router.get(
    "/curated/{question_id}",
    response_model=ClinicalQuestion,
    summary="Get a single curated demo question by ID",
)
def get_curated_question(question_id: str) -> ClinicalQuestion:
    service: QuestionService = get_question_service()
    q = service.get_curated_question(question_id)
    if q is None:
        raise HTTPException(
            status_code=404,
            detail=f"Curated question '{question_id}' not found. "
            "Supported IDs: q-sglt2-ckd-t2dm-001, q-sglt2-ckd-data-elem-001, "
            "q-sglt2-ckd-outcome-eval-001.",
        )
    return q
