"""The checkers admin API, exercised the way cadmin's Alert Bot proxy calls it."""

from helpers import encode_filter
from httpx import ASGITransport, AsyncClient

CHECKERS = "/api/admin/checkers"
ROW_KEYS = {
    "id",
    "brand",
    "channel",
    "channels",
    "checker_code",
    "checker_name",
    "config",
    "description",
    "enabled",
    "frequency_minutes",
    "cron",
    "max_instances",
    "segments",
    "regions",
    "created_at",
    "updated_at",
}


def _new_row(**overrides):
    row = {
        "brand": "DEMO",
        "channel": "#demo-test",
        "channels": ["#demo-test"],
        "checker_code": "threshold_breach",
        "checker_name": "Threshold Breach 900 2h",
        "description": None,
        "enabled": True,
        "frequency_minutes": 5,
        "cron": None,
        "max_instances": 1,
        "config": {"monitoring_window_hours": 2, "threshold": 900},
        "segments": [],
        "regions": [],
    }
    row.update(overrides)
    return row


async def test_list_is_scoped_to_the_brand_header(client: AsyncClient) -> None:
    response = await client.get(CHECKERS)
    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {"total_results": 5, "per_page": 50, "page": 1, "total_pages": 1}
    assert body["warnings"] == []
    assert {row["brand"] for row in body["checkers"]} == {"DEMO"}
    assert set(body["checkers"][0]) == ROW_KEYS

    other = await client.get(CHECKERS, headers={"X-Brand": "acme"})
    assert {row["brand"] for row in other.json()["checkers"]} == {"ACME"}

    none = await client.get(CHECKERS, headers={"X-Brand": ""})
    assert none.json()["meta"]["total_results"] == 0


async def test_search_filter_as_cadmin_encodes_it(client: AsyncClient) -> None:
    token = encode_filter({"$or": [{"checker_name.icontains": "STUCK"}, {"checker_code.icontains": "STUCK"}]})
    body = (await client.get(CHECKERS, params={"filter": token})).json()
    assert [row["checker_name"] for row in body["checkers"]] == ["Status Stuck 120m EU"]


async def test_enabled_and_region_filters(client: AsyncClient) -> None:
    def query(region: str):
        return encode_filter(
            {"$and": [{"enabled": True}, {"$or": [{"regions.in": [region]}, {"regions.isnull": True}]}]}
        )

    eu = (await client.get(CHECKERS, params={"filter": query("EU")})).json()
    assert eu["meta"]["total_results"] == 4  # three ungated enabled rows + the EU-gated one
    latam = (await client.get(CHECKERS, params={"filter": query("LATAM")})).json()
    assert latam["meta"]["total_results"] == 3


async def test_ids_filter_and_pagination(client: AsyncClient) -> None:
    ids = [row["id"] for row in (await client.get(CHECKERS)).json()["checkers"]]
    picked = (await client.get(CHECKERS, params={"filter": encode_filter({"id.in": ids[:2]})})).json()
    assert {row["id"] for row in picked["checkers"]} == set(ids[:2])

    page = (await client.get(CHECKERS, params={"per_page": 2, "page": 2, "sort[]": "checker_name"})).json()
    assert len(page["checkers"]) == 2
    assert page["meta"] == {"total_results": 5, "per_page": 2, "page": 2, "total_pages": 3}

    bad = await client.get(CHECKERS, params={"filter": "not-base64!!"})
    assert bad.status_code == 400


async def test_codes_endpoint(client: AsyncClient) -> None:
    body = (await client.get(f"{CHECKERS}/codes")).json()
    assert {"code": "threshold_breach", "name": "Threshold Breach"} in body["codes"]
    assert len(body["codes"]) == 4


async def test_get_single_wraps_the_row(client: AsyncClient) -> None:
    first = (await client.get(CHECKERS)).json()["checkers"][0]
    body = (await client.get(f"{CHECKERS}/{first['id']}/")).json()
    assert body == {"checker": first, "warnings": []}
    assert (await client.get(f"{CHECKERS}/not-an-id/")).status_code == 404
    assert (await client.get(f"{CHECKERS}/{'0' * 24}/")).status_code == 404


async def test_create_as_cadmin_sends_it(client: AsyncClient) -> None:
    response = await client.post(f"{CHECKERS}/", json={"checker": _new_row()})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["warnings"] == []
    checker = body["checker"]
    assert len(checker["id"]) == 24
    assert checker["created_at"].endswith("Z") and checker["updated_at"] is None
    assert checker["channels"] == ["#demo-test"]
    assert (await client.get(CHECKERS)).json()["meta"]["total_results"] == 6


