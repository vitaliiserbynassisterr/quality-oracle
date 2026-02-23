"""Quality Oracle configuration via environment variables."""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8002
    debug: bool = False
    log_level: str = "info"

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "assisterr"

    # Redis
    redis_url: str = "redis://localhost:6379/1"

    # LLM Judge - Primary (DeepSeek V3.2)
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # LLM Judge - Fallback (Groq)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # LLM Judge - Question Generation
    anthropic_api_key: str = ""

    # API Keys
    api_key_salt: str = "change-this-to-random-string"

    # JWT Attestation Signing (Ed25519)
    jwt_private_key_path: str = ""
    jwt_issuer: str = "did:web:quality-oracle.assisterr.ai"
    attestation_validity_days: int = 30

    # CORS
    cors_origins: List[str] = ["http://localhost:3000"]

    # Evaluation defaults
    default_eval_level: int = 2
    max_concurrent_evals: int = 5
    eval_timeout_seconds: int = 120
    evaluation_version: str = "v1.0"

    # Rate limiting (evaluations per month)
    rate_limit_free: int = 10
    rate_limit_developer: int = 100
    rate_limit_team: int = 500

    # Webhook
    webhook_timeout_seconds: int = 10
    webhook_max_retries: int = 3

    # Base URL for constructing links in responses
    base_url: str = "http://localhost:8002"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
