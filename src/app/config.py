"""Runtime configuration, loaded from environment variables (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_base_url: str = os.getenv(
        "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    llm_model: str = os.getenv("LLM_MODEL", "qwen-plus")
    vlm_model: str = os.getenv("VLM_MODEL", "qwen3-vl-plus")
    llm_temperature: float = _float("LLM_TEMPERATURE", 0.0)
    llm_max_retries: int = _int("LLM_MAX_RETRIES", 3)
    llm_timeout_seconds: int = _int("LLM_TIMEOUT_SECONDS", 120)
    llm_input_price_per_1k: float = _float("LLM_INPUT_PRICE_PER_1K", 0.0008)
    llm_output_price_per_1k: float = _float("LLM_OUTPUT_PRICE_PER_1K", 0.002)
    # Reference qwen3-vl-plus list price (CNY / 1K tokens), including image tokens.
    vlm_input_price_per_1k: float = _float("VLM_INPUT_PRICE_PER_1K", 0.0012)
    vlm_output_price_per_1k: float = _float("VLM_OUTPUT_PRICE_PER_1K", 0.012)
    vlm_max_image_side: int = _int("VLM_MAX_IMAGE_SIDE", 1600)

    mysql_host: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port: int = _int("MYSQL_PORT", 3308)
    mysql_database: str = os.getenv("MYSQL_DATABASE", "docaudit")
    mysql_user: str = os.getenv("MYSQL_USER", "docaudit")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "docaudit_pwd")
    auth_required: bool = os.getenv("AUTH_REQUIRED", "false").lower() in {"1", "true", "yes", "on"}
    api_keys: str = os.getenv("API_KEYS", "")

    pdf_render_dpi: int = _int("PDF_RENDER_DPI", 200)
    auto_accept_confidence: float = _float("AUTO_ACCEPT_CONFIDENCE", 0.85)
    duplicate_vector_threshold: float = _float("DUPLICATE_VECTOR_THRESHOLD", 0.92)

    mineru_output_dir: Path = PROJECT_ROOT / os.getenv(
        "MINERU_OUTPUT_DIR", "data/processed/mineru"
    )

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )


settings = Settings()
