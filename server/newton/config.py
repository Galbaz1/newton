"""Environment configuration for local services and private application data."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read documented NEWTON_ variables without exposing provider credentials."""

    model_config = SettingsConfigDict(env_prefix="NEWTON_", env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://newton@127.0.0.1:15432/newton"
    data_dir: Path = Path(".runtime/data")
    cookie_secure: bool = False
    weaviate_host: str = "127.0.0.1"
    weaviate_http_port: int = 18080
    weaviate_grpc_port: int = 15051
    weaviate_api_key: str = ""
    budget_path: Path = Path(".runtime/budget.json")
    visual_encoder_url: str = ""


settings = Settings()
