"""Runs the assignment's success criteria plus the security checks against a deployed URL.

Usage: python scripts/verify_live.py https://payment-s.vercel.app
Reads WEBHOOK_SIGNING_SECRET, REVIEWER_API_KEY and DATABASE_URL from the environment / .env.
DATABASE_URL is used read-only, to count webhook deliveries (not exposed by the API).
Set FAULT_INJECTION_ENABLED=1 only when the deployment has SETTLEMENT_FAULT_INJECTION=true.
"""

import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import datetime

import asyncpg
import httpx

from backend.config import Settings

BASE = sys.argv[1].rstrip("/")
RUN = uuid.uuid4().hex[:8]
env = Settings()
SECRET = env.webhook_signing_secret
results: list[tuple[str, bool, str]] = []


def _reviewer_key() -> str:
    if os.environ.get("REVIEWER_API_KEY"):
        return os.environ["REVIEWER_API_KEY"]
    for line in open(".env"):
        if line.startswith("REVIEWER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("REVIEWER_API_KEY not found")


KEY = _reviewer_key()


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{': ' + detail if detail else ''}", flush=True)


def body(txn_id: str, **kw: object) -> bytes:
    payload = {"transaction_id": txn_id, "source_account": "acc_user_789", "destination_account": "acc_merchant_456", "amount": 1500, "currency": "INR"}
    payload.update(kw)
    return json.dumps(payload).encode()


def signed(raw: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Webhook-Timestamp": ts, "X-Webhook-Signature": f"sha256={sig}"}


async def post(c: httpx.AsyncClient, raw: bytes, sign: bool = True) -> httpx.Response:
    headers = signed(raw) if sign else {"Content-Type": "application/json"}
    return await c.post(f"{BASE}/v1/webhooks/transactions", content=raw, headers=headers)


async def get(c: httpx.AsyncClient, txn_id: str, key: str | None = KEY) -> httpx.Response:
    return await c.get(f"{BASE}/v1/transactions/{txn_id}", headers={"Authorization": f"Bearer {key}"} if key else {})


async def wait_processed(c: httpx.AsyncClient, txn_id: str, timeout: float) -> dict[str, object] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = await get(c, txn_id)
        if r.status_code == 200 and r.json()[0]["status"] == "PROCESSED":
            return r.json()[0]  # type: ignore[no-any-return]
        await asyncio.sleep(2)
    return None


def seconds_between(a: str, b: str) -> float:
    return (datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds()


async def main() -> None:
    db = await asyncpg.connect(env.database_url, statement_cache_size=0)
    async with httpx.AsyncClient(timeout=20) as c:
        print(f"run id: {RUN}")
        r = await c.get(f"{BASE}/")
        check("health is public and HEALTHY", r.status_code == 200 and r.json().get("status") == "HEALTHY", r.text)

        # Security
        check("unsigned webhook -> 401", (await post(c, body(f"live_{RUN}_unsigned"), sign=False)).status_code == 401)
        check("GET without key -> 401", (await get(c, "txn_x", key=None)).status_code == 401)
        check("GET with wrong key -> 401", (await get(c, "txn_x", key="wrong")).status_code == 401)
        check("/docs disabled", (await c.get(f"{BASE}/docs")).status_code == 404)

        # 1. Single transaction
        single = f"live_{RUN}_single"
        t0 = time.perf_counter()
        r = await post(c, body(single))
        ms = (time.perf_counter() - t0) * 1000
        check("single: webhook -> 202", r.status_code == 202, f"{ms:.0f}ms client round trip")
        first = (await get(c, single)).json()[0]
        check("single: immediately PROCESSING with processed_at null", first["status"] == "PROCESSING" and first["processed_at"] is None)
        done = await wait_processed(c, single, timeout=60)
        if done:
            took = seconds_between(str(done["created_at"]), str(done["processed_at"]))
            check("single: PROCESSED after ~30s", 30 <= took <= 40, f"processed_at - created_at = {took:.1f}s")
        else:
            check("single: PROCESSED after ~30s", False, "not processed within 60s")

        # 2. Duplicate prevention
        dup = f"live_{RUN}_dup"
        statuses = [(await post(c, body(dup))).status_code for _ in range(5)]
        statuses += [r.status_code for r in await asyncio.gather(*[post(c, body(dup)) for _ in range(5)])]
        check("duplicates: all 10 -> 202", statuses == [202] * 10, str(statuses))
        done = await wait_processed(c, dup, timeout=60)
        rows = await db.fetchval("select count(*) from transactions where transaction_id = $1", dup)
        deliveries = await db.fetchval("select count(*) from webhook_deliveries where transaction_id = $1", dup)
        check("duplicates: 1 transaction, 10 deliveries", rows == 1 and deliveries == 10, f"rows={rows} deliveries={deliveries}")
        check("duplicates: processed once (attempts == 1)", done is not None and await db.fetchval("select attempts from transactions where transaction_id=$1", dup) == 1)

        # 3. Validation and reliability
        check("malformed body -> 422", (await post(c, body(f"live_{RUN}_bad", amount=-1))).status_code == 422)
        if os.environ.get("FAULT_INJECTION_ENABLED") == "1":
            fault = f"faultinject_live_{RUN}"
            check("fault: webhook -> 202", (await post(c, body(fault))).status_code == 202)
            done = await wait_processed(c, fault, timeout=90)
            attempts = await db.fetchval("select attempts from transactions where transaction_id=$1", fault)
            check("fault: first settlement fails, retried, ends PROCESSED with attempts == 2", done is not None and attempts == 2, f"attempts={attempts}")
        else:
            print("[SKIP] fault-injection retry check (set FAULT_INJECTION_ENABLED=1 with SETTLEMENT_FAULT_INJECTION=true on the deployment)")

    await db.close()
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


asyncio.run(main())
