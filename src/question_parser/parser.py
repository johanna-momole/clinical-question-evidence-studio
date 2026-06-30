"""Abstract base class for clinical question parsers."""

from abc import ABC, abstractmethod

from src.schemas.parsing import ParseResult


class BaseQuestionParser(ABC):
    """Contract that all question parsers must satisfy.

    Implementations include DemoQuestionParser (deterministic, no API key required)
    and live LLM parsers (AnthropicQuestionParser, OpenAIQuestionParser — planned).
    """

    @abstractmethod
    def parse(self, text: str, question_id: str | None = None) -> ParseResult:
        """Parse a clinical question into a structured ParseResult.

        Args:
            text: Raw question text as entered by the user.
            question_id: Optional curated question ID. When provided and recognised,
                         the corresponding curated fixture is returned directly.

        Returns:
            ParseResult with question, provenance, and support flag.
        """
        ...

    @property
    @abstractmethod
    def parser_name(self) -> str:
        """Human-readable identifier for this parser implementation."""
        ...

    @property
    @abstractmethod
    def is_demo_mode(self) -> bool:
        """True when the parser operates without a live LLM API call."""
        ...
