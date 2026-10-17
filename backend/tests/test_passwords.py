from tests.conftest import USER_PASSWORD, login, unlock_admin


async def test_change_own_password_logs_out_other_sessions(client, new_client, make_user):
    await make_user("priya")
    other = await new_client()
    await login(other, "priya")
    await login(client, "priya")

    response = await client.put(
        "/api/v1/me/password",
        json={"current_password": USER_PASSWORD, "new_password": "brand-new"},
    )

    assert response.status_code == 204
    assert (await client.get("/api/v1/me")).status_code == 200  # this browser stays in
    assert (await other.get("/api/v1/me")).status_code == 401  # the other is logged out
    fresh = await new_client()
    assert (await login(fresh, "priya", USER_PASSWORD)).status_code == 401
    assert (await login(fresh, "priya", "brand-new")).status_code == 200


async def test_change_password_needs_the_right_current_password(client, make_user):
    await make_user("priya")
    await login(client, "priya")

    response = await client.put(
        "/api/v1/me/password", json={"current_password": "wrong-one", "new_password": "brand-new"}
    )
    assert response.status_code == 401
    assert response.json()["type"] == "urn:crm:problem:current-password-wrong"


async def test_new_password_minimum_six_characters(client, make_user):
    await make_user("priya")
    await login(client, "priya")

    short = await client.put(
        "/api/v1/me/password", json={"current_password": USER_PASSWORD, "new_password": "12345"}
    )
    assert short.status_code == 422
    assert short.json()["errors"][0]["field"] == "new_password"

    six = await client.put(
        "/api/v1/me/password", json={"current_password": USER_PASSWORD, "new_password": "123456"}
    )
    assert six.status_code == 204


async def test_new_password_must_differ(client, make_user):
    await make_user("priya")
    await login(client, "priya")
    response = await client.put(
        "/api/v1/me/password",
        json={"current_password": USER_PASSWORD, "new_password": USER_PASSWORD},
    )
    assert response.status_code == 422


async def test_admin_resets_forgotten_password(client, new_client, make_user, admin_password_set):
    await make_user("ravi")
    anita = await make_user("anita")
    anita_browser = await new_client()
    await login(anita_browser, "anita")

    await login(client, "ravi")
    await unlock_admin(client)
    response = await client.put(
        f"/api/v1/admin/users/{anita.id}/password", json={"new_password": "reset-123"}
    )

    assert response.status_code == 204
    assert (await anita_browser.get("/api/v1/me")).status_code == 401  # old session ended
    assert (await login(anita_browser, "anita", USER_PASSWORD)).status_code == 401
    assert (await login(anita_browser, "anita", "reset-123")).status_code == 200


async def test_password_reset_needs_admin_and_valid_input(client, make_user, admin_password_set):
    await make_user("ravi")
    anita = await make_user("anita")
    await login(client, "ravi")

    no_admin = await client.put(
        f"/api/v1/admin/users/{anita.id}/password", json={"new_password": "reset-123"}
    )
    assert no_admin.status_code == 403

    await unlock_admin(client)
    short = await client.put(f"/api/v1/admin/users/{anita.id}/password", json={"new_password": "12"})
    assert short.status_code == 422
    missing = await client.put("/api/v1/admin/users/9999/password", json={"new_password": "reset-123"})
    assert missing.status_code == 404
