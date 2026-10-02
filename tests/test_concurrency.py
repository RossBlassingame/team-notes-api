import pytest


@pytest.fixture
def note(client, alice):
    response = client.post("/notes", json={"title": "Plan", "body": "v1"}, headers=alice.headers)
    return response.json()


def patch(client, user, note, etag, **fields):
    headers = dict(user.headers)
    if etag is not None:
        headers["If-Match"] = etag
    return client.patch(f"/notes/{note['id']}", json=fields or {"body": "edit"}, headers=headers)


def test_update_without_if_match_is_428(client, alice, note):
    assert patch(client, alice, note, etag=None).status_code == 428


def test_update_with_current_etag_succeeds_and_returns_next_etag(client, alice, note):
    first = patch(client, alice, note, etag='"1"', body="v2")
    assert first.status_code == 200
    assert first.headers["ETag"] == '"2"'

    second = patch(client, alice, note, etag=first.headers["ETag"], body="v3")
    assert second.status_code == 200
    assert second.json()["body"] == "v3"


def test_second_writer_with_stale_etag_gets_412(client, alice, note):
    # Two tabs both read version 1; the first save wins and the second must not clobber it.
    etag = client.get(f"/notes/{note['id']}", headers=alice.headers).headers["ETag"]
    assert patch(client, alice, note, etag=etag, body="tab A").status_code == 200

    response = patch(client, alice, note, etag=etag, body="tab B")

    assert response.status_code == 412
    assert client.get(f"/notes/{note['id']}", headers=alice.headers).json()["body"] == "tab A"


@pytest.mark.parametrize("etag", ['W/"1"', "*", '"1", "2"', "1", "garbage"])
def test_unsupported_if_match_forms_never_match(client, alice, note, etag):
    assert patch(client, alice, note, etag=etag).status_code == 412


def test_validation_runs_before_precondition(client, alice, note):
    response = client.patch(f"/notes/{note['id']}", json={}, headers=alice.headers)
    assert response.status_code == 422


def test_update_after_delete_is_404(client, alice, note):
    client.delete(f"/notes/{note['id']}", headers=alice.headers)
    assert patch(client, alice, note, etag='"1"').status_code == 404


@pytest.mark.parametrize("etag", [None, '"7"', '"1"'])
def test_non_reader_gets_404_regardless_of_if_match(client, bob, note, etag):
    assert patch(client, bob, note, etag=etag).status_code == 404
