from sqlalchemy import String, DateTime, JSON, Text, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column
from core.database import Base
from datetime import datetime


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)  # local | github
    language: Mapped[str] = mapped_column(String, default="mixed")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    provider_type: Mapped[str] = mapped_column(String)  # openai | anthropic | vllm | sglang | ollama
    base_url: Mapped[str] = mapped_column(String)
    api_key: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    repo_id: Mapped[str] = mapped_column(String)
    query: Mapped[str] = mapped_column(Text)
    provider_a_id: Mapped[str] = mapped_column(String)
    provider_b_id: Mapped[str] = mapped_column(String)
    response_a: Mapped[str] = mapped_column(Text)
    response_b: Mapped[str] = mapped_column(Text)
    latency_a: Mapped[float] = mapped_column(Float)
    latency_b: Mapped[float] = mapped_column(Float)
    winner: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
