"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "VisionFlow"
    app_env: str = "development"
    debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    database_url: str = f"sqlite:///{PROJECT_ROOT / 'storage' / 'visionflow.db'}"

    storage_root: Path = PROJECT_ROOT / "storage"
    generated_dir: Path = PROJECT_ROOT / "storage" / "generated"
    diagrams_dir: Path = PROJECT_ROOT / "storage" / "diagrams"
    prompts_dir: Path = PROJECT_ROOT / "storage" / "prompts"
    reports_dir: Path = PROJECT_ROOT / "storage" / "reports"
    traces_dir: Path = PROJECT_ROOT / "storage" / "traces"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_image_model: str = "gpt-image-1"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    llm_provider: str = "mock"
    llm_enabled: bool = True

    image_api_key: str = ""
    # Default mock so clone-and-run works without API keys
    image_provider: str = "mock"

    # offline | openai (optional VLM scoring)
    vision_evaluator_provider: str = "none"
    # none | tesseract (reserved for future OCR)
    ocr_provider: str = "none"

    demo_mode: bool = False
    workflow_debug: bool = False

    min_quality_score: float = 0.6
    max_revision_rounds: int = 2

    def ensure_dirs(self) -> None:
        for path in (
            self.storage_root,
            self.generated_dir,
            self.diagrams_dir,
            self.prompts_dir,
            self.reports_dir,
            self.traces_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
