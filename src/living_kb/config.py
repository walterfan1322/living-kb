from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LKB_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = Field(
        default=f"sqlite:///{(PROJECT_ROOT / 'storage' / 'living_kb.db').as_posix()}"
    )
    data_root: Path = PROJECT_ROOT / "storage"
    stale_days: int = 30
    llm_provider: str = "none"
    openai_model: str = "gpt-5-mini"
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    minimax_model: str = "MiniMax-M2.7"
    minimax_api_key: str | None = Field(default=None, alias="MINIMAX_API_KEY")
    minimax_base_url: str = "https://api.minimax.io/v1"
    scheduler_enabled: bool = True
    scheduler_poll_seconds: int = 5
    health_check_interval_seconds: int = 300
    embedding_provider: str = "auto"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    retrieval_lexical_weight: float = 0.45
    retrieval_vector_weight: float = 0.55

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def raw_dir(self) -> Path:
        return self.data_root / "raw"

    @property
    def pages_dir(self) -> Path:
        return self.data_root / "pages"

    @property
    def revisions_dir(self) -> Path:
        return self.pages_dir / "history"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_root / "artifacts"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_root.mkdir(parents=True, exist_ok=True)
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.pages_dir.mkdir(parents=True, exist_ok=True)
    settings.revisions_dir.mkdir(parents=True, exist_ok=True)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    return settings
