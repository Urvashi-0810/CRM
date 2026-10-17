from tests.conftest import login, unlock_admin


async def test_full_name_change_flow(client, new_client, make_user, admin_password_set):
    await make_user("priya", "Priya Shah")
    await make_user("ravi", "Ravi Kumar")

    # Priya asks for a new name.
    await login(client, "priya")
    created = await client.post(
        "/api/v1/me/name-change-requests", json={"requested_name": "  Priya S. Mehta "}
    )
    assert created.status_code == 201
    assert created.json()["requested_name"] == "Priya S. Mehta"  # trimmed
    assert (await client.get("/api/v1/me")).json()["pending_name_change"]["status"] == "pending"

    # Name is unchanged until approved.
    assert (await client.get("/api/v1/me")).json()["display_name"] == "Priya Shah"

    # Ravi unlocks admin and approves it.
    admin = await new_client()
    await login(admin, "ravi")
    assert (await unlock_admin(admin)).status_code == 204
    pending = (await admin.get("/api/v1/admin/name-change-requests?status=pending")).json()["items"]
    assert len(pending) == 1 and pending[0]["current_name"] == "Priya Shah"

    approved = await admin.post(f"/api/v1/admin/name-change-requests/{pending[0]['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    me = (await client.get("/api/v1/me")).json()
    assert me["display_name"] == "Priya S. Mehta"
    assert me["pending_name_change"] is None

    # Reviewing it again is a state conflict.
    again = await admin.post(f"/api/v1/admin/name-change-requests/{pending[0]['id']}/reject")
    assert again.status_code == 409


async def test_only_one_pending_request_at_a_time(client, make_user):
    await make_user("priya", "Priya Shah")
    await login(client, "priya")

    first = await client.post("/api/v1/me/name-change-requests", json={"requested_name": "A Name"})
    second = await client.post("/api/v1/me/name-change-requests", json={"requested_name": "B Name"})

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["type"] == "urn:crm:problem:name-change-already-pending"


async def test_requesting_the_same_name_is_rejected(client, make_user):
    await make_user("priya", "Priya Shah")
    await login(client, "priya")

    response = await client.post(
        "/api/v1/me/name-change-requests", json={"requested_name": "Priya Shah"}
    )
    assert response.status_code == 422


async def test_rejected_request_keeps_old_name_and_allows_a_new_request(
    client, new_client, make_user, admin_password_set
):
    await make_user("priya", "Priya Shah")
    await make_user("ravi")
    await login(client, "priya")
    req = (await client.post("/api/v1/me/name-change-requests", json={"requested_name": "X Y"})).json()

    admin = await new_client()
    await login(admin, "ravi")
    await unlock_admin(admin)
    assert (await admin.post(f"/api/v1/admin/name-change-requests/{req['id']}/reject")).status_code == 200

    assert (await client.get("/api/v1/me")).json()["display_name"] == "Priya Shah"
    history = (await client.get("/api/v1/me/name-change-requests")).json()["items"]
    assert [r["status"] for r in history] == ["rejected"]
    again = await client.post("/api/v1/me/name-change-requests", json={"requested_name": "Z W"})
    assert again.status_code == 201
