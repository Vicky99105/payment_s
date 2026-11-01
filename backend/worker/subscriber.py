"""Queue entrypoint (Vercel: tool.vercel.subscribers). Only Vercel Queues can invoke this function."""

from vercel.queue import Message, subscribe

from backend.composition import build_processor
from backend.config import Settings
from backend.logging_config import configure_logging
from backend.worker.handler import handle_transaction_message

configure_logging()
_settings = Settings()
_processor = build_processor(_settings)


# The queue buffers bursts; bounded concurrency keeps DB connections within budget and leaves headroom for webhooks.
@subscribe(topic=_settings.queue_topic, max_concurrency=_settings.worker_max_concurrency)
async def process_transaction(message: Message[dict[str, str]]) -> None:
    await handle_transaction_message(_processor, message.payload["transaction_id"])
