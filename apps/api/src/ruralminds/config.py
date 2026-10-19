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
    # Shown to the admin; the GGUF file name may be an Ollama blob hash.
    chat_model_label: str = ""
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
    max_queue: int = 30  # hard cap on phones waiting in line
    # Turn a question away when its predicted wait is longer (the estimate comes from the
    # measured gap between finished answers; bench 19 Oct: ~3 answers/min on the demo laptop).
    max_wait_s: int = 180
    queue_update_s: float = 3.0  # how often a waiting phone gets its live place in line
    one_question_ttl_s: int = 300  # backstop for the one-question-per-phone guard
    max_question_chars: int = 500
    history_turns: int = 2

    # Accounts and sessions (see auth.py)
    student_idle_minutes: int = 30  # shared phones: sign out soon after the student stops
    teacher_idle_minutes: int = 480
    admin_idle_minutes: int = 60
    session_max_hours: int = 12
    login_max_failures: int = 5
    login_window_minutes: int = 10

    # Teacher uploads (see uploads.py). Our largest textbook PDF is 32 MB / 159 pages.
    books_dir: Path = Path("data/books")
    uploads_dir: Path = Path("data/uploads")
    page_cache_dir: Path = Path("data/pages")
    page_image_dpi: int = 110  # readable on a phone when zoomed; ~1 MB raw per page
    frontend_dir: Path = Path("frontend/build")
    max_upload_mb: int = 60
    max_pages: int = 400
    min_free_disk_gb: float = 2.0
    stale_upload_hours: int = 6
    max_ingest_attempts: int = 3

    # Retention (janitor): the inbox and the usage log never grow without bound
    unanswered_keep_days: int = 30
    unanswered_keep_per_class: int = 300
    answer_log_keep_days: int = 180


settings = Settings()
