from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Machine settings, read from the .env file (or from environment variables)."""
    # extra="ignore": .env also holds DB_USER, DB_PASSWORD and DB_NAME, which only docker-compose reads
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_url: str
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str
    llm_url: str = "http://localhost:8000/v1"
    embeddings_url: str = "http://localhost:8001/v1"
    rerank_url: str = "http://localhost:8002/rerank"
    vlm_url: str = "http://localhost:8003/v1"    # the VLM only runs during the ETL (step 7)...
    vlm_model: str = "qwen3.5-9b"                # served name of the VLM (llama-server -a)
    judge_url: str = "http://localhost:8003/v1"  # ...so the judge can reuse its port afterwards
    judge_model: str = "gemma4-26b-a4b"          # served name (llama-server -a): not the generator's family

    # Relative to the repo root: scripts are run from there (uv run python scripts/...)
    corpus_path: Path = Path("data/calorvia")                 # symlink to the corpus in enonces/
    eval_path: Path = Path("data/calorvia_eval.json")         # symlink to the eval set in enonces/
    conversions_path: Path = Path("data/conversions")         # Docling output cache (step 4)
    vision_path: Path = Path("data/vision")                   # VLM transcription cache (step 7)
    translations_path: Path = Path("data/translations")       # French versions of nl/en chunks (step 30g)
    reports_path: Path = Path("data/reports")
    models_path: Path  # holds embedder/{name}, reranker/{name} and docling/
    docling_device: str = "cuda"  # where Docling runs its PDF layout and table models: cuda or cpu
    # The configuration the chat, the agent's endpoint and the access proof use. Step 9's final evaluation was
    # status_filter; step 30 added translation on demand for the reranker (runs 148, 150, 152) and Markdown tables
    # (runs 154, 156, judged against french_chunks_tables, run 160)
    final_config: Path = Path("experiments/markdown_tables.toml")

    @property
    def docling_models_path(self):
        return self.models_path / "docling"


settings = Settings()