async def test_bulk_create(client: AsyncClient) -> None:
    rows = [_new_row(checker_name="Bulk A"), _new_row(checker_name="Bulk B")]
    response = await client.post(f"{CHECKERS}/", json={"checkers": rows})
    assert response.status_code == 201
    assert [row["checker_name"] for row in response.json()["checkers"]] == ["Bulk A", "Bulk B"]
    assert (await client.post(f"{CHECKERS}/", json={"nothing": 1})).status_code == 400


async def test_create_rejects_missing_required_knob(client: AsyncClient) -> None:
    response = await client.post(f"{CHECKERS}/", json={"checker": _new_row(config={"threshold": 1})})
    assert response.status_code == 400
    problems = response.json()["detail"]["details"]["config"]
    assert "monitoring_window_hours" in problems[0]


async def test_create_rejects_a_value_outside_its_bounds(client: AsyncClient) -> None:
    config = {"monitoring_window_hours": 500, "threshold": 1}
    response = await client.post(f"{CHECKERS}/", json={"checker": _new_row(config=config)})
    assert response.status_code == 400
    message = response.json()["detail"]["details"]["config"][0]
    assert "1 to 168" in message and "7 days" in message


async def test_create_rejects_unknown_code_and_duplicate_name(client: AsyncClient) -> None:
    unknown = await client.post(f"{CHECKERS}/", json={"checker": _new_row(checker_code="large_deposit")})
    assert unknown.status_code == 400
    assert "checker_code" in unknown.json()["detail"]["details"]

    duplicate = await client.post(f"{CHECKERS}/", json={"checker": _new_row(checker_name="Heartbeat")})
    assert duplicate.status_code == 400
    assert "checker_name" in duplicate.json()["detail"]["details"]


async def test_create_returns_warnings_without_rejecting(client: AsyncClient) -> None:
    config = {"monitoring_window_hours": 2, "threshold": 900, "check_vip_users": False, "check_non_vip_users": False}
    response = await client.post(f"{CHECKERS}/", json={"checker": _new_row(config=config)})
    assert response.status_code == 201
    assert any("nobody" in warning for warning in response.json()["warnings"])


async def test_update_as_cadmin_merges_the_full_record(client: AsyncClient) -> None:
    row = next(r for r in (await client.get(CHECKERS)).json()["checkers"] if r["checker_code"] == "threshold_breach")
    merged = {k: v for k, v in row.items() if k not in {"id", "created_at", "updated_at"}}
    merged["config"] = {**merged["config"], "threshold": 6000}
    merged["brand"] = "DEMO"
    response = await client.patch(f"{CHECKERS}/{row['id']}/", json=merged)
    assert response.status_code == 200, response.text
    checker = response.json()["checker"]
    assert checker["config"]["threshold"] == 6000
    assert checker["updated_at"] is not None
    assert checker["checker_name"] == row["checker_name"]

    wrong_brand = await client.patch(f"{CHECKERS}/{row['id']}/", json=merged, headers={"X-Brand": "ACME"})
    assert wrong_brand.status_code == 404


async def test_update_rejects_a_config_that_loses_a_knob(client: AsyncClient) -> None:
    row = next(r for r in (await client.get(CHECKERS)).json()["checkers"] if r["checker_code"] == "status_stuck")
    response = await client.patch(f"{CHECKERS}/{row['id']}/", json={"config": {"cache_ttl_hours": 1}})
    assert response.status_code == 400
    assert "pending_minutes" in response.json()["detail"]["details"]["config"][0]
    untouched = (await client.get(f"{CHECKERS}/{row['id']}/")).json()["checker"]
    assert untouched["config"] == row["config"]


async def test_update_with_channel_only_derives_channels(client: AsyncClient) -> None:
    row = (await client.get(CHECKERS)).json()["checkers"][0]
    response = await client.patch(f"{CHECKERS}/{row['id']}/", json={"channel": "#moved"})
    assert response.json()["checker"]["channels"] == ["#moved"]


async def test_delete_removes_the_row(client: AsyncClient) -> None:
    row = (await client.get(CHECKERS)).json()["checkers"][0]
    assert (await client.delete(f"{CHECKERS}/{row['id']}/")).status_code == 204
    assert (await client.get(f"{CHECKERS}/{row['id']}/")).status_code == 404
    assert (await client.delete(f"{CHECKERS}/", params={"filter": encode_filter({"enabled": True})})).status_code == 204
    assert (await client.get(CHECKERS)).json()["meta"]["total_results"] == 4


async def test_bearer_token_is_required(client: AsyncClient, seeded_store) -> None:
    wrong = await client.get(CHECKERS, headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anonymous:
        assert (await anonymous.get(CHECKERS)).status_code in (401, 403)  # FastAPI's HTTPBearer decides


async def test_healthcheck(client: AsyncClient) -> None:
    response = await client.get("/api/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"status": True, "mongo": True}
