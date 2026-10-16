from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_server.services.geo import (
    bounding_box_deltas,
    haversine_distance_km,
    media_type_matches,
    parse_coordinate,
    valid_lat_lng,
)

logger = logging.getLogger("mcp_server.services.competitor")

CELL_DEGREES = 0.1
_MISSING_COORDINATES = (
    "Nearby competitor matching is unavailable because this inventory item "
    "has no valid latitude and longitude."
)


class CompetitorDataError(Exception):
    """The competitor data source could not be read or parsed."""


@dataclass(frozen=True)
class CompetitorRecord:
    id: str
    name: str
    media_type: str | None
    location: str | None
    latitude: float
    longitude: float
    source: str
    minimum_billing: float | None
    locality: str | None


def default_competitor_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "competitor"


def load_competitor_records(directory: Path) -> tuple[list[CompetitorRecord], int]:
    """Load and normalize competitor JSON exports.

    Returns valid records and the count of rows skipped for missing or invalid
    coordinates. A readable file with an empty medias list is a successful load.
    Missing directories, unreadable files, and malformed JSON raise
    CompetitorDataError.
    """
    root = Path(directory)
    files = _json_files(root)
    records: list[CompetitorRecord] = []
    skipped = 0
    seen: set[tuple[str, str]] = set()
    for path in files:
        payload = _read_json(path)
        source = _source_name(path, root)
        for media in _extract_medias(payload, path):
            if not isinstance(media, dict):
                skipped += 1
                continue
            normalized = normalize_media_ant_record(media, source=source)
            if normalized is None:
                skipped += 1
                continue
            key = (normalized.source, normalized.id)
            if key in seen:
                continue
            seen.add(key)
            records.append(normalized)
    logger.info(
        "competitor_records_normalized",
        extra={"records": len(records), "skipped_invalid_coordinates": skipped, "files": len(files)},
    )
    return records, skipped


def normalize_media_ant_record(media: dict[str, Any], source: str) -> CompetitorRecord | None:
    """Map one Media Ant outdoor object into the internal competitor record."""
    if not isinstance(media, dict):
        return None
    coordinates = _extract_coordinates(media)
    if coordinates is None:
        return None
    latitude, longitude = coordinates
    record_id = str(media.get("_id") or media.get("id") or "").strip()
    raw_name = media.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not record_id and not name:
        return None
    if not record_id:
        record_id = name
    if not name:
        name = record_id
    locality = media.get("locality")
    locality_text = locality.strip() if isinstance(locality, str) and locality.strip() else None
    billing = parse_coordinate(media.get("minimumBilling"))
    if billing is not None and billing < 0:
        billing = None
    return CompetitorRecord(
        id=record_id,
        name=name,
        media_type=_media_type(media),
        location=_location_text(media),
        latitude=latitude,
        longitude=longitude,
        source=source,
        minimum_billing=billing,
        locality=locality_text,
    )


class CompetitorIndex:
    """In-memory competitor locations with a grid pre-filter before Haversine."""

    def __init__(self, records: list[CompetitorRecord], skipped_invalid: int = 0) -> None:
        self.records = list(records)
        self.skipped_invalid = skipped_invalid
        self._cells: dict[tuple[int, int], list[CompetitorRecord]] = {}
        for record in self.records:
            self._cells.setdefault(_cell(record.latitude, record.longitude), []).append(record)

    @property
    def catalog_size(self) -> int:
        return len(self.records)

    def find_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        limit: int,
        media_type: str | None = None,
        brand: str | None = None,
        precision: int = 2,
    ) -> dict[str, Any]:
        pair = valid_lat_lng(latitude, longitude)
        if pair is None:
            raise ValueError("latitude and longitude must be valid coordinates")
        if not math.isfinite(radius_km) or radius_km <= 0:
            raise ValueError("radius_km must be greater than 0")
        if limit < 1:
            raise ValueError("limit must be at least 1")
        lat, lng = pair
        places = max(0, int(precision))
        if self.catalog_size == 0:
            return _match_payload(
                status="none_in_catalog",
                radius_km=radius_km,
                competitors=[],
                catalog_size=0,
                skipped_invalid=self.skipped_invalid,
                message=(
                    "Competitor data loaded successfully but contains no records with valid coordinates."
                ),
            )

        lat_delta, lng_delta = bounding_box_deltas(lat, radius_km)
        min_lat, max_lat = lat - lat_delta, lat + lat_delta
        min_lng, max_lng = lng - lng_delta, lng + lng_delta
        brand_text = brand.strip().casefold() if isinstance(brand, str) else ""
        matches: list[tuple[float, CompetitorRecord]] = []
        for cell in _cells_covering(min_lat, max_lat, min_lng, max_lng):
            for record in self._cells.get(cell, []):
                if not (min_lat <= record.latitude <= max_lat and min_lng <= record.longitude <= max_lng):
                    continue
                if not media_type_matches(media_type, record.media_type):
                    continue
                if brand_text and not _brand_matches(record, brand_text):
                    continue
                distance = haversine_distance_km(lat, lng, record.latitude, record.longitude)
                if distance <= radius_km:
                    matches.append((distance, record))

        matches.sort(key=lambda item: (item[0], item[1].id))
        competitors = [
            _serialize_competitor(record, distance, places, radius_km)
            for distance, record in matches[:limit]
        ]
        if competitors:
            status = "ok"
            message = f"Found {len(competitors)} competitor placements within {radius_km:g} km."
        else:
            status = "none_in_radius"
            message = f"No competitor media found within {radius_km:g} km."
        return _match_payload(
            status=status,
            radius_km=radius_km,
            competitors=competitors,
            catalog_size=self.catalog_size,
            skipped_invalid=self.skipped_invalid,
            message=message,
        )


