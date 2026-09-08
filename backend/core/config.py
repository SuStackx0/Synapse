from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "synapse123"

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    database_url: str = "sqlite+aiosqlite:///./synapse.db"

    repos_base_path: str = "/repos"
    embed_model: str = "all-MiniLM-L6-v2"

    class Config:
        env_file = ".env"


settings = Settings()
