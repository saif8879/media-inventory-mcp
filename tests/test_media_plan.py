from __future__ import annotations

import pytest

from mcp_server.services.competitor_service import CompetitorIndex, normalize_media_ant_record
from mcp_server.tools.generate_media_plan import _competitor_type
from mcp_server.services.media_plan_service import MediaPlanService, select_inventory_within_budget
from tests.conftest import competitor_media


def inventory(
    code: str,
    cost: float | None,
    reach: int | None,
    *,
    latitude: float | None = 19.076,
    longitude: float | None = 72.8777,
    media_type: str = "BillBoard",
) -> dict:
    return {
        "id": f"uuid-{code}",
        "inventory_code": code,
        "city": "Mumbai",
        "area": "Dadar",
        "location": f"{code} location",
        "media_type": media_type,
        "latitude": latitude,
        "longitude": longitude,
        "display_cost": None,
        "printing_cost": None,
        "installation_cost": None,
        "total_cost": cost,
        "admavin": {"reach": reach, "ots": None} if reach is not None else None,
        "media_owner": "Owner",
    }


def test_billboard_plan_keeps_every_nearby_competitor_type():
    assert _competitor_type("", "billboard") == ""
    assert _competitor_type("billboards", "billording") == ""
    assert _competitor_type("hoarding", "billboard") == ""
    assert _competitor_type("bus shelter", "billboard") == "bus shelter"
    assert _competitor_type("", "gantry") == "gantry"
    assert _competitor_type("any", "gantry") == ""


def test_sites_with_competitors_are_chosen_before_a_higher_reach_site():
    with_competitors = inventory("MI10", 100000, 5)
    with_competitors["nearby_competitors"] = [{"id": "hoarding-1", "distance_km": 0.4}]
    higher_reach = inventory("MI11", 100000, 900)
    chosen = select_inventory_within_budget(
        [higher_reach, with_competitors],
        budget=100000,
        max_sites=1,
    )
    assert [item["inventory_code"] for item in chosen["selected"]] == ["MI10"]


def test_budget_sums_every_selected_site_and_skips_missing_prices():
    chosen = select_inventory_within_budget(
        [
            inventory("MI1", 150000, 10),
            inventory("MI2", 100000, 40),
            inventory("MI3", None, 100),
            inventory("MI4", 40000, 5),
        ],
        budget=400000,
        max_sites=10,
    )
    assert [item["inventory_code"] for item in chosen["selected"]] == ["MI2", "MI1", "MI4"]
    assert chosen["estimated_spend"] == 290000
    assert chosen["estimated_spend"] != chosen["selected"][0]["estimated_cost"]
    assert chosen["estimated_spend"] == sum(item["estimated_cost"] for item in chosen["selected"])
    assert chosen["remaining_budget"] == 110000
    assert [item["inventory_code"] for item in chosen["excluded_unpriced"]] == ["MI3"]


def test_budget_does_not_select_a_site_that_exceeds_remaining_funds():
    chosen = select_inventory_within_budget(
        [
            inventory("MI2", 100000, 40),
            inventory("MI1", 250000, 10),
            inventory("MI9", 500000, 1),
        ],
        budget=400000,
        max_sites=10,
    )
    assert [item["inventory_code"] for item in chosen["selected"]] == ["MI2", "MI1"]
    assert chosen["estimated_spend"] == 350000
    assert chosen["remaining_budget"] == 50000
    assert [item["inventory_code"] for item in chosen["excluded_unpriced"]] == []
    assert chosen["omitted_for_budget"] == 1


def test_missing_price_is_reported_separately_from_a_fitting_plan():
    chosen = select_inventory_within_budget(
        [inventory("MI3", None, 100), inventory("MI8", 0, 50)],
        budget=200000,
        max_sites=5,
    )
    assert chosen["selected"] == []
    assert chosen["estimated_spend"] == 0
    assert chosen["remaining_budget"] == 200000
    assert {item["inventory_code"] for item in chosen["excluded_unpriced"]} == {"MI3", "MI8"}
    assert all(item["price_status"] == "missing" for item in chosen["excluded_unpriced"])


