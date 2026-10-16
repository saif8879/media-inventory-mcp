from __future__ import annotations

import math
from typing import Any

EARTH_RADIUS_KM = 6371.0

SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset(
        {
            "billboard",
            "billboards",
            "bill board",
            "billording",
            "hoarding",
            "hoardings",
            "hording",
            "unipole",
            "unipoles",
        }
    ),
    frozenset({"digital", "digital ooh", "dooh", "led"}),
    frozenset({"bus shelter", "bus shelter advertising"}),
    frozenset({"gantry"}),
    frozenset({"metro pillar"}),
    frozenset({"pole kiosk"}),
    frozenset({"skywalk"}),
)


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in kilometres."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return EARTH_RADIUS_KM * c


def parse_coordinate(value: Any) -> float | None:
    """Parse a finite number. Booleans and blank text are rejected."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.casefold() in {"null", "none", "nan", "undefined"}:
            return None
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def valid_lat_lng(latitude: Any, longitude: Any) -> tuple[float, float] | None:
    lat = parse_coordinate(latitude)
    lng = parse_coordinate(longitude)
    if lat is None or lng is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return None
    return lat, lng


def bounding_box_deltas(latitude: float, radius_km: float) -> tuple[float, float]:
    lat_delta = radius_km / 111.0
    cosine = math.cos(math.radians(latitude))
    lng_delta = radius_km / (111.0 * max(abs(cosine), 0.01))
    return lat_delta, lng_delta


def normalize_media_type(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().casefold().replace("-", " ").replace("_", " ").split())


def expanded_media_types(value: str | None) -> set[str]:
    key = normalize_media_type(value)
    if not key:
        return set()
    for group in SYNONYM_GROUPS:
        if key in group:
            return set(group)
    return {key}


def is_billboard_family(value: str | None) -> bool:
    """True for billboard, hoarding, hording, unipole, and the same spellings."""
    key = normalize_media_type(value)
    if not key:
        return False
    return key in SYNONYM_GROUPS[0]


def media_type_matches(requested: str | None, actual: str | None) -> bool:
    if requested is None or not str(requested).strip():
        return True
    actual_key = normalize_media_type(actual)
    if not actual_key:
        return False
    return actual_key in expanded_media_types(requested)


def media_type_like_patterns(value: str) -> list[str]:
    return sorted(expanded_media_types(value))


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
