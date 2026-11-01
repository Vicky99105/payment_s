from typing import Protocol


class TaskQueue(Protocol):
    async def enqueue(self, transaction_id: str) -> None:
        """Publish a processing task. Idempotency key = transaction_id, so duplicates are dropped.

        Raises EnqueueError if the queue did not accept the message.
        """
        ...
