import sqlite3
from contextlib import closing

import pytest


@pytest.fixture
def users(make_user):
    return {name: make_user(name) for name in ["alice", "bob", "carol", "dave"]}


@pytest.fixture
def teams(client, users):
    """Alice owns both teams; bob is on `platform`, carol on `design`, dave on neither."""
    alice = users["alice"]
    created = {}
    for name, member in [("platform", "bob"), ("design", "carol")]:
        team = client.post("/teams", json={"name": name}, headers=alice.headers).json()
        client.post(
            f"/teams/{team['id']}/members", json={"username": member}, headers=alice.headers
        )
        created[name] = team["id"]
    return created


@pytest.fixture
def note(client, users):
    alice = users["alice"]
    return client.post("/notes", json={"title": "Roadmap"}, headers=alice.headers).json()


def share(client, user, note, team_id):
    return client.put(f"/notes/{note['id']}/shares/{team_id}", headers=user.headers)


def unshare(client, user, note, team_id):
    return client.delete(f"/notes/{note['id']}/shares/{team_id}", headers=user.headers)


def get(client, user, note):
    return client.get(f"/notes/{note['id']}", headers=user.headers)


def edit(client, user, note, etag='"1"', body="edited"):
    headers = {**user.headers, "If-Match": etag}
    return client.patch(f"/notes/{note['id']}", json={"body": body}, headers=headers)


def test_new_notes_are_private(client, users, teams, note):
    assert note["shared_with"] == []
    for name in ["bob", "carol", "dave"]:
        assert get(client, users[name], note).status_code == 404


def test_team_members_can_read_and_edit_a_shared_note(client, users, teams, note):
    assert share(client, users["alice"], note, teams["platform"]).status_code == 201

    assert get(client, users["bob"], note).status_code == 200
    assert edit(client, users["bob"], note).status_code == 200
    assert get(client, users["alice"], note).json()["body"] == "edited"
    assert get(client, users["carol"], note).status_code == 404


def test_note_can_be_shared_with_several_teams(client, users, teams, note):
    alice = users["alice"]
    share(client, alice, note, teams["design"])
    share(client, alice, note, teams["platform"])

    assert get(client, users["bob"], note).status_code == 200
    assert get(client, users["carol"], note).status_code == 200
    assert get(client, users["dave"], note).status_code == 404
    shared_with = get(client, alice, note).json()["shared_with"]
    assert shared_with == sorted([teams["platform"], teams["design"]])


def test_shared_note_appears_once_in_list_even_via_two_teams(client, users, teams, note):
    alice, bob = users["alice"], users["bob"]
    client.post(
        f"/teams/{teams['design']}/members", json={"username": "bob"}, headers=alice.headers
    )
    share(client, alice, note, teams["platform"])
    share(client, alice, note, teams["design"])

    items = client.get("/notes", headers=bob.headers).json()["items"]

    assert [item["id"] for item in items] == [note["id"]]
    assert client.get("/notes", headers=users["dave"].headers).json()["items"] == []


def test_sharing_is_idempotent_and_keeps_the_etag(client, users, teams, note):
    alice = users["alice"]
    first, repeat = (share(client, alice, note, teams["platform"]) for _ in range(2))
    assert (first.status_code, first.content) == (201, b"")
    assert (repeat.status_code, repeat.content) == (204, b"")

    # Sharing isn't a content edit: the owner's ETag from before sharing still works.
    assert get(client, alice, note).headers["ETag"] == '"1"'
    assert edit(client, alice, note, etag='"1"').status_code == 200


def test_unsharing_revokes_only_that_team(client, users, teams, note):
    alice = users["alice"]
    share(client, alice, note, teams["platform"])
    share(client, alice, note, teams["design"])

    assert unshare(client, alice, note, teams["platform"]).status_code == 204

    bob = users["bob"]
    assert get(client, bob, note).status_code == 404
    assert edit(client, bob, note).status_code == 404
    assert client.get("/notes", headers=bob.headers).json()["items"] == []
    assert client.get("/notes", params={"q": "Roadmap"}, headers=bob.headers).json()["items"] == []
    assert get(client, users["carol"], note).status_code == 200
    assert get(client, alice, note).json()["shared_with"] == [teams["design"]]


def test_unsharing_a_team_that_was_never_shared_is_204(client, users, teams, note):
    assert unshare(client, users["alice"], note, teams["platform"]).status_code == 204


def test_only_the_owner_can_share_unshare_or_delete(client, users, teams, note):
    bob = users["bob"]
    share(client, users["alice"], note, teams["platform"])  # bob can now read it

    assert share(client, bob, note, teams["platform"]).status_code == 403
    assert unshare(client, bob, note, teams["platform"]).status_code == 403
    assert client.delete(f"/notes/{note['id']}", headers=bob.headers).status_code == 403


def test_non_readers_get_404_from_share_endpoints(client, users, teams, note):
    dave = users["dave"]

    assert share(client, dave, note, teams["platform"]).status_code == 404
    assert unshare(client, dave, note, teams["platform"]).status_code == 404


def test_owner_can_only_share_with_their_own_teams(client, users, teams, note):
    dave = users["dave"]
    daves_team = client.post("/teams", json={"name": "dave's"}, headers=dave.headers).json()

    for team_id in [daves_team["id"], 999]:
        assert share(client, users["alice"], note, team_id).status_code == 404


def test_concurrent_edits_by_teammates_conflict(client, users, teams, note):
    alice, bob = users["alice"], users["bob"]
    share(client, alice, note, teams["platform"])
    etag = get(client, bob, note).headers["ETag"]

    assert edit(client, alice, note, etag=etag, body="alice's edit").status_code == 200
    assert edit(client, bob, note, etag=etag, body="bob's edit").status_code == 412
    assert get(client, bob, note).json()["body"] == "alice's edit"


def test_deleting_a_note_removes_its_shares(client, users, teams, note):
    alice = users["alice"]
    share(client, alice, note, teams["platform"])

    assert client.delete(f"/notes/{note['id']}", headers=alice.headers).status_code == 204

    with closing(sqlite3.connect(client.app.state.db_path)) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM note_shares WHERE note_id = ?", (note["id"],)
        ).fetchone()
    assert remaining == (0,)


def test_sharing_a_note_deleted_mid_request_is_404(client, users, teams, note, monkeypatch):
    from app.routes import notes as notes_routes

    real_is_member = notes_routes.is_member

    def delete_note_then_check(conn, team_id, user_id):
        # Simulate the owner deleting the note from another request after it was fetched.
        with closing(sqlite3.connect(client.app.state.db_path)) as other:
            other.execute("DELETE FROM notes WHERE id = ?", (note["id"],))
            other.commit()
        return real_is_member(conn, team_id, user_id)

    monkeypatch.setattr(notes_routes, "is_member", delete_note_then_check)

    assert share(client, users["alice"], note, teams["platform"]).status_code == 404


def test_team_members_can_search_shared_notes(client, users, teams, note):
    share(client, users["alice"], note, teams["platform"])

    def found(user):
        response = client.get("/notes", params={"q": "roadmap"}, headers=user.headers)
        return [item["id"] for item in response.json()["items"]]

    assert found(users["bob"]) == [note["id"]]
    assert found(users["carol"]) == []
