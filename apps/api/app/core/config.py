"""Central configuration.

Every environment variable the system reads is declared here. Business logic
imports `settings`; it never touches `os.environ`, so credentials have exactly
one entry point and can be redacted in exactly one place.
"""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Runtime configuration, loaded from `.env` then the environment."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- TigerGraph ------------------------------------------------------
    tg_host: str = Field(default="", alias="TG_HOST")
    tg_graphname: str = Field(default="FraudLens", alias="TG_GRAPHNAME")
    tg_api_token: SecretStr = Field(default=SecretStr(""), alias="TG_API_TOKEN")
    tg_username: str = Field(default="tigergraph", alias="TG_USERNAME")
    tg_password: SecretStr = Field(default=SecretStr(""), alias="TG_PASSWORD")
    tg_tgcloud: bool = Field(default=True, alias="TG_TGCLOUD")
    tg_mcp_transport: str = Field(default="stdio", alias="TG_MCP_TRANSPORT")
    tg_log_tool_calls: bool = Field(default=True, alias="TG_LOG_TOOL_CALLS")
    tg_timeout_seconds: float = Field(default=30.0, alias="TG_TIMEOUT_SECONDS")

    # --- LLM -------------------------------------------------------------
    llm_provider: str = Field(default="gemini", alias="LLM_PROVIDER")
    llm_model: str = Field(default="gemini-3.5-flash", alias="LLM_MODEL")
    llm_api_key: SecretStr = Field(default=SecretStr(""), alias="LLM_API_KEY")
    llm_temperature: float = Field(default=0.0, alias="LLM_TEMPERATURE")
    embedding_model: str = Field(default="gemini-embedding-001", alias="EMBEDDING_MODEL")

    # --- GraphRAG --------------------------------------------------------
    graphrag_chunk_size: int = Field(default=2048, alias="GRAPHRAG_CHUNK_SIZE")
    graphrag_chunk_overlap: int = Field(default=256, alias="GRAPHRAG_CHUNK_OVERLAP")
    graphrag_top_k: int = Field(default=5, alias="GRAPHRAG_TOP_K")
    graphrag_num_hops: int = Field(default=2, alias="GRAPHRAG_NUM_HOPS")

    # --- Application -----------------------------------------------------
    app_env: str = Field(default="development", alias="APP_ENV")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    web_origin: str = Field(default="http://localhost:5173", alias="WEB_ORIGIN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Reproducibility --------------------------------------------------
    dataset_version: str = Field(default="hhgoa-ieee-2026-09-18", alias="DATASET_VERSION")
    policy_version: str = Field(default="1.0", alias="POLICY_VERSION")
    prompt_version: str = Field(default="1.0", alias="PROMPT_VERSION")
    simulator_seed: int = Field(default=20260923, alias="SIMULATOR_SEED")

    # --- Safety -----------------------------------------------------------
    simulate_external_actions: bool = Field(default=True, alias="SIMULATE_EXTERNAL_ACTIONS")
    # The kill switch for the approval boundary. Flipping this to true would
    # let the agent execute L1/L2 actions without a human, so it stays false
    # and the API refuses to start in production if it is set.
    allow_non_auto_action_execution: bool = Field(
        default=False, alias="ALLOW_NON_AUTO_ACTION_EXECUTION"
    )
    benchmark_memory_mode: str = Field(default="chronological", alias="BENCHMARK_MEMORY_MODE")

    # --- Paths ------------------------------------------------------------
    repo_root: Path = REPO_ROOT

    @field_validator("llm_provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        allowed = {"gemini", "openai", "anthropic", "none"}
        if value.lower() not in allowed:
            raise ValueError(f"LLM_PROVIDER must be one of {sorted(allowed)}, got {value!r}")
        return value.lower()

    # --- Derived paths ----------------------------------------------------
    @property
    def raw_data_dir(self) -> Path:
        return self.repo_root / "data" / "raw"

    @property
    def processed_data_dir(self) -> Path:
        return self.repo_root / "data" / "processed"

    @property
    def fixtures_dir(self) -> Path:
        return self.repo_root / "data" / "fixtures"

    @property
    def outputs_cases_dir(self) -> Path:
        return self.repo_root / "outputs" / "cases"

    @property
    def traces_dir(self) -> Path:
        return self.repo_root / "outputs" / "traces"

    @property
    def knowledge_dir(self) -> Path:
        return self.repo_root / "knowledge"

    @property
    def source_manifest_path(self) -> Path:
        return self.repo_root / "data" / "source-manifest.json"

    # --- Readiness --------------------------------------------------------
    @property
    def tigergraph_configured(self) -> bool:
        """Whether a live graph connection can be attempted."""
        has_credential = bool(self.tg_api_token.get_secret_value()) or bool(
            self.tg_password.get_secret_value()
        )
        return bool(self.tg_host) and has_credential

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key.get_secret_value())

    def redacted(self) -> dict[str, object]:
        """A safe view for logs and the API health endpoint.

        Secrets are reported as booleans. A secret must never reach a log
        line, a trace file, or a prompt.
        """
        return {
            "app_env": self.app_env,
            "tg_host": self.tg_host or "(unset)",
            "tg_graphname": self.tg_graphname,
            "tg_credential_present": self.tigergraph_configured,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_key_present": bool(self.llm_api_key.get_secret_value()),
            "embedding_model": self.embedding_model,
            "dataset_version": self.dataset_version,
            "policy_version": self.policy_version,
            "prompt_version": self.prompt_version,
            "simulate_external_actions": self.simulate_external_actions,
            "allow_non_auto_action_execution": self.allow_non_auto_action_execution,
            "benchmark_memory_mode": self.benchmark_memory_mode,
        }


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance. Use this rather than constructing Settings()."""
    return Settings()


settings = get_settings()