def attach_nearby_competitors(
    item: dict[str, Any],
    index: CompetitorIndex,
    *,
    radius_km: float,
    limit: int,
    media_type: str = "",
    brand: str = "",
    precision: int = 2,
) -> dict[str, Any]:
    """Return a copy of an inventory item with its own nearby competitor list."""
    enriched = dict(item)
    pair = valid_lat_lng(item.get("latitude"), item.get("longitude"))
    if pair is None:
        enriched["nearby_competitors"] = []
        enriched["competitor_search"] = {
            "status": "skipped_missing_coordinates",
            "radius_km": radius_km,
            "message": _MISSING_COORDINATES,
        }
        warnings = list(enriched.get("warnings") or [])
        warnings.append(_MISSING_COORDINATES)
        enriched["warnings"] = warnings
        return enriched

    result = index.find_nearby(
        pair[0],
        pair[1],
        radius_km=radius_km,
        limit=limit,
        media_type=media_type or None,
        brand=brand or None,
        precision=precision,
    )
    enriched["nearby_competitors"] = result["competitors"]
    enriched["competitor_search"] = {
        "status": result["status"],
        "radius_km": result["radius_km"],
        "catalog_size": result["catalog_size"],
        "message": result["message"],
    }
    return enriched


class CompetitorCatalog:
    """Process-local cache invalidated by file signature and TTL."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._index: CompetitorIndex | None = None
        self._signature: tuple | None = None
        self._loaded_at = 0.0

    def get(self, directory: Path, ttl_seconds: float) -> CompetitorIndex:
        root = Path(directory)
        signature = _directory_signature(root)
        now = time.monotonic()
        with self._lock:
            if self._is_fresh(signature, now, ttl_seconds):
                assert self._index is not None
                return self._index
        records, skipped = load_competitor_records(root)
        index = CompetitorIndex(records, skipped_invalid=skipped)
        with self._lock:
            self._index = index
            self._signature = signature
            self._loaded_at = time.monotonic()
            return self._index

    def _is_fresh(self, signature: tuple, now: float, ttl_seconds: float) -> bool:
        return (
            self._index is not None
            and self._signature == signature
            and ttl_seconds > 0
            and (now - self._loaded_at) < ttl_seconds
        )


_catalog = CompetitorCatalog()


def get_competitor_index(
    directory: Path | None = None,
    ttl_seconds: float | None = None,
) -> CompetitorIndex:
    from mcp_server.config import get_settings

    settings = get_settings()
    if directory is None:
        configured = settings.competitor_data_dir.strip()
        if not configured:
            directory = default_competitor_directory()
        else:
            directory = Path(configured)
            if not directory.is_absolute():
                directory = default_competitor_directory().parent / directory
    if ttl_seconds is None:
        ttl_seconds = settings.competitor_cache_ttl_seconds
    return _catalog.get(directory, ttl_seconds)


def reset_competitor_catalog() -> None:
    global _catalog
    _catalog = CompetitorCatalog()


def _json_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise CompetitorDataError(f"Competitor data directory not found: {directory}")
    files = sorted(path for path in directory.rglob("*.json") if path.is_file())
    if not files:
        raise CompetitorDataError(f"No competitor JSON files found in {directory}")
    return files


def _directory_signature(directory: Path) -> tuple:
    files = _json_files(directory)
    return tuple(
        (str(path.relative_to(directory)), path.stat().st_mtime_ns, path.stat().st_size)
        for path in files
    )


def _read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CompetitorDataError(f"Competitor data file could not be read: {path}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CompetitorDataError(f"Failed to parse competitor data file {path}: {exc}") from exc


def _extract_medias(payload: Any, path: Path) -> list[Any]:
    if isinstance(payload, dict) and isinstance(payload.get("medias"), list):
        return payload["medias"]
    if isinstance(payload, list):
        return payload
    raise CompetitorDataError(
        f"Failed to parse competitor data file {path}: expected an object with a medias list"
    )


def _source_name(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    folder = relative.parts[0] if len(relative.parts) > 1 else path.parent.name
    return folder.replace("-", " ").replace("_", " ").title()


def _extract_coordinates(media: dict[str, Any]) -> tuple[float, float] | None:
    # Media Ant stores GeoJSON order: [longitude, latitude].
    location = media.get("location") if isinstance(media.get("location"), dict) else {}
    coordinates = location.get("coordinates") if isinstance(location, dict) else None
    if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
        pair = valid_lat_lng(coordinates[1], coordinates[0])
        if pair is not None:
            return pair
    geos = media.get("geos")
    if isinstance(geos, list) and geos and isinstance(geos[0], dict):
        point = ((geos[0].get("geometry") or {}).get("location") or {})
        if isinstance(point, dict):
            return valid_lat_lng(point.get("lat"), point.get("lng"))
    return None


def _media_type(media: dict[str, Any]) -> str | None:
    attributes = media.get("attributes")
    if not isinstance(attributes, dict):
        return None
    raw = attributes.get("mediaType")
    if isinstance(raw, dict):
        value = raw.get("value")
    else:
        value = raw
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _location_text(media: dict[str, Any]) -> str | None:
    locality = media.get("locality")
    if isinstance(locality, str) and locality.strip():
        return locality.strip()
    attributes = media.get("attributes") if isinstance(media.get("attributes"), dict) else {}
    landmark = attributes.get("landmark") if isinstance(attributes, dict) else None
    if isinstance(landmark, dict):
        value = landmark.get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    elif isinstance(landmark, str) and landmark.strip():
        return landmark.strip()
    geos = media.get("geos")
    if isinstance(geos, list) and geos and isinstance(geos[0], dict):
        formatted = geos[0].get("formatted_address")
        if isinstance(formatted, str) and formatted.strip():
            return formatted.strip()
    return None


def _brand_matches(record: CompetitorRecord, brand_text: str) -> bool:
    haystacks = (
        record.name,
        record.locality,
        record.location,
        record.source,
        record.media_type,
    )
    return any(brand_text in (value or "").casefold() for value in haystacks)


def _serialize_competitor(
    record: CompetitorRecord,
    distance_km: float,
    precision: int,
    radius_km: float,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "competitor_name": record.name,
        "source": record.source,
        "media_type": record.media_type,
        "location": record.location,
        "latitude": record.latitude,
        "longitude": record.longitude,
        "distance_km": round(distance_km, precision),
        "radius_km": radius_km,
        "minimum_billing": record.minimum_billing,
    }


def _cell(latitude: float, longitude: float) -> tuple[int, int]:
    return (math.floor(latitude / CELL_DEGREES), math.floor(longitude / CELL_DEGREES))


def _cells_covering(
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
) -> list[tuple[int, int]]:
    row_start = math.floor(min_lat / CELL_DEGREES)
    row_end = math.floor(max_lat / CELL_DEGREES)
    col_start = math.floor(min_lng / CELL_DEGREES)
    col_end = math.floor(max_lng / CELL_DEGREES)
    return [
        (row, col)
        for row in range(row_start, row_end + 1)
        for col in range(col_start, col_end + 1)
    ]


def _match_payload(
    *,
    status: str,
    radius_km: float,
    competitors: list[dict[str, Any]],
    catalog_size: int,
    skipped_invalid: int,
    message: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "radius_km": radius_km,
        "competitors": competitors,
        "catalog_size": catalog_size,
        "skipped_invalid_coordinates": skipped_invalid,
        "message": message,
    }
