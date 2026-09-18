# VaultLearn backend

VaultLearn turns a public documentation site into a bounded study plan, a searchable index, and a stateful study session. The session agent can answer with source links, ask a question to check understanding, grade the reply, update a simple concept-mastery score, and write vault notes. This is a demo-ready agent loop, not merely document Q&A.

## What runs where

- FastAPI serves setup, session, resume, vault, trace, and usage APIs.
- LangGraph orchestrates setup and session decisions. Setup verifies a supplied documentation URL or searches for candidates, crawls a bounded section of up to 30 pages, plans those pages, then indexes available content. Session turns route to answer, quiz, grade, or end-and-summarize.
- Chroma persists document vectors in `chroma_db/`. Sentence Transformers supplies local embeddings and reranking; the first run may download those models.
- SQLite persists sessions, turns, quiz state, mastery scores, run events, and LLM usage in `sessions.db` by default. `VAULTLEARN_DB_PATH` overrides its location. Docker Compose mounts a named volume for the database and bind mounts for Chroma and vault notes.
- Groq provides planning, answering, quizzes, grading, and summaries. URL discovery is search-first and deterministic rather than a model guess. Configure `GROQ_API_KEY` in `Backend/.env`. Never commit a real key.

## Run locally

Use Python 3.12 or newer. From `Backend/`:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8001
```

Alternatively run `docker compose up --build` from the repository root. API docs are at `http://127.0.0.1:8001/docs` for a local run. For a reliable demo, start setup with a known public docs URL rather than a technology name, and allow time for first-run local model downloads.

## Documentation ingestion and failures

For a product name, the backend searches for candidate sites, checks that a candidate host matches the product identity (ignoring generic qualifiers such as "API" or "documentation"), fetches the page, and prefers an explicit documentation link from that site. If the docs-focused search yields nothing verifiable, it tries one bounded official-homepage search. It also handles products under a parent vendor's domain (for example, LangGraph under LangChain): a product-named page must link to a same-site documentation page that passes the documentation check. This is evidence for a likely official site, not cryptographic proof of ownership. If candidates are ambiguous or none can be verified, the setup SSE stream sends an `error` event with a machine-readable `code`, a message, and optional `candidates`; paste the desired docs URL to resolve it. A supplied URL is treated as the user's source choice, but it must resolve to a public HTML page that looks like documentation or links to one.

The crawler discovers sitemaps from `robots.txt` and `/sitemap.xml`, follows bounded sitemap indexes, respects disallow rules, and keeps pages within the selected URL path and host. Navigation and documentation-index links are followed breadth-first; sitemaps supplement them. Relative links are resolved against the fetched page URL, including its trailing slash. The synchronous demo setup still caps discovery at 30 pages—it does **not** index an entire large site. `index_report` now records `discovered_pages`, `selected_pages`, `page_limit`, and `crawl_limited` so this limit is visible rather than implying complete coverage. It does not discard a small docs site just because it has fewer than five pages. Each page is fetched directly and converted to Markdown; the Jina rendering proxy is a fallback. Failed pages appear as `skipped` progress events and in `index_report` on setup and resume. When fewer than 60% of planned pages can be indexed, setup fails with `insufficient_index_coverage` instead of creating a misleading session. Successful partial setups drop failed topics from the returned plan. A restart marks incomplete runs as `interrupted` for trace inspection.

## Demo flow

1. `POST /setup` with `{"url":"https://docs.example.com"}`. The SSE stream emits progress and a final `done` event containing `session_id`, `run_id`, `resolved_url`, `study_plan`, and `index_report`. The resolved URL is persisted with the session. Use a real public docs site in place of `example.com`.
2. `POST /session/{session_id}/message` with `{"message":"Explain routing","current_module_number":1}`. The response includes an answer, source links, and `run_id`.
3. Send `{"message":"quiz me"}`, answer the returned question, then inspect `POST /session/{session_id}/resume` for persisted turns, pending-quiz state, and mastery scores.
4. Send `{"message":"end session"}` to write latest-topic and per-session archived Markdown notes. Read them through `GET /vault` and `GET /vault/{filename}`.
5. Open `GET /runs/{run_id}/trace`, `GET /session/{session_id}/runs`, and `GET /session/{session_id}/usage` to show decisions, node latency, token counts, and estimated spend. `GET /usage` aggregates all recorded calls.

## Observability semantics

Each setup or session turn gets a run ID. The trace is an ordered SQL event log: node start/completion/failure, routing decisions, retrieval timings, quiz grades, and LLM calls. LLM records include operation, model, latency, token usage when returned by Groq, and estimated USD cost. Raw prompts and answers are not stored in the trace; conversation turns are stored separately for resume. Cost estimates use published per-million-token rates for the default Groq models; override rates with `GROQ_PRICES_JSON` (a JSON mapping from model ID to `[input_rate, output_rate]`). Missing token usage or unpriced custom models produce an unknown cost, not zero. Local embedding and reranking compute is timed but not included in dollar estimates.

Defaults are `openai/gpt-oss-20b` for routing/quiz/summary and `openai/gpt-oss-120b` for planning/answers. Override with `GROQ_URL_MODEL`, `GROQ_PLAN_MODEL`, `GROQ_ANSWER_MODEL`, and `GROQ_SUMMARY_MODEL` (the `URL` variable is retained for session routing/quiz compatibility).

## Tests and honest limits

Run `PYTHONPATH=Backend Backend/.venv/bin/python -m unittest discover -s Backend/tests -v` from the repository root. Tests exercise persistence, metering, routing, grading, memory-to-answer wiring, URL discovery, sitemap indexes, version scoping, short docs sites, content-fetch fallback, coverage failures, and API resume/trace with external services mocked. A live end-to-end setup still requires network access, Groq credentials, a reachable public documentation site, and downloaded local models.

SQLite and the SQL trace are appropriate for a single-instance portfolio demo. This is not yet a multi-tenant production service: there is no user authentication, rate limiting, durable background setup queue, vector-index recovery workflow, or OpenTelemetry export. An SSE client disconnect cancels setup; a process crash interrupts the run and requires starting setup again. Add those before exposing the API publicly. PostgreSQL becomes useful when multiple backend instances or concurrent writers are needed; it is not required just to demonstrate the agent loop.