def test_partial_component_prices_are_used_and_flagged():
    item = inventory("MI5", None, 12)
    item["display_cost"] = 70000
    item["printing_cost"] = 5000
    item["installation_cost"] = None
    chosen = select_inventory_within_budget([item], budget=100000, max_sites=5)
    assert chosen["selected"][0]["estimated_cost"] == 75000
    assert chosen["selected"][0]["price_status"] == "partial_components"
    assert chosen["estimated_spend"] == 75000


@pytest.mark.asyncio
async def test_media_plan_attaches_a_competitor_list_to_every_recommendation():
    shared = normalize_media_ant_record(
        competitor_media("shared", "Shared Hoarding", 72.8777, 19.0760, media_type="Hoarding"),
        source="Media Ant",
    )
    east = normalize_media_ant_record(
        competitor_media("east-only", "East Hoarding", 72.91, 19.08, media_type="Hoarding", locality="Chembur, Mumbai"),
        source="Media Ant",
    )
    assert shared is not None and east is not None
    index = CompetitorIndex([shared, east], skipped_invalid=0)

    class FakeInventory:
        def __init__(self):
            self.calls: list[dict] = []

        async def search(self, **kwargs):
            self.calls.append(kwargs)
            items = [
                inventory("MI1", 250000, 10, latitude=19.0760, longitude=72.8777),
                inventory("MI2", 100000, 30, latitude=19.0800, longitude=72.9100),
                inventory("MI3", None, 90),
            ]
            offset = kwargs["offset"]
            limit = kwargs["limit"]
            return items[offset : offset + limit], len(items)

    inventory_service = FakeInventory()
    plan = await MediaPlanService(inventory_service, index).generate(
        brand="Croma",
        city="Mumbai",
        budget=400000,
        media_type="billboard",
        radius_km=5,
        max_competitors=5,
        max_candidates=10,
        max_sites=10,
    )

    assert inventory_service.calls[0]["city"] == "Mumbai"
    assert inventory_service.calls[0]["media_type_mode"] == "synonym"
    assert len(inventory_service.calls) == 1
    assert plan["campaign"]["brand"] == "Croma"
    assert plan["campaign"]["budget"] == 400000
    recommended = plan["recommended_inventory"]
    assert [item["inventory_code"] for item in recommended] == ["MI2", "MI1"]
    assert all("nearby_competitors" in item for item in recommended)
    assert plan["budget_summary"]["estimated_spend"] == 350000
    assert plan["budget_summary"]["remaining_budget"] == 50000
    assert plan["budget_summary"]["estimated_spend"] == sum(item["estimated_cost"] for item in recommended)
    competitor_ids = [{row["id"] for row in item["nearby_competitors"]} for item in recommended]
    assert "shared" in competitor_ids[1]
    assert all(item["competitor_search"]["status"] == "ok" for item in recommended)
    assert any(item["inventory_code"] == "MI3" for item in plan["excluded_inventory"])
    assert "reach" in recommended[0]["selection_reason"].lower() or "cost" in recommended[0]["selection_reason"].lower()


@pytest.mark.asyncio
async def test_media_plan_explains_missing_coordinates_without_inventing_competitors():
    index = CompetitorIndex([], skipped_invalid=0)

    class FakeInventory:
        async def search(self, **kwargs):
            return [inventory("MI7", 50000, None, latitude=None, longitude=None)], 1

    plan = await MediaPlanService(FakeInventory(), index).generate(
        brand="Nike",
        city="Delhi",
        budget=100000,
        media_type="",
        radius_km=5,
        max_competitors=3,
        max_candidates=10,
        max_sites=5,
    )
    item = plan["recommended_inventory"][0]
    assert item["nearby_competitors"] == []
    assert item["competitor_search"]["status"] == "skipped_missing_coordinates"
    assert plan["budget_summary"]["estimated_spend"] == 50000
