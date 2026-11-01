# Payment Service

A Python service that receives transaction webhooks from payment processors, acknowledges them immediately, and settles each transaction reliably in the background.

**Live:** https://payment-s.vercel.app

## What it does

| Endpoint | Auth | Behaviour |
|---|---|---|
| `GET /` | public | `{"status": "HEALTHY", "current_time": "..."}` |
| `POST /v1/webhooks/transactions` | HMAC signature | Stores the transaction, enqueues it, returns `202 Accepted`. Duplicates also get `202` and are never processed twice. |
| `GET /v1/transactions/{transaction_id}` | API key (`transactions:read`) | Returns `[{... "status": "PROCESSING" or "PROCESSED", "created_at", "processed_at"}]` |

Processing simulates an external settlement call that takes 30 seconds, then marks the transaction `PROCESSED`.

## Architecture

```
                 Ingestion (HTTP function, cdg1)                         Processing (queue consumer, cdg1)
Processor ──► POST /v1/webhooks/transactions                    ┌──► worker/subscriber.py
              1. verify HMAC signature                          │      TransactionProcessor.process
              2. validate body                                  │        record_attempt
              3. ONE SQL statement: log delivery +              │        SettlementGateway.settle   (30s)
                 INSERT ... ON CONFLICT DO NOTHING ──► Postgres │        mark_processed  (guarded UPDATE)
              4. enqueue(transaction_id) ──────────► Vercel Queue
              5. 202
```

Two services with a hard boundary: they share no memory and talk only through the queue and the database. Vercel deploys them as separate functions from one repository, and each scales on its own.

### Request path in more detail

- **Webhook:** signature check, then body validation, then `ingest`, then `enqueue`, then `202`.
  - If the database or the queue fails, the response is `503` with `Retry-After`, never `202`. The processor then retries the webhook, so an event is never acknowledged before it is stored.
  - A retried webhook finds the row still `PROCESSING` and enqueues it again. That covers the case where the row was stored but the first enqueue failed.
- **Worker:** `record_attempt`, then `settle` (30s), then `mark_processed`.
  - If settlement fails, the attempt and error are recorded and the worker asks the queue to redeliver after 5s, 10s, 20s ... up to 60s.
  - If the worker process dies outright, the queue redelivers once its 5-minute lease expires.
- **Query:** reads the row.

### Idempotency, three layers

1. `transaction_id` is the primary key, and the insert uses `ON CONFLICT DO NOTHING`, so a duplicate never creates a second row.
2. The queue idempotency key is `transaction_id`, so the queue drops duplicate messages.
3. `mark_processed` is `UPDATE ... WHERE status = 'PROCESSING'`. Even if a message were delivered twice, only one call makes the transition, and `processed_at` is set exactly once.

Every delivery, duplicates included, is appended to `webhook_deliveries`. That gives an audit trail and makes "10 deliveries, 1 transaction" visible.

## Security

| Control | Implementation |
|---|---|
| Webhook authentication | HMAC-SHA256 over `f"{timestamp}.{raw_body}"`, in headers `X-Webhook-Timestamp` and `X-Webhook-Signature: sha256=<hex>` (the same scheme RazorPay uses). Constant-time comparison. Timestamps more than 300s from now are rejected, which blocks replays. The signature is checked before the body is parsed. |
| API authentication | `Authorization: Bearer <key>`. The server stores only SHA-256 hashes of keys (`API_KEYS` env var). |
| Authorization | Scopes on a `Principal`: `webhooks:write` (signing-secret holder), `transactions:read` (reviewer key). A missing scope gives `403`. Single tenant, so there is no users table. |
| Input | Strict schema: unknown fields rejected, id patterns, `Decimal` amount (> 0, 2 dp), ISO currency code, 16KB body limit (`413`). Error responses never echo input values. |
| Database | The app connects as a least-privilege role (`payment_service`: SELECT/INSERT/UPDATE on two tables, no DELETE, no DDL). Parameterized queries only, TLS required. RLS is on, so Supabase's public REST API cannot read the tables. |
| Errors and logs | `500` bodies are generic and carry a `request_id`. Logs are JSON lines with `transaction_id`, never account numbers, payloads or secrets. |
| Surface | API docs are off in production. Responses are `Cache-Control: no-store`. The worker function can only be invoked by Vercel Queues. Configuration defaults to production (fail safe). Missing secrets make auth fail closed. |

## Try it

You need the webhook signing secret and the reviewer API key. They are shared separately, never in this repository.

```bash
export WEBHOOK_SIGNING_SECRET=...   # provided separately
export API_KEY=...                  # provided separately
```

Send a signed webhook:

