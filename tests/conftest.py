from __future__ import annotations

import json
import os
from pathlib import Path

# OAuth route tests expect this issuer. Environment variables override .env.
os.environ["MCP_PUBLIC_URL"] = "https://mcp.wrap2earn.test"


def write_competitor_file(directory: Path, medias: list[dict], relative: str = "media-ant/outdoor.json") -> Path:
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"medias": medias}), encoding="utf-8")
    return path


def competitor_media(
    record_id: str,
    name: str,
    longitude: float | str | None,
    latitude: float | str | None,
    *,
    media_type: str = "Hoarding",
    locality: str = "Andheri, Mumbai",
    minimum_billing: int | None = 25000,
    coordinates: list | None = None,
    include_geos: bool = False,
) -> dict:
    if coordinates is None and longitude is not None and latitude is not None:
        coordinates = [longitude, latitude]
    record = {
        "_id": record_id,
        "name": name,
        "locality": locality,
        "minimumBilling": minimum_billing,
        "location": {"type": "Point", "coordinates": coordinates if coordinates is not None else []},
        "attributes": {
            "mediaType": {"value": media_type},
            "landmark": {"value": locality},
        },
    }
    if include_geos and latitude is not None and longitude is not None:
        record["geos"] = [
            {
                "formatted_address": f"{locality}, India",
                "geometry": {"location": {"lat": latitude, "lng": longitude}},
            }
        ]
    return record
