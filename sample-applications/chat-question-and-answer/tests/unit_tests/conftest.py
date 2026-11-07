import pytest
import sys
from types import ModuleType
from fastapi.testclient import TestClient

chain_stub = ModuleType("app.chain")
chain_stub.process_chunks = lambda *_args, **_kwargs: iter([])
sys.modules["app.chain"] = chain_stub

# application packages
from app.server import app, require_admin, require_user

@pytest.fixture
def test_client():
    """A fixture to help send HTTP REST requests to API endpoints."""
    client = TestClient(app)
    yield client


@pytest.fixture
def authenticated_client(test_client):
    previous_override = app.dependency_overrides.get(require_user)
    app.dependency_overrides[require_user] = lambda: {
        "id": 7,
        "username": "test-user",
    }
    yield test_client
    if previous_override is None:
        app.dependency_overrides.pop(require_user, None)
    else:
        app.dependency_overrides[require_user] = previous_override


@pytest.fixture
def admin_client(test_client):
    previous_override = app.dependency_overrides.get(require_admin)
    app.dependency_overrides[require_admin] = lambda: {
        "id": 1,
        "username": "admin",
        "role": "admin",
    }
    yield test_client
    if previous_override is None:
        app.dependency_overrides.pop(require_admin, None)
    else:
        app.dependency_overrides[require_admin] = previous_override
