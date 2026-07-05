from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    auth_mode: str = Field(default="fake", alias="AUTH_MODE")
    confidence_threshold_primary: float = Field(default=0.65, alias="CONFIDENCE_THRESHOLD_PRIMARY")
    confidence_threshold_post_clarification: float = Field(
        default=0.50, alias="CONFIDENCE_THRESHOLD_POST_CLARIFICATION"
    )
    session_ttl_seconds: int = Field(default=14_400, alias="SESSION_TTL_SECONDS")
    token_budget: int = Field(default=2_500, alias="TOKEN_BUDGET")
    clarification_timeout_seconds: int = Field(default=30, alias="CLARIFICATION_TIMEOUT_SECONDS")
    session_store: str = Field(default="memory", alias="SESSION_STORE")
    upstash_redis_url: str | None = Field(default=None, alias="UPSTASH_REDIS_URL")
    supabase_database_url: str | None = Field(default=None, alias="SUPABASE_DATABASE_URL")
    stt_provider: str = Field(default="fake", alias="STT_PROVIDER")
    deepgram_api_key: str | None = Field(default=None, alias="DEEPGRAM_API_KEY")
    clerk_issuer: str | None = Field(default=None, alias="CLERK_ISSUER")
    clerk_jwks_url: str | None = Field(default=None, alias="CLERK_JWKS_URL")
    clerk_audience: str | None = Field(default=None, alias="CLERK_AUDIENCE")
    clerk_user_id_claim: str = Field(default="vox_user_id", alias="CLERK_USER_ID_CLAIM")
    clerk_tenant_id_claim: str = Field(default="vox_tenant_id", alias="CLERK_TENANT_ID_CLAIM")
    clerk_role_claim: str = Field(default="role", alias="CLERK_ROLE_CLAIM")
    clerk_email_claim: str = Field(default="email", alias="CLERK_EMAIL_CLAIM")
    clerk_snowflake_role_claim: str = Field(
        default="snowflake_role",
        alias="CLERK_SNOWFLAKE_ROLE_CLAIM",
    )
    backend_cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="BACKEND_CORS_ORIGINS",
    )
    canonical_sql_model: str = "claude-sonnet-4-20250514"

    @field_validator("auth_mode")
    @classmethod
    def validate_auth_mode(cls, value: str) -> str:
        allowed = {"fake", "clerk"}
        if value not in allowed:
            raise ValueError(f"AUTH_MODE must be one of {sorted(allowed)}")
        return value

    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, value: str) -> str:
        allowed = {"development", "test", "staging", "production"}
        if value not in allowed:
            raise ValueError(f"APP_ENV must be one of {sorted(allowed)}")
        return value

    @field_validator("session_store")
    @classmethod
    def validate_session_store(cls, value: str) -> str:
        allowed = {"memory", "redis"}
        if value not in allowed:
            raise ValueError(f"SESSION_STORE must be one of {sorted(allowed)}")
        return value

    @field_validator("stt_provider")
    @classmethod
    def validate_stt_provider(cls, value: str) -> str:
        allowed = {"fake", "deepgram"}
        if value not in allowed:
            raise ValueError(f"STT_PROVIDER must be one of {sorted(allowed)}")
        return value

    @field_validator("clerk_issuer", "clerk_jwks_url", "clerk_audience", mode="before")
    @classmethod
    def empty_optional_clerk_value_is_unset(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("deepgram_api_key", mode="before")
    @classmethod
    def empty_deepgram_key_is_unset(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    def validate_startup(self) -> None:
        if self.app_env in {"staging", "production"} and self.auth_mode == "fake":
            raise RuntimeError("AUTH_MODE=fake is only allowed in development or test.")
        if self.auth_mode == "clerk" and (not self.clerk_issuer or not self.clerk_jwks_url):
            raise RuntimeError("CLERK_ISSUER and CLERK_JWKS_URL are required when AUTH_MODE=clerk.")
        if (
            self.auth_mode == "clerk"
            and self.app_env in {"staging", "production"}
            and (
                not self.clerk_issuer.startswith("https://")
                or not self.clerk_jwks_url.startswith("https://")
            )
        ):
            raise RuntimeError("CLERK_ISSUER and CLERK_JWKS_URL must use https://.")
        if self.session_store == "redis" and not self.upstash_redis_url:
            raise RuntimeError("UPSTASH_REDIS_URL is required when SESSION_STORE=redis.")
        if (
            self.session_store == "redis"
            and self.upstash_redis_url
            and self.app_env in {"staging", "production"}
            and not self.upstash_redis_url.startswith("rediss://")
        ):
            raise RuntimeError("UPSTASH_REDIS_URL must use rediss:// in staging/production.")
        if self.stt_provider == "deepgram" and not self.deepgram_api_key:
            raise RuntimeError("DEEPGRAM_API_KEY is required when STT_PROVIDER=deepgram.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
