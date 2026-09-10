from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    # DEV-ONLY fallback so `docker compose up` works out of the box.
    # PRODUCTION MUST override NEO4J_PASSWORD via .env or a secrets manager.
    neo4j_password: str = "synapse123"

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    database_url: str = "sqlite+aiosqlite:///./synapse.db"

    repos_base_path: str = "/repos"
    embed_model: str = "all-MiniLM-L6-v2"

    # Comma-separated list of browser origins allowed to call the API.
    # Never set this to "*" while credentialed requests are enabled.
    cors_allowed_origins: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"


settings = Settings()
