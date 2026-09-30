from httpx import AsyncClient

SETTINGS = "/api/admin/settings"


async def test_seeded_defaults(client: AsyncClient) -> None:
    body = (await client.get(SETTINGS)).json()
    assert body["regions"] == ["EU", "LATAM", "ASIA"]
    assert body["default_region"] == "EU"
    assert body["min_win_to_store_eur"] is None
    assert body["crypto_address_max_players_to_publish"] == 10


async def test_brand_header_is_required(client: AsyncClient) -> None:
    assert (await client.get(SETTINGS, headers={"X-Brand": ""})).status_code == 400
    assert (await client.get(SETTINGS, headers={"X-Brand": "NOPE"})).status_code == 400


async def test_default_region_must_be_in_the_catalogue(client: AsyncClient) -> None:
    rejected = await client.put(SETTINGS, json={"default_region": "MARS"})
    assert rejected.status_code == 400
    shrunk = await client.put(SETTINGS, json={"regions": ["LATAM"]})
    assert shrunk.status_code == 400  # would orphan the current default
    moved = await client.put(SETTINGS, json={"regions": ["LATAM"], "default_region": "LATAM"})
    assert moved.status_code == 200
    assert moved.json()["default_region"] == "LATAM"


async def test_partial_update_and_always_defaulted_maxima(client: AsyncClient) -> None:
    body = (await client.put(SETTINGS, json={"min_win_to_store_eur": 12.5})).json()
    assert body["min_win_to_store_eur"] == 12.5 and body["regions"] == ["EU", "LATAM", "ASIA"]
    body = (await client.put(SETTINGS, json={"crypto_address_max_players_to_publish": None})).json()
    assert body["crypto_address_max_players_to_publish"] == 10
    body = (await client.put(SETTINGS, json={"crypto_address_exclude_entity_tags_regex": "("})).json()
    assert "regular expression" in body["detail"]
