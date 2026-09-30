"""Shared fixtures. Every test runs without infrastructure: an in-memory Mongo replaces a running one."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("ENVIRONMENT", "test")
# Deterministic, whatever a developer's `.env` says.
os.environ["BRANDS"] = "DEMO,ACME"
os.environ["ADMIN_API_SECRET_KEY"] = "test-secret"
os.environ["SEED_ON_STARTUP"] = "false"
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
# The MCP server must not build OAuth settings or reach cadmin in tests. Set (not unset): `load_dotenv`
# never overrides a key that is already present, so an empty value keeps `.env` out.
for name in (
    "ALERTS_MCP_PUBLIC_URL",
    "ALERTS_MCP_CADMIN_BASE_URL",
    "ALERTS_MCP_CADMIN_ISSUER",
    "ALERTS_MCP_CADMIN_TOKEN",
):
    os.environ[name] = ""
os.environ["ALERTS_MCP_CADMIN_REVIEW_BASE"] = "https://cadmin.test"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

from seed import seed_demo_data  # noqa: E402
from storage.mongo import MongoStore  # noqa: E402

BRANDS = ["DEMO", "ACME"]
AUTH_HEADERS = {"Authorization": "Bearer test-secret", "X-Brand": "DEMO"}


@pytest.fixture
def mock_client() -> AsyncMongoMockClient:
    return AsyncMongoMockClient()


@pytest_asyncio.fixture
async def store(mock_client: AsyncMongoMockClient) -> MongoStore:
    store = MongoStore(mock_client)
    await store.ensure_indexes(BRANDS)
    return store


@pytest_asyncio.fixture
async def seeded_store(store: MongoStore) -> MongoStore:
    await seed_demo_data(store, BRANDS)
    return store


@pytest_asyncio.fixture
async def client(seeded_store: MongoStore):
    from main import app

    app.state.store = seeded_store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=AUTH_HEADERS) as http:
        yield http
