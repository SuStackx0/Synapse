# Synapse

AI-powered codebase intelligence. Connect a repo — or start one from nothing — and get graph-grounded answers, debugging, code review, and safe autonomous edits, not just a grep-and-hope chatbot.

![Homepage](docs/screenshots/homepage.jpg)

## What makes it different

Most "AI codebase" tools embed text chunks and hope similarity search finds the right ones. Synapse splits the job in two: Neo4j holds the actual call graph — files, functions, signatures, callers, callees, entrypoints — and Qdrant is used only to resolve *which* symbols a query is about, returning IDs, never text. Every prompt is built from the graph, not from a chunk that happened to score well. Ask it to check whether something is "wired in properly" and it reads the real files the graph resolved, then answers with file:line citations instead of guessing.

![Ask AI — graph-grounded analysis](docs/screenshots/ask-ai.jpg)

## Features

- **Ask AI** — a single chat box for QA, debugging, code review, and implementation. It classifies read vs. write intent itself, asks a clarifying question instead of guessing when a request is genuinely ambiguous, and streams progress step-by-step as it plans, writes, and applies file changes.
- **Start from nothing** — no local repo or GitHub URL required. Describe what you want built and Synapse scaffolds and iteratively builds a real, runnable project on its own, with the same task-by-task progress view as a normal chat turn.

  ![Start a project from nothing](docs/screenshots/new-project.jpg)
- **Repo Brain** — interactive Neo4j-backed call graph explorer.

  ![Repo Brain — call graph explorer](docs/screenshots/repo-brain.jpg)
- **Vibe Check** — a code health dashboard backed by real graph queries (true call-graph fan-in for dead-code detection, not a string-matching heuristic).

  ![Vibe Check — codebase health](docs/screenshots/vibe-check.jpg)
- **Commit History Chat** — talk to your git history.
- **Model Benchmarker** — compare two LLM providers side by side on the same query.
- **Bring Your Own Model** — plug in OpenAI, Anthropic, vLLM, SGLang, or Ollama. No vendor is hardcoded and there's no default endpoint; you configure and activate a provider, and credentials are encrypted at rest.
- **Session persistence** — every conversation is saved and resumable; switching or starting a new chat never loses history.
- **In-app file editor** — open any file the agent touched (or any file at all) in a side-by-side console and edit it directly.

## Quick Start

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000), then add and activate an LLM provider under **Settings** — there's no default model configured, so this is the one required step before your first query.

For local dev conveniences (e.g. mounting your own repos), copy settings into a
gitignored `docker-compose.override.yml` rather than editing the committed compose
file.

## Testing

```bash
cd backend && pip install -r requirements.txt && pytest tests/ -v
```

CI runs the same suite on every push/PR via `.github/workflows/backend-tests.yml`.

## Stack

- **Frontend**: Next.js 14, TailwindCSS, D3.js, CodeMirror
- **Backend**: FastAPI, LangGraph
- **Graph DB**: Neo4j
- **Vector DB**: Qdrant
- **Parsing**: Python AST (full call-graph resolution); lightweight regex-based parsing for JS/TS
