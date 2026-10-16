from __future__ import annotations

import logging
from typing import Any

from mcp_server.services.competitor_service import CompetitorIndex, attach_nearby_competitors
from mcp_server.services.geo import parse_coordinate

logger = logging.getLogger("mcp_server.services.media_plan")


def select_inventory_within_budget(
    items: list[dict[str, Any]],
    budget: float,
    max_sites: int,
) -> dict[str, Any]:
    """Greedy budget fill. Higher recorded reach is preferred, then lower cost."""
    priced: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in items:
        cost, status = estimate_cost(item)
        copy = dict(item)
        copy["estimated_cost"] = cost
        copy["price_status"] = status
        if cost is None:
            excluded.append(copy)
        else:
            priced.append(copy)

    priced.sort(key=_rank_key)
    selected: list[dict[str, Any]] = []
    remaining = float(budget)
    omitted = 0
    for item in priced:
        if len(selected) >= max_sites:
            break
        if item["estimated_cost"] > remaining:
            omitted += 1
            continue
        selected.append(item)
        remaining = round(remaining - item["estimated_cost"], 2)

    estimated_spend = round(sum(item["estimated_cost"] for item in selected), 2)
    return {
        "selected": selected,
        "excluded_unpriced": excluded,
        "omitted_for_budget": omitted,
        "estimated_spend": estimated_spend,
        "remaining_budget": round(float(budget) - estimated_spend, 2),
    }


def estimate_cost(item: dict[str, Any]) -> tuple[float | None, str]:
    total = _positive_amount(item.get("total_cost"))
    if total is not None:
        return round(total, 2), "total_cost"
    components = [
        amount
        for amount in (
            _positive_amount(item.get("display_cost")),
            _positive_amount(item.get("printing_cost")),
            _positive_amount(item.get("installation_cost")),
        )
        if amount is not None
    ]
    if components:
        return round(sum(components), 2), "partial_components"
    return None, "missing"


