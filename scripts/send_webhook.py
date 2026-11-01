"""Send one signed webhook, the way a payment processor would.

Usage:
  WEBHOOK_SIGNING_SECRET=... python scripts/send_webhook.py https://payment-s.vercel.app txn_abc123 [amount] [currency]
"""

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request


def main() -> None:
    base, txn_id = sys.argv[1].rstrip("/"), sys.argv[2]
    amount = float(sys.argv[3]) if len(sys.argv) > 3 else 1500
    currency = sys.argv[4] if len(sys.argv) > 4 else "INR"
    secret = os.environ["WEBHOOK_SIGNING_SECRET"]

    body = json.dumps(
        {
            "transaction_id": txn_id,
            "source_account": "acc_user_789",
            "destination_account": "acc_merchant_456",
            "amount": amount,
            "currency": currency,
        }
    ).encode()
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        f"{base}/v1/webhooks/transactions",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Webhook-Timestamp": ts, "X-Webhook-Signature": f"sha256={sig}"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status, text = resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        status, text = err.code, err.read().decode()
    print(f"{status} in {(time.perf_counter() - started) * 1000:.0f}ms: {text}")


if __name__ == "__main__":
    main()
