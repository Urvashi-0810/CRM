from tests.conftest import login


async def test_login_success_sets_http_only_cookie_and_returns_csrf(client, make_user):
    await make_user("priya", "Priya Shah", "Operations Lead")

    response = await login(client, "priya")

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["display_name"] == "Priya Shah"
    assert body["csrf_token"]
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


async def test_username_is_case_insensitive(client, make_user):
    await make_user("priya")
    assert (await login(client, "PRIYA")).status_code == 200


async def test_wrong_password_and_unknown_user_give_the_same_401(client, make_user):
    await make_user("priya")

    wrong = await login(client, "priya", "not-the-password")
    unknown = await login(client, "nobody", "not-the-password")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.headers["content-type"] == "application/problem+json"
    assert wrong.json()["type"] == unknown.json()["type"] == "urn:crm:problem:invalid-credentials"


async def test_deactivated_user_cannot_log_in(client, make_user):
    await make_user("old", active=False)
    assert (await login(client, "old")).status_code == 401


async def test_me_requires_login(client):
    response = await client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["type"] == "urn:crm:problem:not-authenticated"


async def test_me_returns_profile(client, make_user):
    await make_user("priya", "Priya Shah", "Operations Lead")
    await login(client, "priya")

    me = (await client.get("/api/v1/me")).json()

    assert me["display_name"] == "Priya Shah"
    assert me["role"] == "Operations Lead"
    assert me["admin_active"] is False
    assert me["pending_name_change"] is None


async def test_state_changing_request_without_csrf_token_is_rejected(client, make_user):
    await make_user("priya")
    await login(client, "priya")

    response = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"})

    assert response.status_code == 403
    assert response.json()["type"] == "urn:crm:problem:csrf-token-invalid"


async def test_logout_ends_the_session(client, make_user):
    await make_user("priya")
    await login(client, "priya")

    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    assert (await client.get("/api/v1/me")).status_code == 401


async def test_validation_errors_use_problem_format(client):
    response = await client.post("/api/v1/auth/login", json={"username": "x"})

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "urn:crm:problem:validation-error"
    assert any(e["field"] == "password" for e in body["errors"])


async def test_healthz(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
