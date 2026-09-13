# Synapse — Documentation

Synapse is a codebase-intelligence tool: connect a repository (or start one from
nothing) and get graph-grounded answers, debugging, code review, and safe
autonomous edits. This folder documents how it actually works, for anyone
picking up the codebase.

## Start here

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — the big picture: what each piece
  (Next.js, FastAPI, Neo4j, Qdrant, SQLite) is for, and how a request flows
  through the system end to end.
- **[BACKEND.md](./BACKEND.md)** — the LangGraph agent harness in detail: the
  read path (retrieval), the write path (plan → code → apply), the autonomous
  "build from scratch" loop, and the specific reliability fixes that have
  landed in it.
- **[INGESTION.md](./INGESTION.md)** — how a repository on disk becomes a
  Neo4j call graph and a Qdrant vector index, and the SKL context format the
  LLM actually reads.
- **[FRONTEND.md](./FRONTEND.md)** — the Next.js app: page structure, the chat
  UI, the design system.
- **[DEVELOPMENT.md](./DEVELOPMENT.md)** — running the stack locally, the test
  suite, and known rough edges worth knowing about before you touch things.

## One-paragraph summary

A repo is indexed once (or scaffolded from a text description) into two
stores: Neo4j holds the *structure* (files, functions, classes, call edges,
imports) and Qdrant holds *embeddings* used only to resolve which symbols are
relevant to a query — it never returns raw text, only IDs that get resolved
back through Neo4j. Every chat message is classified as a read (ask/debug/
review) or write (implement) request; read requests retrieve a compact,
graph-derived context and answer directly, write requests go through a
plan → generate → validate → apply pipeline that writes real files to disk
through a path-traversal-safe, syntax-checked write tool. Nothing runs the
code it writes — see BACKEND.md's "Known gaps" section for what that implies
and what's been done to reduce the blast radius of that gap.
