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

    # Execution limits of the MCP server (step 11)
    max_rows: int = 200            # rows returned to the model; more = truncated flag
    query_timeout_s: int = 20      # client side, on every engine (SQL Server has none server side)
    min_group_size: int = 5        # payroll privacy rule (O5): a salary figure covers at least this many people
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 9001           # 9000 is for the agent's OpenAI endpoint, 3000-3003 for auto-ontology

    # The course PostgreSQL (5432): every query of the agent is logged there
    postgres_url: str

    # The course material (git-ignored): the presentation holds the 12 starter questions and their answers
    sources_path: Path = Path("enonces/calorvia_t2sql/sources_calorvia")


settings = Settings()