class MediaPlanService:
    def __init__(self, inventory: Any, catalog: CompetitorIndex) -> None:
        self.inventory = inventory
        self.catalog = catalog

    async def generate(
        self,
        *,
        brand: str,
        city: str,
        budget: float,
        media_type: str = "",
        objective: str = "",
        query: str = "",
        radius_km: float,
        max_competitors: int,
        max_candidates: int,
        max_sites: int,
        competitor_media_type: str = "",
        competitor_brand: str = "",
        precision: int = 2,
    ) -> dict[str, Any]:
        candidate_cap = min(max(int(max_candidates), 1), 5000)
        candidates = await self._collect_candidates(
            city=city,
            media_type=media_type,
            query=query,
            max_candidates=candidate_cap,
        )
        annotated = [
            attach_nearby_competitors(
                item,
                self.catalog,
                radius_km=radius_km,
                limit=max_competitors,
                media_type=competitor_media_type,
                brand=competitor_brand,
                precision=precision,
            )
            for item in candidates
        ]
        chosen = select_inventory_within_budget(annotated, budget, max_sites)
        recommended = [self._present(item, radius_km) for item in chosen["selected"]]
        logger.info(
            "media_plan_generated",
            extra={
                "city": city,
                "recommended": len(recommended),
                "estimated_spend": chosen["estimated_spend"],
            },
        )
        return {
            "campaign": {
                "brand": brand,
                "city": city,
                "budget": budget,
                "media_type": media_type or None,
                "objective": objective or None,
            },
            "recommended_inventory": recommended,
            "excluded_inventory": [_excluded_item(item) for item in chosen["excluded_unpriced"]],
            "budget_summary": {
                "total_budget": budget,
                "estimated_spend": chosen["estimated_spend"],
                "remaining_budget": chosen["remaining_budget"],
                "recommended_count": len(recommended),
                "currency": "INR",
                "unpriced_excluded_count": len(chosen["excluded_unpriced"]),
                "sites_omitted_for_budget": chosen["omitted_for_budget"],
            },
            "selection_strategy": (
                "Every matching inventory site is checked, up to "
                f"{candidate_cap} records. Sites with nearby competitor media are ordered first, "
                "then by recorded audience reach, highest first, then by lower estimated cost. "
                "A site is added while its estimated cost fits the remaining budget. "
                "Empty price fields are reported and left out of the spend."
            ),
        }

    async def _collect_candidates(
        self,
        *,
        city: str,
        media_type: str,
        query: str,
        max_candidates: int,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        offset = 0
        mode = "synonym" if media_type.strip() else "exact"
        while len(candidates) < max_candidates:
            page_limit = min(100, max_candidates - len(candidates))
            items, total = await self.inventory.search(
                query=query or None,
                city=city or None,
                media_type=media_type or None,
                media_type_mode=mode,
                offset=offset,
                limit=page_limit,
            )
            if not items:
                break
            candidates.extend(items)
            offset += len(items)
            if offset >= total:
                break
        return candidates

    def _present(self, item: dict[str, Any], radius_km: float) -> dict[str, Any]:
        enriched = dict(item)
        enriched["inventory_id"] = item.get("inventory_code") or item.get("id")
        enriched["name"] = _display_name(item)
        enriched["pricing"] = {
            "display_cost": item.get("display_cost"),
            "printing_cost": item.get("printing_cost"),
            "installation_cost": item.get("installation_cost"),
            "total_cost": item.get("total_cost"),
            "price_status": item.get("price_status"),
        }
        enriched["audience"] = item.get("admavin")
        warnings = list(enriched.get("warnings") or [])
        if item.get("price_status") == "partial_components":
            warnings.append(
                "Estimated cost uses the available display, printing, and installation "
                "components because total_cost is empty."
            )
        enriched["warnings"] = warnings
        enriched["selection_reason"] = _selection_reason(enriched, radius_km)
        return enriched


def _positive_amount(value: Any) -> float | None:
    number = parse_coordinate(value)
    if number is None or number <= 0:
        return None
    return number


def _reach(item: dict[str, Any]) -> float | None:
    audience = item.get("admavin")
    if not isinstance(audience, dict):
        return None
    number = parse_coordinate(audience.get("reach"))
    if number is None or number < 0:
        return None
    return number


def _rank_key(item: dict[str, Any]) -> tuple:
    reach = _reach(item)
    has_competitors = 1 if item.get("nearby_competitors") else 0
    return (
        -has_competitors,
        0 if reach is not None else 1,
        -(reach or 0.0),
        item["estimated_cost"],
        str(item.get("inventory_code") or item.get("id") or ""),
    )


def _display_name(item: dict[str, Any]) -> str:
    parts = [
        part
        for part in (
            item.get("media_type"),
            item.get("area") or item.get("location"),
            item.get("inventory_code"),
        )
        if part
    ]
    if parts:
        return " · ".join(str(part) for part in parts)
    return str(item.get("id") or "Inventory site")


def _selection_reason(item: dict[str, Any], radius_km: float) -> str:
    media_type = item.get("media_type") or "media"
    city = item.get("city") or "the requested city"
    location = item.get("location")
    where = f" at {location}" if location else ""
    cost = item.get("estimated_cost") or 0
    reason = (
        f"Included as a {media_type} site in {city}{where} "
        f"with an estimated cost of {cost:.2f} INR that fits the remaining budget."
    )
    audience = item.get("audience") if isinstance(item.get("audience"), dict) else item.get("admavin")
    reach = audience.get("reach") if isinstance(audience, dict) else None
    if isinstance(reach, (int, float)) and not isinstance(reach, bool):
        reason += f" Recorded monthly reach is {int(reach)}."
    else:
        reason += " Audience reach is not available for this site."

    status = (item.get("competitor_search") or {}).get("status")
    competitors = item.get("nearby_competitors") or []
    if status == "skipped_missing_coordinates":
        reason += (
            " Nearby competitor matching is unavailable because this site has no valid "
            "latitude and longitude."
        )
    elif competitors:
        nearest = competitors[0].get("distance_km")
        nearest_text = f", nearest at {nearest} km" if nearest is not None else ""
        reason += (
            f" Competitive context: {len(competitors)} competitor placement(s) within "
            f"{radius_km:g} km{nearest_text}. Competitor proximity is planning context."
        )
    else:
        reason += f" No competitor media was found within {radius_km:g} km."
    if item.get("price_status") == "partial_components":
        reason += " The cost is estimated from available component prices because total_cost is empty."
    return reason


def _excluded_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "inventory_id": item.get("inventory_code") or item.get("id"),
        "inventory_code": item.get("inventory_code"),
        "name": _display_name(item),
        "location": item.get("location"),
        "media_type": item.get("media_type"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "price_status": "missing",
        "estimated_cost": None,
        "reason": "Price is missing or zero, so this site was not included in the spend.",
    }
