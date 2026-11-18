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
    max_rows_limit: int = 5000     # a client may ask for more rows (the agent, to reconcile), never past this
    query_timeout_s: int = 20      # client side, on every engine (SQL Server has none server side)
    min_group_size: int = 5        # payroll privacy rule (O5): a salary figure covers at least this many people
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 9001           # 9000 is for the agent's OpenAI endpoint, 3000-3003 for auto-ontology

    # The agent (step 13): LangGraph over the MCP server, served as an OpenAI-compatible endpoint
    llm_url: str = "http://localhost:8000/v1"
    llm_model: str = "openai/qwen3.8-27b"   # the alias the generator is served under (step 12)
    mcp_url: str = "http://127.0.0.1:9001/mcp"
    agent_host: str = "127.0.0.1"
    agent_port: int = 9000
    agent_model_name: str = "calorvia-agent"
    max_tool_calls: int = 24       # per question: past this, the agent must answer with what it has
    max_sql_errors: int = 4        # refused or failed queries per question before it stops correcting
    tool_result_chars: int = 12_000   # what one tool answer may take in the model's context
    agent_fetch_rows: int = 2000      # rows the agent fetches and keeps for reconcile
    rows_to_model: int = 50           # rows of a result the model sees; the rest stays in the agent's state
    context_tokens: int = 26_000      # past this (estimated), the oldest tool answers are shortened (32k context)
    data_until: str = "2026-05-31"    # the sources stop here: "this month", "this year" are read from this date
    # Bonuses (step 15): charts served by the endpoint, conversations and learned memory in PostgreSQL
    agent_public_url: str = "http://localhost:9000"   # how a client reaches the endpoint (chart links)
    charts_dir: Path = Path("data/charts")
    max_memories: int = 30            # memories put in the prompt, newest first
    # Before a real deployment (step 24, D72)
    api_keys: str = ""                # "name:key,name2:key2"; empty = local mode, loopback only
    trusted_gateways: str = ""        # names whose key may say which end user is asking (Open WebUI's header)
    chart_max_age_days: int = 30      # older chart files are deleted when a new chart is drawn
    overlap_max_rows: int = 200_000   # payroll: rows read to compare what two queries cover

    # The course PostgreSQL (5432): every query of the agent is logged there
    postgres_url: str

    # The course material (git-ignored): the presentation holds the 12 starter questions and their answers
    sources_path: Path = Path("enonces/calorvia_t2sql/sources_calorvia")


settings = Settings()
