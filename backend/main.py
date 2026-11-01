"""Web entrypoint (Vercel: tool.vercel.entrypoint = backend.main:app)."""

from backend.api.app import create_app
from backend.composition import build_container
from backend.config import Settings
from backend.logging_config import configure_logging

configure_logging()
app = create_app(build_container(Settings()))
