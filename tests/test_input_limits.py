"""Malformed input gets a 4xx, never a 500."""

import pytest

HUGE = "9" * 20  # beyond SQLite's 64-bit integers


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"/notes/{HUGE}"),
        ("PATCH", f"/notes/{HUGE}"),
        ("DELETE", f"/notes/{HUGE}"),
        ("PUT", f"/notes/1/shares/{HUGE}"),
        ("DELETE", f"/notes/{HUGE}/shares/1"),
        ("POST", f"/teams/{HUGE}/members"),
        ("GET", "/notes/0"),
    ],
)
def test_out_of_range_ids_are_422(client, alice, method, path):
    response = client.request(method, path, json={"username": "bob"}, headers=alice.headers)
    assert response.status_code == 422


def test_out_of_range_offset_is_422(client, alice):
    response = client.get("/notes", params={"offset": HUGE}, headers=alice.headers)
    assert response.status_code == 422


@pytest.mark.parametrize("etag", [f'"{HUGE}"', '"01"'])
def test_if_match_must_be_exactly_an_issued_etag(client, alice, etag):
    note = client.post("/notes", json={"title": "x"}, headers=alice.headers).json()

    response = client.patch(
        f"/notes/{note['id']}", json={"body": "y"}, headers={**alice.headers, "If-Match": etag}
    )

    assert response.status_code == 412


@pytest.mark.parametrize(
    ("path", "raw_json"),
    [
        ("/notes", '{"title": "\\ud800"}'),
        ("/notes", '{"title": "ok", "body": "\\udfff"}'),
        ("/teams", '{"name": "\\ud800"}'),
    ],
)
def test_text_that_is_not_valid_utf8_is_422(client, alice, path, raw_json):
    headers = {**alice.headers, "Content-Type": "application/json"}
    assert client.post(path, content=raw_json, headers=headers).status_code == 422


def test_validation_errors_do_not_echo_the_input(client, alice):
    response = client.post("/notes", json={"title": "x" * 5000}, headers=alice.headers)

    assert response.status_code == 422
    assert "x" * 5000 not in response.text
    assert response.json()["detail"][0]["loc"] == ["body", "title"]
