# Development

## Running the stack

```bash
docker compose up --build
```

Brings up `neo4j`, `qdrant`, `backend`, `frontend`. Open
[http://localhost:3000](http://localhost:3000). First backend startup loads a
local `SentenceTransformer` embedding model, which takes ~15-20s.

For local-only conveniences (mounting a personal directory, overriding an env
var), use a gitignored `docker-compose.override.yml` rather than editing the
committed `docker-compose.yml` — it's merged automatically by
`docker compose up`.

### Configuration

Backend config is centralized in `backend/core/config.py` (pydantic-settings,
reads env vars). Notable ones: `NEO4J_PASSWORD` (dev-only fallback baked in,
production must override), `CORS_ALLOWED_ORIGINS` (comma-separated; never
set to `*` while `allow_credentials` is on — the backend refuses to combine
those), `SYNAPSE_SECRET_KEY` (encrypts LLM provider API keys at rest via
Fernet in `core/crypto.py`; auto-generates a dev-only key into a gitignored
file if unset — never rely on that in production), `RELOAD` (uvicorn
`--reload`, defaults on for local dev via docker-compose, off by default in
the image itself).

## Tests

```bash
cd backend && pip install -r requirements.txt && pytest tests/ -v
```

Runs in CI on every push/PR via `.github/workflows/backend-tests.yml`. The
suite is unit tests over the harness's pure/near-pure functions — path
safety, the intent classifier, JSON/code-block extraction from LLM output,
role detection, the planner's deterministic path/op corrections (using a
tiny fake-LLM stub, not a real model call) — not integration tests against a
live Neo4j/Qdrant/LLM, so a green suite doesn't by itself prove an end-to-end
chat turn works. The standing practice in this repo has been to also verify
real changes live through the actual UI (Chrome), not just curl, since curl
can't exercise the SSE streaming or the frontend's rendering of it.

## Docker Desktop resource notes

During development on this repo, Docker Desktop's own VM process has more
than once ballooned to 8GB+ resident and stalled *all* container start/build
operations (existing containers kept running fine; only new starts/builds
hung indefinitely with near-zero CPU). The fix each time was quitting and
relaunching Docker Desktop (`osascript -e 'quit app "Docker Desktop"'` then
reopen), which reliably freed the memory and unstuck subsequent builds. If a
`docker compose build`/`up` hangs with no progress for several minutes,
check `top`/`docker ps -a` before assuming the app itself is broken — it may
well be this.

## Things to know before changing the agent harness

See `BACKEND.md`'s "Known gaps" section in full, but the two most consequential
for anyone extending write-path behavior:

- **No code the harness writes is ever executed.** Validation is syntax-only.
  If you're adding a feature that depends on the write path "knowing" whether
  something works, it currently can't — that would require an execution/test
  step that doesn't exist yet.
- **`preview_write` (dry-run + diff, no filesystem write) is fully built and
  entirely unused** — every call site hardcodes `auto_apply=True`. If you
  want a real approval-before-write flow, the validation/diff machinery
  already exists; it just needs to be threaded through the API and wired
  into the frontend's send flow.