```bash
python scripts/send_webhook.py https://payment-s.vercel.app txn_demo_001
```

Check the transaction straight away (`PROCESSING`) and again after about 30s (`PROCESSED`):

```bash
curl -s https://payment-s.vercel.app/v1/transactions/txn_demo_001 -H "Authorization: Bearer $API_KEY"
```

Unauthenticated requests are rejected:

```bash
curl -s -X POST https://payment-s.vercel.app/v1/webhooks/transactions -H 'content-type: application/json' -d '{"transaction_id":"x"}'
```

## Run locally

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env    # then fill in values
uv run uvicorn backend.main:app --reload
```

The queue needs Vercel's environment to publish messages. Locally, webhooks are stored, but the enqueue step returns `503` unless you point the SDK at its devserver (`uv run python -m vercel.queue.devserver`, see `tests/integration/test_task_queue.py`).

## Tests

```bash
uv run pytest tests/unit -q          # 80 tests, < 1s, no network (services on in-memory fakes)
uv run pytest tests/integration -q   # 19 tests: real Postgres (DATABASE_URL) + the queue SDK's local devserver
uv run mypy backend                  # strict
uv run pip-audit
```

| Suite | Covers |
|---|---|
| `test_ingestion_service`, `test_transaction_processor`, `test_query_service` | Duplicates in every state, queue and DB outages, settlement failure and backoff, redelivery after success |
| `test_worker_handler` | A settlement retry becomes a queue `RetryAfter`; other errors fall through to the lease backstop |
| `test_webhook_signature`, `test_api_keys`, `test_security_dependencies` | Wrong secret, tampered body, replayed or future timestamps, malformed headers, unknown keys, missing scopes, broken key config failing closed |
| `test_api` | Status codes and response shapes, `401` before `422`, `413`, `503` not `202`, generic `500`, docs off in production, no-store headers |
| `integration/test_transaction_repository` | Real SQL: single-round-trip ingest, decimal precision, guarded transitions, 20 concurrent duplicate ingests giving exactly 1 row |
| `integration/test_task_queue` | Publish, idempotent duplicate drop, unreachable queue giving `EnqueueError` |

Against the deployed service:

```bash
uv run python scripts/verify_live.py https://payment-s.vercel.app       # the 4 success criteria + security checks
uv run python scripts/load_test.py https://payment-s.vercel.app 200 50  # latency percentiles under load, then confirms all processed
```

CI (`.github/workflows/ci.yml`) runs type checks, unit tests and the dependency audit on every push.

## Technical choices

- **FastAPI.** Async I/O fits a webhook endpoint that spends its time waiting on the network. Pydantic gives strict validation and the HTTP contract in one place.
- **A durable queue, not a background task.** On serverless platforms a function can be frozen once the response is sent, so a `sleep(30)` after returning `202` can silently never finish. Even on a normal server, an in-process task dies with the process. Vercel Queues stores the task and redelivers it if the worker fails. That is what makes "no lost transactions" true.
  - Verified on the live platform before building: a 30s job finished at 30.0s; 50 concurrent jobs all finished in parallel; a duplicate key was processed once; a failed delivery was retried.
- **Supabase Postgres.** Managed Postgres gives the primary key, `ON CONFLICT` and guarded `UPDATE`, which are the primitives the idempotency design rests on. The app uses the transaction pooler (asyncpg with the statement cache off), suited to many short-lived serverless connections.
- **Co-location.** The functions run in `cdg1` (Paris), next to the database in `eu-west-3`, so each database round trip stays within the region.
- **Deep modules behind contracts.** Every service, repository and integration is a `typing.Protocol`, with a `Default*` implementation. Routes and the worker import contracts only. `backend/composition.py` is the only module that knows concrete classes. Tests run against `Fake*` implementations of the same contracts, not mocks.
- **More payment providers later.** The 5-field body is the canonical internal format. A new provider would get its own route plus an adapter that verifies that provider's signature and maps its payload to the canonical model. Everything after normalization stays the same. With several providers, the key would become `(provider, transaction_id)`.

## Project layout

```
backend/
  main.py                 web entrypoint
  composition.py          wiring: the only place Default* classes are imported
  api/                    routes, HTTP schemas, error mapping, middleware
  services/               ingestion / processing / query: contract.py + service.py each
  security/               signature verifier, API keys, scope checks
  integrations/           queue (Vercel Queues), settlement (simulated 30s gateway)
  database/               pool, repository (contract + asyncpg implementation)
  worker/                 queue subscriber + testable handler
supabase/migrations/      schema, least-privilege role, RLS policies
tests/unit, tests/integration
scripts/                  send_webhook, verify_live, load_test, set_vercel_env
```
