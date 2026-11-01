"""The composition root must start even when dependencies are down: warm-up is an optimization, not a requirement."""

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.composition import build_container
from backend.config import Settings


def test_startup_survives_unreachable_database_and_health_still_works() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://u:p@127.0.0.1:1/db")  # type: ignore[call-arg]
    container = build_container(settings)
    with TestClient(create_app(container)) as client:
        assert client.get("/").status_code == 200


def test_startup_survives_missing_database_url() -> None:
    container = build_container(Settings(_env_file=None, database_url=""))  # type: ignore[call-arg]
    with TestClient(create_app(container)) as client:
        assert client.get("/").json()["status"] == "HEALTHY"
