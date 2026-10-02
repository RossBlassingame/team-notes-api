import pytest


def test_register_returns_token_once(client):
    response = client.post("/users", json={"username": "alice"})

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "alice"
    assert body["token"]

    me = client.get("/users/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json() == {k: body[k] for k in ("id", "username", "created_at")}


def test_duplicate_username_is_rejected_case_insensitively(client, alice):
    response = client.post("/users", json={"username": "ALICE"})
    assert response.status_code == 409


@pytest.mark.parametrize("username", ["", "has space", "x" * 33, "semi;colon"])
def test_invalid_username_is_rejected(client, username):
    response = client.post("/users", json={"username": username})
    assert response.status_code == 422


def test_unknown_fields_are_rejected(client):
    response = client.post("/users", json={"username": "alice", "admin": True})
    assert response.status_code == 422
