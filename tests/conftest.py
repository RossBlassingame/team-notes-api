from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.api import create_app


@dataclass
class TestUser:
    id: int
    username: str
    headers: dict[str, str]


@pytest.fixture
def client(tmp_path) -> TestClient:
    return TestClient(create_app(tmp_path / "test.db"))


@pytest.fixture
def make_user(client):
    def _make_user(username: str) -> TestUser:
        response = client.post("/users", json={"username": username})
        assert response.status_code == 201, response.text
        body = response.json()
        return TestUser(body["id"], username, {"Authorization": f"Bearer {body['token']}"})

    return _make_user


@pytest.fixture
def alice(make_user) -> TestUser:
    return make_user("alice")


@pytest.fixture
def bob(make_user) -> TestUser:
    return make_user("bob")
