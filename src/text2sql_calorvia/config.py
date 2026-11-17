from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings of phase B, read from the same .env file as phase A.

    Only the read-only account's password is needed: the admin passwords in .env are for the restore
    (docker compose) and the application never reads them.
    """
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agent_ro_password: str
    sources_host: str = "localhost"
    erp_port: int = 14330      # the course's compose file publishes SQL Server on 14330, not 1433
    compta_port: int = 5433
    paie_port: int = 5434
    connect_timeout_s: int = 5

    # The course material (git-ignored): the presentation holds the 12 starter questions and their answers
    sources_path: Path = Path("enonces/calorvia_t2sql/sources_calorvia")


settings = Settings()
