from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog

from core.database import init_db
from ingestion.graph_builder import graph_builder
from ingestion.embedder import embedder
from routers import repos, agents, graph, health, settings, sessions

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting_up")
    await init_db()
    await graph_builder.connect()
    await embedder.init()
    yield
    await graph_builder.close()
    logger.info("shut_down")


app = FastAPI(
    title="Synapse API",
    description="AI-powered codebase intelligence",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(repos.router)
app.include_router(agents.router)
app.include_router(graph.router)
app.include_router(health.router)
app.include_router(settings.router)
app.include_router(sessions.router)


@app.get("/")
async def root():
    return {"service": "Synapse", "status": "running", "version": "1.0.0"}


@app.get("/ping")
async def ping():
    return {"pong": True}
