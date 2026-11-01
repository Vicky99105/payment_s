"""Webhook latency under load, while earlier jobs are still in their 30s settlement.

Usage: python scripts/load_test.py https://payment-s.vercel.app [total=200] [concurrency=50]
Prints client-side p50/p95/p99/max, then waits until every transaction is PROCESSED (nothing lost).
"""

import asyncio
import hashlib
import hmac
import json
import sys
import time
import uuid

import httpx

from backend.config import Settings

BASE = sys.argv[1].rstrip("/")
TOTAL = int(sys.argv[2]) if len(sys.argv) > 2 else 200
CONCURRENCY = int(sys.argv[3]) if len(sys.argv) > 3 else 50
SECRET = Settings().webhook_signing_secret
RUN = uuid.uuid4().hex[:8]


def reviewer_key() -> str:
    for line in open(".env"):
        if line.startswith("REVIEWER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("REVIEWER_API_KEY not found in .env")


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


async def send(c: httpx.AsyncClient, sem: asyncio.Semaphore, txn_id: str) -> tuple[int, float]:
    raw = json.dumps({"transaction_id": txn_id, "source_account": "acc_load_1", "destination_account": "acc_load_2", "amount": 99.99, "currency": "INR"}).encode()
    async with sem:
        ts = str(int(time.time()))
        sig = hmac.new(SECRET.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
        started = time.perf_counter()
        r = await c.post(f"{BASE}/v1/webhooks/transactions", content=raw, headers={"Content-Type": "application/json", "X-Webhook-Timestamp": ts, "X-Webhook-Signature": f"sha256={sig}"})
        return r.status_code, (time.perf_counter() - started) * 1000


async def main() -> None:
    ids = [f"live_{RUN}_load_{i}" for i in range(TOTAL)]
    sem = asyncio.Semaphore(CONCURRENCY)
    limits = httpx.Limits(max_connections=CONCURRENCY, max_keepalive_connections=CONCURRENCY)
    async with httpx.AsyncClient(timeout=20, limits=limits) as c:
        await c.get(f"{BASE}/")  # open a connection so the first sample doesn't include TLS setup
        wall = time.perf_counter()
        out = await asyncio.gather(*[send(c, sem, i) for i in ids])
        wall_ms = (time.perf_counter() - wall) * 1000
        codes = [code for code, _ in out]
        lat = [ms for _, ms in out]
        print(f"sent {TOTAL} webhooks at concurrency {CONCURRENCY} in {wall_ms:.0f}ms")
        print(f"status codes: { {code: codes.count(code) for code in set(codes)} }")
        print(f"client latency ms: p50={pct(lat, 50):.0f} p95={pct(lat, 95):.0f} p99={pct(lat, 99):.0f} max={max(lat):.0f}")
        print(f"under 500ms: {sum(ms < 500 for ms in lat)}/{TOTAL}")

        key = reviewer_key()
        deadline = time.monotonic() + 150
        pending = set(ids)
        while pending and time.monotonic() < deadline:
            await asyncio.sleep(5)
            for txn_id in list(pending):
                r = await c.get(f"{BASE}/v1/transactions/{txn_id}", headers={"Authorization": f"Bearer {key}"})
                if r.status_code == 200 and r.json()[0]["status"] == "PROCESSED":
                    pending.discard(txn_id)
            print(f"  processed {TOTAL - len(pending)}/{TOTAL}", flush=True)
        print("ALL PROCESSED (none lost)" if not pending else f"NOT PROCESSED: {len(pending)} e.g. {sorted(pending)[:3]}")
        sys.exit(0 if not pending and codes.count(202) == TOTAL else 1)


asyncio.run(main())
