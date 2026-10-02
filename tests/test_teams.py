import threading
from concurrent.futures import ThreadPoolExecutor

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


def add_member(client, user, team, username):
    return client.post(
        f"/teams/{team['id']}/members", json={"username": username}, headers=user.headers
    )


def remove_member(client, user, team, username):
    return client.delete(f"/teams/{team['id']}/members/{username}", headers=user.headers)


def test_member_can_remove_another_member(client, alice, bob, make_user):
    carol = make_user("carol")
    team = create_team(client, alice)
    add_member(client, alice, team, "bob")
    add_member(client, alice, team, "carol")

    assert remove_member(client, bob, team, "Carol").status_code == 204  # case-insensitive

    assert team_names(client, carol) == []
    assert team_names(client, bob) == ["Platform"]


def test_member_can_leave(client, alice, bob):
    team = create_team(client, alice)
    add_member(client, alice, team, "bob")

    assert remove_member(client, bob, team, "bob").status_code == 204

    assert team_names(client, bob) == []
    assert add_member(client, bob, team, "bob").status_code == 404  # no longer a member


def test_last_member_cannot_leave(client, alice):
    team = create_team(client, alice)

    response = remove_member(client, alice, team, "alice")

    assert response.status_code == 409
    assert team_names(client, alice) == ["Platform"]


@pytest.mark.parametrize("username", ["bob", "nobody"])
def test_removing_someone_who_is_not_a_member_is_204(client, alice, bob, username):
    team = create_team(client, alice)
    assert remove_member(client, alice, team, username).status_code == 204


def test_non_member_cannot_remove_members(client, alice, bob):
    team = create_team(client, alice)

    assert remove_member(client, bob, team, "alice").status_code == 404
    assert remove_member(client, bob, {"id": 999}, "alice").status_code == 404
    assert team_names(client, alice) == ["Platform"]


@pytest.mark.parametrize("username", ["-x", "x" * 33, "a b"])
def test_invalid_username_in_path_is_422(client, alice, username):
    team = create_team(client, alice)
    assert remove_member(client, alice, team, username).status_code == 422


def test_simultaneous_leaves_cannot_empty_a_team(client, alice, bob):
    team = create_team(client, alice)
    add_member(client, alice, team, "bob")
    barrier = threading.Barrier(2)

    def leave(user):
        barrier.wait()
        return remove_member(client, user, team, user.username).status_code

    with ThreadPoolExecutor(2) as pool:
        statuses = sorted(pool.map(leave, [alice, bob]))

    assert statuses == [204, 409]
    assert len(team_names(client, alice) + team_names(client, bob)) == 1
