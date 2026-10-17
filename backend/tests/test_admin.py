from tests.conftest import ADMIN_PASSWORD, login, unlock_admin


async def test_admin_routes_need_the_admin_password(client, make_user, admin_password_set):
    await make_user("ravi")
    await login(client, "ravi")

    response = await client.get("/api/v1/admin/users")

    assert response.status_code == 403
    assert response.json()["type"] == "urn:crm:problem:admin-session-required"


async def test_wrong_admin_password_then_lockout(client, make_user, admin_password_set, settings):
    await make_user("ravi")
    await login(client, "ravi")

    for _ in range(settings.admin_max_failed_attempts):
        assert (await unlock_admin(client, "wrong-password")).status_code == 401

    locked = await unlock_admin(client, ADMIN_PASSWORD)  # even the right one is refused now
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0


async def test_lockout_survives_logging_in_again(client, new_client, make_user, admin_password_set, settings):
    await make_user("ravi")
    await login(client, "ravi")
    for _ in range(settings.admin_max_failed_attempts):
        await unlock_admin(client, "wrong-password")

    fresh = await new_client()
    await login(fresh, "ravi")
    assert (await unlock_admin(fresh, ADMIN_PASSWORD)).status_code == 429


async def test_admin_password_not_configured(client, make_user):
    await make_user("ravi")
    await login(client, "ravi")

    status = (await client.get("/api/v1/admin/session")).json()
    assert status["password_configured"] is False
    assert (await unlock_admin(client)).status_code == 503


async def test_unlock_and_lock_admin(client, make_user, admin_password_set):
    await make_user("ravi")
    await login(client, "ravi")

    assert (await unlock_admin(client)).status_code == 204
    status = (await client.get("/api/v1/admin/session")).json()
    assert status["active"] is True and status["expires_at"]
    assert (await client.get("/api/v1/me")).json()["admin_active"] is True

    assert (await client.delete("/api/v1/admin/session")).status_code == 204
    assert (await client.get("/api/v1/admin/users")).status_code == 403


async def test_create_list_and_update_users(client, make_user, admin_password_set):
    await make_user("ravi")
    await login(client, "ravi")
    await unlock_admin(client)

    created = await client.post(
        "/api/v1/admin/users",
        json={
            "username": "anita",
            "display_name": "Anita Rao",
            "role": "Recruitment Executive",
            "initial_password": "initial-pass-1",
        },
    )
    assert created.status_code == 201
    assert created.headers["location"].endswith(f"/admin/users/{created.json()['id']}")

    duplicate = await client.post(
        "/api/v1/admin/users",
        json={"username": "ANITA", "display_name": "Other", "initial_password": "initial-pass-1"},
    )
    assert duplicate.status_code == 409

    names = [u["username"] for u in (await client.get("/api/v1/admin/users")).json()["items"]]
    assert set(names) == {"ravi", "anita"}

    updated = await client.patch(
        f"/api/v1/admin/users/{created.json()['id']}", json={"role": "Team Lead"}
    )
    assert updated.status_code == 200 and updated.json()["role"] == "Team Lead"


async def test_short_initial_password_is_rejected(client, make_user, admin_password_set):
    await make_user("ravi")
    await login(client, "ravi")
    await unlock_admin(client)

    response = await client.post(
        "/api/v1/admin/users",
        json={"username": "anita", "display_name": "Anita", "initial_password": "short"},
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "initial_password"


async def test_deactivating_a_user_logs_them_out(client, new_client, make_user, admin_password_set):
    ravi = await make_user("ravi")
    anita = await make_user("anita")
    victim = await new_client()
    await login(victim, "anita")
    assert (await victim.get("/api/v1/me")).status_code == 200

    await login(client, "ravi")
    await unlock_admin(client)
    response = await client.patch(f"/api/v1/admin/users/{anita.id}", json={"is_active": False})
    assert response.status_code == 200 and response.json()["is_active"] is False

    assert (await victim.get("/api/v1/me")).status_code == 401
    assert (await login(victim, "anita")).status_code == 401

    # And you cannot deactivate yourself.
    self_off = await client.patch(f"/api/v1/admin/users/{ravi.id}", json={"is_active": False})
    assert self_off.status_code == 409


async def test_change_admin_password(client, make_user, admin_password_set):
    await make_user("ravi")
    await login(client, "ravi")
    await unlock_admin(client)

    wrong = await client.put(
        "/api/v1/admin/password",
        json={"current_password": "nope-nope-nope", "new_password": "new-admin-pass-1"},
    )
    assert wrong.status_code == 401

    ok = await client.put(
        "/api/v1/admin/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "new-admin-pass-1"},
    )
    assert ok.status_code == 204

    await client.delete("/api/v1/admin/session")
    assert (await unlock_admin(client, ADMIN_PASSWORD)).status_code == 401
    assert (await unlock_admin(client, "new-admin-pass-1")).status_code == 204
