# Generation Job Queue — Design-Only Stubs (Phase 6)

This package defines the contract for queueable generation jobs. No queue
backend is imported or required at runtime.

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package docstring — empty runtime |
| `generation_job_contract.py` | Payload, Result, Queue Protocol, and `enqueue_generation_job` placeholder |
| `README.md` | This file |

## Migration Path

See `docs/phase-6-worker-queue-reliability-design.md` for full details.

### Subphases

1. **Phase 6A** — Queue abstraction interface (this stub; no runtime change)
2. **Phase 6B** — DB-backed or Redis queue setup
3. **Phase 6C** — Worker process entrypoint
4. **Phase 6D** — Move generation runner into worker
5. **Phase 6E** — Frontend polling/SSE DB-backed progress
6. **Phase 6F** — Stale job recovery and retries

## Current Runtime

Generation tasks still run in-process via `asyncio.create_task` in
`app/application/use_cases/generation_start.py`. The `enqueue_generation_job`
placeholder logs intent but returns immediately — the real enqueue will be
wired in Phase 6D.
