"""FastAPI routes for computable phenotype building (Phase 2)."""

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from src.phenotypes.service import PhenotypeService, get_phenotype_service
from src.question_parser.service import QuestionService, get_question_service
from src.schemas.parsing import PhenotypeResult
from src.schemas.phenotype import PhenotypeDefinition

router = APIRouter(prefix="/phenotypes", tags=["phenotypes"])


class BuildPhenotypeRequest(BaseModel):
    question_id: str


@router.post(
    "/build",
    response_model=PhenotypeResult,
    summary="Build a phenotype for an approved question",
    description=(
        "Resolves the phenotype for a curated question ID. "
        "The question must have status='approved' in the fixture (all curated questions do). "
        "Returns is_available=false for question IDs outside the demo catalog."
    ),
)
def build_phenotype(
    body: Annotated[BuildPhenotypeRequest, Body(...)],
) -> PhenotypeResult:
    q_service: QuestionService = get_question_service()
    question = q_service.get_curated_question(body.question_id)
    if question is None:
        raise HTTPException(
            status_code=404,
            detail=f"Question '{body.question_id}' not found in curated demo catalog.",
        )
    p_service: PhenotypeService = get_phenotype_service()
    return p_service.build_from_question(question)


@router.get(
    "/{phenotype_id}",
    response_model=PhenotypeDefinition,
    summary="Retrieve a phenotype fixture directly by ID",
)
def get_phenotype(phenotype_id: str) -> PhenotypeDefinition:
    service: PhenotypeService = get_phenotype_service()
    result = service._repo.load(phenotype_id)  # noqa: SLF001
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Phenotype '{phenotype_id}' not found.",
        )
    return result
