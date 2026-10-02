import re

import pytest

from app.api import create_app

PUBLIC = {("GET", "/health"), ("POST", "/users")}


def protected_routes() -> list[tuple[str, str]]:
    """Every documented route not explicitly public, so a new route can't silently skip auth."""
    paths = create_app(":memory:").openapi()["paths"]
    routes = {
        (method.upper(), re.sub(r"\{[^}]+\}", "1", path))
        for path, operations in paths.items()
        for method in operations
    }
    return sorted(routes - PUBLIC)


BAD_AUTH = {
    "missing": {},
    "unknown token": {"Authorization": "Bearer not-a-real-token"},
    "wrong scheme": {"Authorization": "Basic YWxpY2U6c2VjcmV0"},
}


@pytest.mark.parametrize(("method", "path"), protected_routes())
@pytest.mark.parametrize("headers", BAD_AUTH.values(), ids=BAD_AUTH.keys())
def test_protected_routes_require_a_valid_token(client, method, path, headers):
    response = client.request(method, path, headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
