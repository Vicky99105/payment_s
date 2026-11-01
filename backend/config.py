from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "production"
    """Fail-safe default: docs off. Local development opts in with ENV=development."""
    database_url: str = ""
    webhook_signing_secret: str = ""
    api_keys: str = "{}"
    """JSON: {"<sha256 hex of key>": {"name": "...", "scopes": ["transactions:read"]}}"""
    signature_tolerance_seconds: int = 300
    max_body_bytes: int = 16_384
    queue_topic: str = "transactions"
    settlement_delay_seconds: float = 30.0
    settlement_fault_injection: bool = False
    """When true, ids starting with `faultinject_` fail their first settlement attempt. Live verification only."""
