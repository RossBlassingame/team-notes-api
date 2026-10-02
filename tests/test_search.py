import pytest


def create_notes(client, user, *titles, body=""):
    for title in titles:
        client.post("/notes", json={"title": title, "body": body}, headers=user.headers)


def search(client, user, **params):
    response = client.get("/notes", params=params, headers=user.headers)
    assert response.status_code == 200, response.text
    return [note["title"] for note in response.json()["items"]]


def test_matches_title_or_body_case_insensitively(client, alice):
    create_notes(client, alice, "Quarterly PLANNING")
    create_notes(client, alice, "Retro", body="action items: planning poker")
    create_notes(client, alice, "Lunch")

    assert search(client, alice, q="planning") == ["Retro", "Quarterly PLANNING"]


@pytest.mark.parametrize(
    ("q", "expected"),
    [("100%", ["100% done"]), ("a_b", ["a_b"]), ("C:\\tmp", ["C:\\tmp"])],
)
def test_wildcard_characters_match_literally(client, alice, q, expected):
    create_notes(client, alice, "100% done", "1000 done", "a_b", "axb", "C:\\tmp", "C:tmp")

    assert search(client, alice, q=q) == expected


def test_search_never_returns_notes_you_cannot_read(client, alice, bob):
    create_notes(client, alice, "secret plan")
    create_notes(client, bob, "bob's plan")

    assert search(client, bob, q="plan") == ["bob's plan"]


def test_pagination(client, alice):
    create_notes(client, alice, *[f"note {i}" for i in range(5)])

    assert search(client, alice, limit=2) == ["note 4", "note 3"]
    assert search(client, alice, limit=2, offset=2) == ["note 2", "note 1"]
    assert search(client, alice, limit=2, offset=4) == ["note 0"]


def test_list_reports_pagination_defaults(client, alice):
    body = client.get("/notes", headers=alice.headers).json()
    assert (body["limit"], body["offset"]) == (20, 0)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_out_of_range_pagination_is_rejected(client, alice, params):
    assert client.get("/notes", params=params, headers=alice.headers).status_code == 422
