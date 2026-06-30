"""Application settings loaded from environment variables and .env file."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Clinical Question-Evidence Studio."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "Clinical Question-Evidence Studio"
    app_version: str = "0.1.0"
    app_env: str = Field("development", description="development | staging | production")
    debug: bool = False

    # LLM provider (leave empty for deterministic demo mode)
    llm_provider: str | None = Field(None, description="anthropic | openai | None (demo mode)")
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-6"
    demo_mode: bool = Field(True, description="Force deterministic mode regardless of API keys")

    # FastAPI
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_base_url: str = "http://localhost:8000"

    # Evidence source APIs
    pubmed_api_key: str | None = None
    ncbi_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    clinicaltrials_base_url: str = "https://clinicaltrials.gov/api/v2"
    rxnorm_base_url: str = "https://rxnav.nlm.nih.gov/REST"

    # Storage
    data_dir: str = "data"
    fixtures_dir: str = "data/fixtures"
    cache_dir: str = ".cache"

    # Quality assurance
    max_evidence_age_days: int = Field(1825, description="Flag evidence older than this (5 years)")

    @property
    def is_demo_mode(self) -> bool:
        """True when no live LLM provider is configured or demo_mode is forced."""
        return self.demo_mode or self.llm_provider is None

    @property
    def active_llm_model(self) -> str:
        """Returns 'demo' in demo mode, otherwise the configured model."""
        return "demo" if self.is_demo_mode else self.llm_model


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()  # type: ignore[call-arg]  # pydantic-settings resolves defaults from env
