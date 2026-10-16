from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server.services.geo import haversine_distance_km
from mcp_server.services.media_service import haversine_distance_km as service_haversine
from tests.conftest import competitor_media, write_competitor_file

from mcp_server.services.competitor_service import (
    CompetitorCatalog,
    CompetitorDataError,
    CompetitorIndex,
    attach_nearby_competitors,
    load_competitor_records,
)


def test_haversine_matches_known_equator_distance():
    distance = haversine_distance_km(0.0, 0.0, 0.0, 1.0)
    assert round(distance, 2) == 111.19
    assert service_haversine is haversine_distance_km


def test_geojson_coordinates_are_longitude_then_latitude(tmp_path: Path):
    write_competitor_file(
        tmp_path,
        [competitor_media("site-1", "Hoarding Andheri", 72.8777, 19.0760)],
    )
    records, skipped = load_competitor_records(tmp_path)
    assert skipped == 0
    assert len(records) == 1
    assert records[0].latitude == pytest.approx(19.0760)
    assert records[0].longitude == pytest.approx(72.8777)
    assert records[0].name == "Hoarding Andheri"
    assert records[0].media_type == "Hoarding"
    assert records[0].source == "Media Ant"
    assert records[0].location == "Andheri, Mumbai"


def test_string_coordinates_and_geos_fallback_are_normalized(tmp_path: Path):
    primary = competitor_media("string-coords", "String Coords", "72.80", "19.10")
    fallback = competitor_media(
        "fallback",
        "Fallback Coords",
        72.85,
        19.09,
        coordinates=[],
        include_geos=True,
        locality="",
    )
    fallback["locality"] = ""
    fallback["attributes"]["landmark"] = {"value": "Sahara Star"}
    write_competitor_file(tmp_path, [primary, fallback])

    records, skipped = load_competitor_records(tmp_path)
    by_id = {record.id: record for record in records}
    assert skipped == 0
    assert by_id["string-coords"].latitude == pytest.approx(19.10)
    assert by_id["string-coords"].longitude == pytest.approx(72.80)
    assert by_id["fallback"].latitude == pytest.approx(19.09)
    assert by_id["fallback"].longitude == pytest.approx(72.85)
    assert by_id["fallback"].location == "Sahara Star"


def test_invalid_coordinates_are_skipped_and_counted(tmp_path: Path):
    valid = competitor_media("ok", "Valid", 72.8, 19.1)
    malformed = competitor_media("bad", "Bad", None, None, coordinates=["north", "east"])
    out_of_range = competitor_media("oor", "Out of range", 72.8, 999)
    missing = {
        "_id": "missing",
        "name": "Missing",
        "location": {"coordinates": []},
        "attributes": {"mediaType": {"value": "Hoarding"}},
        "geos": [],
    }
    write_competitor_file(tmp_path, [valid, malformed, out_of_range, missing])

    records, skipped = load_competitor_records(tmp_path)
    assert [record.id for record in records] == ["ok"]
    assert skipped == 3


def test_empty_catalog_is_distinct_from_missing_source(tmp_path: Path):
    write_competitor_file(tmp_path, [])
    records, skipped = load_competitor_records(tmp_path)
    assert records == []
    assert skipped == 0
    result = CompetitorIndex(records, skipped_invalid=skipped).find_nearby(
        19.1, 72.8, radius_km=5, limit=5
    )
    assert result["status"] == "none_in_catalog"
    assert result["competitors"] == []
    assert result["catalog_size"] == 0

    with pytest.raises(CompetitorDataError, match="not found"):
        load_competitor_records(tmp_path / "missing-directory")


def test_malformed_json_raises_instead_of_returning_empty(tmp_path: Path):
    path = tmp_path / "media-ant" / "outdoor.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(CompetitorDataError, match="Failed to parse"):
        load_competitor_records(tmp_path)


def test_nearby_competitors_are_filtered_by_radius_and_sorted(tmp_path: Path):
    origin_lat, origin_lng = 19.0760, 72.8777
    near = competitor_media("near", "Near Hoarding", origin_lng + 0.002, origin_lat + 0.001)
    mid = competitor_media("mid", "Mid Hoarding", origin_lng + 0.01, origin_lat)
    far = competitor_media("far", "Far Hoarding", origin_lng + 0.2, origin_lat)
    write_competitor_file(tmp_path, [far, near, mid])
    records, skipped = load_competitor_records(tmp_path)
    result = CompetitorIndex(records, skipped_invalid=skipped).find_nearby(
        origin_lat,
        origin_lng,
        radius_km=5,
        limit=10,
        precision=2,
    )

    assert result["status"] == "ok"
    assert [row["id"] for row in result["competitors"]] == ["near", "mid"]
    distances = [row["distance_km"] for row in result["competitors"]]
    assert distances == sorted(distances)
    expected_near = round(
        haversine_distance_km(origin_lat, origin_lng, near_lat(records, "near"), near_lng(records, "near")),
        2,
    )
    assert result["competitors"][0]["distance_km"] == expected_near
    assert result["radius_km"] == 5
    assert "far" not in {row["id"] for row in result["competitors"]}


