"""Settings loaded from the environment / .env. Every tunable lives here, not in code.

Paths are relative to the repository root; run commands from there.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RURALMINDS_", extra="ignore")

    env: str = "development"

    # Storage
    db_path: Path = Path("data/ruralminds.db")
    ocr_cache_dir: Path = Path("data/ocr")
    books_file: Path = Path("apps/api/books.toml")

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Local llama-server instances (never internet hosts)
    llm_url: str = "http://127.0.0.1:8080"
    embed_url: str = "http://127.0.0.1:8081"
    embed_dim: int = 1024
    embed_batch_size: int = 16

    # Ingestion
    tesseract_cmd: str = "tesseract"
    ocr_dpi: int = 300
    ocr_workers: int = 4
    # A page whose text layer has less than this share of the expected script goes to OCR.
    min_script_ratio: float = 0.6
    chunk_target_chars: int = 1000
    chunk_max_chars: int = 1600

    # Generation / retrieval
    temperature: float = 0.2
    max_tokens: int = 300
    final_top_k: int = 4
    # Budget for retrieved text, in bge-m3 tokens. 600 keeps time-to-first-word near the 10-15 s
    # target on this laptop (measured 12 Oct); 900 measured 14-23 s.
    max_context_tokens: int = 600
    # Refusal gate, layer 1: refuse before calling the model when no keyword hit exists AND the
    # best cosine similarity is below this. Placeholder: calibrate on the eval dev split.
    refusal_threshold: float = 0.5
    llm_parallel: int = 2  # must match llama-server -np; sizes the answer queue
    max_queue: int = 30
    max_question_chars: int = 500
    history_turns: int = 2
    teacher_pin_hash: str = ""


settings = Settings()
