"""TaskQueue on Vercel Queues (vercel-queue SDK).

Configuration comes from the SDK's environment: VERCEL_REGION, the OIDC token (or
VERCEL_QUEUE_TOKEN), VERCEL_DEPLOYMENT_ID, and optionally VERCEL_QUEUE_BASE_URL.
"""

import logging

from vercel.queue import DuplicateIdempotencyKeyError, QueueClient

from backend.domain.errors import EnqueueError

logger = logging.getLogger(__name__)


class DefaultTaskQueue:
    def __init__(self, topic: str) -> None:
        self._topic = topic
        self._client: QueueClient | None = None

    def _get_client(self) -> QueueClient:
        # Built lazily: the constructor reads VERCEL_REGION and raises ValueError if it is absent.
        if self._client is None:
            self._client = QueueClient()
        return self._client

    async def enqueue(self, transaction_id: str) -> None:
        try:
            await self._get_client().send(
                self._topic,
                {"transaction_id": transaction_id},
                idempotency_key=transaction_id,
            )
        except DuplicateIdempotencyKeyError:
            # The platform normally drops duplicates silently; a 409 means the same thing.
            return
        except Exception as exc:
            raise EnqueueError("task queue did not accept the message") from exc

    async def warm(self) -> None:
        """Front-load first-send costs without publishing a message. Best-effort, never raises.

        Steps, each independent:
        1. Construct the QueueClient (region and base-URL resolution, httpx client setup).
        2. Resolve the auth token. This succeeds only when the token is ambient
           (VERCEL_QUEUE_TOKEN, VERCEL_OIDC_TOKEN env, or a token file). On Vercel the OIDC
           token usually arrives per request in the `x-vercel-oidc-token` header, so at startup
           this step may fail and is skipped; the token is then resolved on the first send.
        3. Open the TCP+TLS connection with an unauthenticated GET to the queue host root
           through the SDK's pooled HTTP client, so the first send reuses a live connection.
           The response status is ignored. The SDK keys its pooled client by event loop, so
           call warm() on the loop that serves requests.

        Limitation: the SDK has no no-op or health endpoint, so a fully warmed authenticated
        request is impossible without sending a message.
        """
        try:
            client = self._get_client()
        except Exception:
            logger.info("queue warm-up skipped: client could not be constructed", exc_info=True)
            return
        try:
            await client.http.token(client.token)
        except Exception:
            logger.info("queue warm-up: token not resolvable yet", exc_info=True)
        try:
            await client.http.get(f"{client.base_url}/", headers={})
        except Exception:
            logger.info("queue warm-up: connection pre-open failed", exc_info=True)