def test_media_type_and_brand_filters():
    records, _ = load_competitor_records_from_memory()
    index = CompetitorIndex(records, skipped_invalid=0)
    billboards = index.find_nearby(19.076, 72.8777, radius_km=5, limit=10, media_type="billboard")
    assert {row["media_type"] for row in billboards["competitors"]} == {"Hoarding"}
    plural = index.find_nearby(19.076, 72.8777, radius_km=5, limit=10, media_type="billboards")
    assert {row["media_type"] for row in plural["competitors"]} == {"Hoarding"}
    typo = index.find_nearby(19.076, 72.8777, radius_km=5, limit=10, media_type="billording")
    assert {row["id"] for row in typo["competitors"]} == {"hoarding"}
    shelters = index.find_nearby(19.076, 72.8777, radius_km=5, limit=10, media_type="Bus Shelter")
    assert [row["id"] for row in shelters["competitors"]] == ["shelter"]
    branded = index.find_nearby(19.076, 72.8777, radius_km=5, limit=10, brand="juhu")
    assert [row["id"] for row in branded["competitors"]] == ["shelter"]


def test_each_inventory_item_gets_its_own_competitor_list_and_can_share_one():
    shared = competitor_media("shared", "Shared Hoarding", 72.880, 19.0760, locality="Dadar, Mumbai")
    only_west = competitor_media("west-only", "West Hoarding", 72.845, 19.0760, locality="Bandra, Mumbai")
    only_east = competitor_media("east-only", "East Hoarding", 72.915, 19.0760, locality="Chembur, Mumbai")
    index = CompetitorIndex(load_pair(shared, only_west, only_east), skipped_invalid=0)

    west = {
        "id": "inv-west",
        "inventory_code": "MI1",
        "latitude": 19.0760,
        "longitude": 72.870,
        "media_type": "BillBoard",
        "location": "Dadar West",
    }
    east = {
        "id": "inv-east",
        "inventory_code": "MI2",
        "latitude": 19.0760,
        "longitude": 72.890,
        "media_type": "BillBoard",
        "location": "Dadar East",
    }
    no_coords = {"id": "inv-none", "inventory_code": "MI3", "latitude": None, "longitude": None}

    west_result = attach_nearby_competitors(west, index, radius_km=3, limit=5)
    east_result = attach_nearby_competitors(east, index, radius_km=3, limit=5)
    missing_result = attach_nearby_competitors(no_coords, index, radius_km=3, limit=5)

    west_ids = {row["id"] for row in west_result["nearby_competitors"]}
    east_ids = {row["id"] for row in east_result["nearby_competitors"]}
    assert "shared" in west_ids
    assert "shared" in east_ids
    assert "west-only" in west_ids
    assert "east-only" in east_ids
    assert west_result["nearby_competitors"] is not east_result["nearby_competitors"]
    assert {row["id"] for row in west_result["nearby_competitors"]} != {
        row["id"] for row in east_result["nearby_competitors"]
    }
    assert missing_result["nearby_competitors"] == []
    assert missing_result["competitor_search"]["status"] == "skipped_missing_coordinates"
    assert "latitude and longitude" in missing_result["competitor_search"]["message"]


def test_catalog_reloads_when_source_changes_and_caches_until_then(tmp_path: Path):
    path = write_competitor_file(
        tmp_path,
        [competitor_media("first", "First", 72.88, 19.08)],
    )
    catalog = CompetitorCatalog()
    first = catalog.get(tmp_path, ttl_seconds=3600)
    again = catalog.get(tmp_path, ttl_seconds=3600)
    assert again is first
    assert first.catalog_size == 1

    path.write_text(json.dumps({"medias": []}), encoding="utf-8")
    refreshed = catalog.get(tmp_path, ttl_seconds=3600)
    assert refreshed is not first
    assert refreshed.catalog_size == 0
    assert refreshed.find_nearby(19.08, 72.88, radius_km=5, limit=5)["status"] == "none_in_catalog"


def test_shipped_media_ant_export_normalizes_real_coordinates():
    root = Path(__file__).resolve().parents[1] / "competitor"
    export = root / "media-ant" / "outdoor.json"
    if not export.exists():
        pytest.skip("competitor export is not present")
    records, skipped = load_competitor_records(root)
    assert records
    assert all(-90.0 <= record.latitude <= 90.0 for record in records)
    assert all(-180.0 <= record.longitude <= 180.0 for record in records)
    assert any(record.media_type == "Hoarding" for record in records)
    assert skipped >= 0


def near_lat(records, record_id: str) -> float:
    return next(record.latitude for record in records if record.id == record_id)


def near_lng(records, record_id: str) -> float:
    return next(record.longitude for record in records if record.id == record_id)


def load_competitor_records_from_memory():
    from mcp_server.services.competitor_service import normalize_media_ant_record

    rows = [
        competitor_media("hoarding", "Dadar Hoarding", 72.8777, 19.0760, media_type="Hoarding", locality="Dadar, Mumbai"),
        competitor_media("shelter", "Juhu Shelter", 72.8780, 19.0762, media_type="Bus Shelter", locality="Juhu, Mumbai"),
    ]
    records = []
    skipped = 0
    for row in rows:
        record = normalize_media_ant_record(row, source="Media Ant")
        if record is None:
            skipped += 1
        else:
            records.append(record)
    return records, skipped


def load_pair(*rows: dict):
    from mcp_server.services.competitor_service import normalize_media_ant_record

    records = []
    for row in rows:
        normalized = normalize_media_ant_record(row, source="Media Ant")
        assert normalized is not None
        records.append(normalized)
    return records
