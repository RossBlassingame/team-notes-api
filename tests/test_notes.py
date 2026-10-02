import pytest


def create_note(client, user, **fields):
    response = client.post("/notes", json={"title": "Groceries", **fields}, headers=user.headers)
    assert response.status_code == 201, response.text
    return response


def test_create_note(client, alice):
    response = create_note(client, alice, body="eggs, milk")

    note = response.json()
    assert note["title"] == "Groceries"
    assert note["body"] == "eggs, milk"
    assert note["owner_id"] == alice.id
    assert note["version"] == 1
    assert response.headers["Location"] == f"/notes/{note['id']}"
    assert response.headers["ETag"] == '"1"'


def test_body_defaults_to_empty(client, alice):
    assert create_note(client, alice).json()["body"] == ""


def test_get_note(client, alice):
    created = create_note(client, alice)

    response = client.get(created.headers["Location"], headers=alice.headers)

    assert response.status_code == 200
    assert response.json() == created.json()
    assert response.headers["ETag"] == '"1"'


def test_other_users_cannot_see_a_private_note(client, alice, bob):
    location = create_note(client, alice).headers["Location"]

    assert client.get(location, headers=bob.headers).status_code == 404
    assert client.get("/notes", headers=bob.headers).json()["items"] == []


def test_missing_note_is_404(client, alice):
    assert client.get("/notes/999", headers=alice.headers).status_code == 404


def test_list_returns_own_notes_newest_first(client, alice, bob):
    create_note(client, alice, title="first")
    create_note(client, alice, title="second")
    create_note(client, bob, title="bob's")

    items = client.get("/notes", headers=alice.headers).json()["items"]

    assert [note["title"] for note in items] == ["second", "first"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "ok", "body": "x" * 100_001},
        {"title": None},
        {"title": "ok", "owner_id": 2},
    ],
    ids=["missing", "empty", "blank", "too-long", "body-too-long", "null", "unknown-field"],
)
def test_invalid_note_is_rejected(client, alice, payload):
    response = client.post("/notes", json=payload, headers=alice.headers)
    assert response.status_code == 422


def test_update_title_only(client, alice):
    created = create_note(client, alice, body="eggs").json()

    response = client.patch(
        f"/notes/{created['id']}", json={"title": "Shopping"}, headers=alice.headers
    )

    assert response.status_code == 200
    note = response.json()
    assert (note["title"], note["body"]) == ("Shopping", "eggs")
    assert note["version"] == 2
    assert note["updated_at"] > created["updated_at"]
    assert response.headers["ETag"] == '"2"'


def test_update_body_only(client, alice):
    created = create_note(client, alice).json()

    response = client.patch(f"/notes/{created['id']}", json={"body": "milk"}, headers=alice.headers)

    assert (response.json()["title"], response.json()["body"]) == ("Groceries", "milk")


def test_edited_note_moves_to_top_of_list(client, alice):
    first = create_note(client, alice, title="first").json()
    create_note(client, alice, title="second")

    client.patch(f"/notes/{first['id']}", json={"body": "edited"}, headers=alice.headers)

    items = client.get("/notes", headers=alice.headers).json()["items"]
    assert [note["title"] for note in items] == ["first", "second"]


@pytest.mark.parametrize(
    "payload",
    [{}, {"title": None}, {"body": None}, {"title": ""}, {"version": 5}],
    ids=["empty", "null-title", "null-body", "empty-title", "unknown-field"],
)
def test_invalid_update_is_rejected(client, alice, payload):
    note_id = create_note(client, alice).json()["id"]

    response = client.patch(f"/notes/{note_id}", json=payload, headers=alice.headers)

    assert response.status_code == 422


def test_delete_note(client, alice):
    location = create_note(client, alice).headers["Location"]

    assert client.delete(location, headers=alice.headers).status_code == 204
    assert client.get(location, headers=alice.headers).status_code == 404
    assert client.delete(location, headers=alice.headers).status_code == 404


def test_other_users_cannot_update_or_delete(client, alice, bob):
    location = create_note(client, alice).headers["Location"]

    assert client.patch(location, json={"title": "mine"}, headers=bob.headers).status_code == 404
    assert client.delete(location, headers=bob.headers).status_code == 404
    assert client.get(location, headers=alice.headers).json()["title"] == "Groceries"
