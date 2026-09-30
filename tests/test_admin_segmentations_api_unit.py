from httpx import AsyncClient

SEGMENTATIONS = "/api/admin/segmentations"


async def test_list_is_lightweight(client: AsyncClient) -> None:
    body = (await client.get(SEGMENTATIONS)).json()
    assert body["meta"] == {"total": 3, "page": 1, "per_page": 50}
    by_id = {row["segmentation_id"]: row for row in body["segmentations"]}
    assert by_id["Business"]["segment_count"] == 4 and by_id["Business"]["segments"] == []
    custom = (await client.get(SEGMENTATIONS, params={"product": "custom"})).json()
    assert [row["name"] for row in custom["segmentations"]] == ["Watchlist Q3"]
    searched = (await client.get(SEGMENTATIONS, params={"q": "casino"})).json()
    assert searched["meta"]["total"] == 1


async def test_segments_are_loaded_on_demand(client: AsyncClient) -> None:
    body = (await client.get(f"{SEGMENTATIONS}/Business/segments")).json()
    assert body["total"] == 4
    body = (await client.get(f"{SEGMENTATIONS}/Business/segments", params={"q": "prem"})).json()
    assert body == {"segments": [{"value": "34", "name": "Premium", "description": "Top decile by value"}], "total": 1}
    assert (await client.get(f"{SEGMENTATIONS}/Nope/segments")).status_code == 404


async def test_resolve_labels(client: AsyncClient) -> None:
    keys = ["Business__34", "Casino__vip_gold", "Nope__1", "malformed"]
    body = (await client.post(f"{SEGMENTATIONS}/resolve", json={"keys": keys})).json()
    labels = {item["key"]: item["label"] for item in body["items"]}
    assert labels == {
        "Business__34": "Business › Premium",
        "Casino__vip_gold": "Casino tier › VIP-Gold",
        "Nope__1": "Nope__1",
        "malformed": "malformed",
    }
    assert {row["segmentation_id"] for row in body["segmentations"]} == {"Business", "Casino"}


async def test_players_of_a_segmentation(client: AsyncClient) -> None:
    body = (await client.get(f"{SEGMENTATIONS}/Business/players", params={"segment": "34"})).json()
    assert body["segmentation"]["segment_count"] == 4
    assert {"10001", "10003"} <= {row["player_id"] for row in body["players"]}
    assert all(row["segment_name"] == "Premium" for row in body["players"])
    searched = (await client.get(f"{SEGMENTATIONS}/Business/players", params={"q": "1000"})).json()
    assert searched["meta"]["total"] >= 6


async def test_import_append_remove_delete(client: AsyncClient) -> None:
    csv_text = "player_id,segment,is_test\n20001,Gold,\n20002,Silver,\n20003,Gold,1\n20004,,\n"
    imported = await client.post(
        f"{SEGMENTATIONS}/import", json={"name": "Imported", "description": None, "csv": csv_text}
    )
    assert imported.status_code == 200, imported.text
    summary = imported.json()
    assert summary["product"] == "custom"
    assert (summary["segments_created"], summary["player_segments_created"]) == (2, 2)
    assert (summary["rows_total"], summary["skipped_test"], summary["skipped_invalid"]) == (4, 1, 1)
    seg_id = summary["segmentation_id"]

    players = (await client.get(f"{SEGMENTATIONS}/{seg_id}/players")).json()
    assert {row["player_id"]: row["segment_name"] for row in players["players"]} == {"20001": "Gold", "20002": "Silver"}

    appended = await client.post(
        f"{SEGMENTATIONS}/{seg_id}/players/import", json={"csv": "player_id,segment\n20005,Bronze\n20001,Gold\n"}
    )
    assert appended.status_code == 200, appended.text
    assert (appended.json()["segments_added"], appended.json()["player_segments_created"]) == (1, 1)
    values = (await client.get(f"{SEGMENTATIONS}/{seg_id}/segments")).json()
    assert [s["value"] for s in values["segments"]] == ["1", "2", "3"]

    removed = (await client.delete(f"{SEGMENTATIONS}/{seg_id}/players/20001/")).json()
    assert removed["deleted_player_segments"] == 1

    deleted = (await client.delete(f"{SEGMENTATIONS}/{seg_id}/")).json()
    assert deleted["deleted_player_segments"] == 2
    assert (await client.get(f"{SEGMENTATIONS}/{seg_id}/segments")).status_code == 404


async def test_seeded_segmentations_are_protected(client: AsyncClient) -> None:
    assert (await client.delete(f"{SEGMENTATIONS}/Business/")).status_code == 403
    bad = await client.post(f"{SEGMENTATIONS}/import", json={"name": "x", "csv": "player_id\n1\n"})
    assert bad.status_code == 400
