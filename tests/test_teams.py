import pytest


def create_team(client, user, name="Platform"):
    response = client.post("/teams", json={"name": name}, headers=user.headers)
    assert response.status_code == 201, response.text
    return response.json()


def team_names(client, user):
    return [team["name"] for team in client.get("/teams", headers=user.headers).json()["items"]]


def test_creator_is_a_member(client, alice):
    team = create_team(client, alice)

    assert team["name"] == "Platform"
    assert team["created_by"] == alice.id
    assert team_names(client, alice) == ["Platform"]


def test_list_shows_only_my_teams(client, alice, bob):
    create_team(client, alice, "Platform")
    create_team(client, bob, "Design")

    assert team_names(client, alice) == ["Platform"]
    assert team_names(client, bob) == ["Design"]


def test_member_can_add_by_username_idempotently(client, alice, bob):
    team = create_team(client, alice)

    for username in ["bob", "BOB"]:  # usernames match case-insensitively
        response = client.post(
            f"/teams/{team['id']}/members", json={"username": username}, headers=alice.headers
        )
        assert response.status_code == 204

    assert team_names(client, bob) == ["Platform"]


def test_added_member_can_add_others(client, alice, bob, make_user):
    team = create_team(client, alice)
    client.post(f"/teams/{team['id']}/members", json={"username": "bob"}, headers=alice.headers)
    make_user("carol")

    response = client.post(
        f"/teams/{team['id']}/members", json={"username": "carol"}, headers=bob.headers
    )

    assert response.status_code == 204


def test_unknown_username_is_422(client, alice):
    team = create_team(client, alice)

    response = client.post(
        f"/teams/{team['id']}/members", json={"username": "nobody"}, headers=alice.headers
    )

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"type": "value_error", "loc": ["body", "username"], "msg": "No such user"}
    ]


def test_non_member_cannot_add_members(client, alice, bob):
    team = create_team(client, alice)

    for team_id in [team["id"], 999]:
        response = client.post(
            f"/teams/{team_id}/members", json={"username": "bob"}, headers=bob.headers
        )
        assert response.status_code == 404

    assert team_names(client, bob) == []


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_invalid_team_name_is_rejected(client, alice, name):
    assert client.post("/teams", json={"name": name}, headers=alice.headers).status_code == 422
