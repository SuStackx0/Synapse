# Synapse

AI-powered codebase intelligence. Connect a repo, ask questions, visualize your call graph, debug faster.

## Features

- **Repo Brain** — interactive Neo4j-backed call graph explorer
- **AI Agents** — QA, debugging, and code review powered by any LLM
- **Vibe Check** — automated code health dashboard
- **Commit History Chat** — talk to your git history
- **Model Benchmarker** — compare two LLM providers side by side
- **Bring Your Own Model** — plug in OpenAI, Anthropic, vLLM, sglang, or Ollama

## Quick Start

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000)

## Stack

- **Frontend**: Next.js 14, TailwindCSS, D3.js
- **Backend**: FastAPI, LangGraph
- **Graph DB**: Neo4j
- **Vector DB**: Qdrant
- **Parsing**: Python AST + Tree-sitter
