from __future__ import annotations

import math
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Integer,
    and_,
    case,
    cast,
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_server.models import (
    AdMavinMediaInventory,
    MediaInventory,
    MediaInventoryPriceHistory,
)
from mcp_server.services.geo import (
    escape_like,
    haversine_distance_km,
    media_type_like_patterns,
)


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def serialize_media_item(
    row: MediaInventory,
    admavin: AdMavinMediaInventory | None = None,
    latest_quotation: Decimal | None = None,
) -> dict[str, Any]:
    """Convert MediaInventory ORM object into a clean dictionary for AI."""
    item: dict[str, Any] = {
        "id": str(row.id),
        "inventory_code": row.inventory_code,
        "city": row.city,
        "area": row.area,
        "location": row.location,
        "category": row.category,
        "media_type": row.media_type,
        "sub_type": row.sub_type,
        "orientation": row.orientation,
        "facing": row.facing,
        "width": _to_float(row.width),
        "height": _to_float(row.height),
        "area_sq_ft": _to_float(row.area_sq_ft),
        "latitude": _to_float(row.latitude),
        "longitude": _to_float(row.longitude),
        "media_owner": row.media_owner,
        "qty": row.qty,
        "number_of_slots": row.number_of_slots,
        "display_cost": _to_float(row.display_cost),
        "printing_cost": _to_float(row.printing_cost),
        "installation_cost": _to_float(row.installation_cost),
        "total_cost": _to_float(row.total_cost),
        "has_image": bool(row.image_url and row.image_url.strip()),
        "image_url": row.image_url,
        "remark": row.remark,
        "is_synced": row.is_synced,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }

    if latest_quotation is not None:
        item["latest_quotation_price"] = _to_float(latest_quotation)

    if admavin:
        item["admavin"] = {
            "reach": admavin.reach,
            "ots": admavin.ots,
            "avg_frequency": _to_float(admavin.avg_frequency),
            "avg_dwell_time": _to_float(admavin.avg_dwell_time),
            "reach_percent": _to_float(admavin.reach_percent),
            "lts_score": _to_float(admavin.lts_score),
            "lts_rating": _to_float(admavin.lts_rating),
            "sync_status": admavin.sync_status,
        }
    return item


class MediaInventoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _build_admavin_join(self):
        sub_type_lit = func.lower(func.trim(func.coalesce(MediaInventory.sub_type, "")))
        derived_lit = case(
            (sub_type_lit.like("%back%"), "Back"),
            (sub_type_lit.like("%front%"), "Front"),
            (
                or_(
                    sub_type_lit.in_(("non lit", "nonlit", "non-lit", "unlit")),
                    and_(sub_type_lit.like("%non%"), sub_type_lit.like("%lit%")),
                ),
                "NON LIT",
            ),
            (sub_type_lit == "led", "LED"),
            else_="Front",
        )
        join_on = and_(
            func.round(MediaInventory.latitude, 6)
            == func.round(AdMavinMediaInventory.latitude, 6),
            func.round(MediaInventory.longitude, 6)
            == func.round(AdMavinMediaInventory.longitude, 6),
            derived_lit == AdMavinMediaInventory.lit,
        )
        return AdMavinMediaInventory, join_on

    async def get_media_by_identifier(
        self,
        identifier: str,
        include_price_history: bool = True,
        include_audience_metrics: bool = True,
    ) -> dict[str, Any] | None:
        """Find media item by inventory_code (e.g. MI1) or UUID id."""
        clean_id = identifier.strip()
        admavin_model, join_on = self._build_admavin_join()

        # Check if identifier is a valid UUID
        is_uuid = False
        parsed_uuid = None
        try:
            parsed_uuid = uuid.UUID(clean_id)
            is_uuid = True
        except ValueError:
            is_uuid = False

        query = select(MediaInventory, admavin_model).outerjoin(admavin_model, join_on)
        if is_uuid and parsed_uuid:
            query = query.where(MediaInventory.id == parsed_uuid)
        else:
            query = query.where(
                func.lower(MediaInventory.inventory_code) == clean_id.lower()
            )

        res = await self.db.execute(query.limit(1))
        row_tuple = res.first()
        if not row_tuple:
            return None

        media, admavin = row_tuple
        data = serialize_media_item(media, admavin)

        if include_audience_metrics and admavin:
            data["audience_metrics"] = {
                "reach": admavin.reach,
                "ots": admavin.ots,
                "avg_frequency": _to_float(admavin.avg_frequency),
                "avg_dwell_time": _to_float(admavin.avg_dwell_time),
                "reach_percent": _to_float(admavin.reach_percent),
                "lts_score": _to_float(admavin.lts_score),
                "lts_rating": _to_float(admavin.lts_rating),
                "demographic_summary": admavin.demographic_summary,
                "location_summary": admavin.location_summary,
                "traffic_profile": admavin.traffic_profile,
                "landmarks_nearby": admavin.landmarks_nearby,
                "target_groups": {
                    "gender": admavin.tg_gender,
                    "age": admavin.tg_age,
                    "income": admavin.tg_income,
                },
                "sync_status": admavin.sync_status,
                "synced_at": admavin.synced_at.isoformat() if admavin.synced_at else None,
            }

        if include_price_history:
            history_query = (
                select(MediaInventoryPriceHistory)
                .where(MediaInventoryPriceHistory.media_inventory_id == media.id)
                .order_by(MediaInventoryPriceHistory.created_at.desc())
            )
            hist_res = await self.db.execute(history_query)
            price_rows = hist_res.scalars().all()
            data["price_history"] = [
                {
                    "id": str(p.id),
                    "quotation_price": _to_float(p.quotation_price),
                    "comment": p.comment,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in price_rows
            ]

        return data

    async def search(
        self,
        query: str | None = None,
        city: str | None = None,
        media_type: str | None = None,
        media_owner: str | None = None,
        min_total_cost: float | None = None,
        max_total_cost: float | None = None,
        min_reach: int | None = None,
        min_ots: int | None = None,
        has_image: bool | None = None,
        offset: int = 0,
        limit: int = 20,
        media_type_mode: str = "exact",
    ) -> tuple[list[dict[str, Any]], int]:
        admavin_model, join_on = self._build_admavin_join()
        conditions = []

        if query and query.strip():
            pat = f"%{query.strip()}%"
            conditions.append(
                or_(
                    MediaInventory.inventory_code.ilike(pat),
                    MediaInventory.city.ilike(pat),
                    MediaInventory.area.ilike(pat),
                    MediaInventory.location.ilike(pat),
                    MediaInventory.category.ilike(pat),
                    MediaInventory.media_type.ilike(pat),
                    MediaInventory.sub_type.ilike(pat),
                    MediaInventory.media_owner.ilike(pat),
                )
            )

        if city and city.strip():
            conditions.append(func.lower(MediaInventory.city) == city.strip().lower())
        if media_type and media_type.strip():
            if media_type_mode == "synonym":
                patterns = media_type_like_patterns(media_type)
                conditions.append(
                    or_(
                        *[
                            MediaInventory.media_type.ilike(
                                f"%{escape_like(pattern)}%",
                                escape="\\",
                            )
                            for pattern in patterns
                        ]
                    )
                )
            elif media_type_mode == "exact":
                conditions.append(
                    func.lower(MediaInventory.media_type) == media_type.strip().lower()
                )
            else:
                raise ValueError(f"Unsupported media_type_mode: {media_type_mode}")
        if media_owner and media_owner.strip():
            conditions.append(
                func.lower(MediaInventory.media_owner) == media_owner.strip().lower()
            )

        if min_total_cost is not None:
            conditions.append(MediaInventory.total_cost >= min_total_cost)
        if max_total_cost is not None:
            conditions.append(MediaInventory.total_cost <= max_total_cost)

        if min_reach is not None:
            conditions.append(admavin_model.reach >= min_reach)
        if min_ots is not None:
            conditions.append(admavin_model.ots >= min_ots)

        if has_image is not None:
            if has_image:
                conditions.append(
                    and_(
                        MediaInventory.image_url.isnot(None),
                        MediaInventory.image_url != "",
                    )
                )
            else:
                conditions.append(
                    or_(
                        MediaInventory.image_url.is_(None),
                        MediaInventory.image_url == "",
                    )
                )

        bounded_limit = min(max(limit, 1), 100)
        bounded_offset = max(offset, 0)

        main_q = select(MediaInventory, admavin_model).outerjoin(
            admavin_model, join_on
        )
        count_q = (
            select(func.count())
            .select_from(MediaInventory)
            .outerjoin(admavin_model, join_on)
        )

        if conditions:
            main_q = main_q.where(*conditions)
            count_q = count_q.where(*conditions)

        # Ordering: numeric inventory code sequence if available, then created_at
        code_seq = cast(
            func.nullif(
                func.regexp_replace(MediaInventory.inventory_code, "[^0-9]", "", "g"),
                "",
            ),
            Integer,
        )
        main_q = (
            main_q.order_by(code_seq.asc().nulls_last(), MediaInventory.created_at.asc())
            .offset(bounded_offset)
            .limit(bounded_limit)
        )

        total_res = await self.db.execute(count_q)
        total = int(total_res.scalar_one())

        res = await self.db.execute(main_q)
        items = []
        for media, admavin in res.all():
            items.append(serialize_media_item(media, admavin))

        return items, total

    async def list_media(
        self,
        city: str | None = None,
        category: str | None = None,
        media_type: str | None = None,
        sub_type: str | None = None,
        orientation: str | None = None,
        media_owner: str | None = None,
        is_synced: bool | None = None,
        admavin_sync_status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        admavin_model, join_on = self._build_admavin_join()
        conditions = []

        if city and city.strip():
            conditions.append(func.lower(MediaInventory.city) == city.strip().lower())
        if category and category.strip():
            conditions.append(
                func.lower(MediaInventory.category) == category.strip().lower()
            )
        if media_type and media_type.strip():
            conditions.append(
                func.lower(MediaInventory.media_type) == media_type.strip().lower()
            )
        if sub_type and sub_type.strip():
            conditions.append(
                func.lower(MediaInventory.sub_type) == sub_type.strip().lower()
            )
        if orientation and orientation.strip():
            conditions.append(
                func.lower(MediaInventory.orientation) == orientation.strip().lower()
            )
        if media_owner and media_owner.strip():
            conditions.append(
                func.lower(MediaInventory.media_owner) == media_owner.strip().lower()
            )
        if is_synced is not None:
            conditions.append(MediaInventory.is_synced.is_(is_synced))

        if admavin_sync_status:
            if admavin_sync_status.lower() == "none":
                conditions.append(admavin_model.id.is_(None))
            else:
                conditions.append(admavin_model.sync_status == admavin_sync_status.lower())

        bounded_limit = min(max(limit, 1), 100)
        bounded_offset = max(offset, 0)

        main_q = select(MediaInventory, admavin_model).outerjoin(
            admavin_model, join_on
        )
        count_q = (
            select(func.count())
            .select_from(MediaInventory)
            .outerjoin(admavin_model, join_on)
        )

        if conditions:
            main_q = main_q.where(*conditions)
            count_q = count_q.where(*conditions)

        code_seq = cast(
            func.nullif(
                func.regexp_replace(MediaInventory.inventory_code, "[^0-9]", "", "g"),
                "",
            ),
            Integer,
        )
        main_q = (
            main_q.order_by(code_seq.asc().nulls_last(), MediaInventory.created_at.asc())
            .offset(bounded_offset)
            .limit(bounded_limit)
        )

        total_res = await self.db.execute(count_q)
        total = int(total_res.scalar_one())

        res = await self.db.execute(main_q)
        items = [serialize_media_item(m, a) for m, a in res.all()]
        return items, total

    async def get_statistics(
        self,
        city: str | None = None,
        media_type: str | None = None,
        breakdown_by: str | None = None,
    ) -> dict[str, Any]:
        admavin_model, join_on = self._build_admavin_join()
        conditions = []

        if city and city.strip():
            conditions.append(func.lower(MediaInventory.city) == city.strip().lower())
        if media_type and media_type.strip():
            conditions.append(
                func.lower(MediaInventory.media_type) == media_type.strip().lower()
            )

        agg_query = (
            select(
                func.count(MediaInventory.id).label("total_sites"),
                func.count(func.distinct(MediaInventory.city)).label("total_cities"),
                func.count(func.distinct(MediaInventory.media_type)).label("total_media_types"),
                func.avg(MediaInventory.total_cost).label("avg_total_cost"),
                func.min(MediaInventory.total_cost).label("min_total_cost"),
                func.max(MediaInventory.total_cost).label("max_total_cost"),
                func.sum(admavin_model.reach).label("total_reach"),
                func.avg(admavin_model.reach).label("avg_reach"),
                func.avg(admavin_model.ots).label("avg_ots"),
                func.avg(admavin_model.lts_score).label("avg_lts_score"),
            )
            .select_from(MediaInventory)
            .outerjoin(admavin_model, join_on)
        )

        if conditions:
            agg_query = agg_query.where(*conditions)

        res = await self.db.execute(agg_query)
        row = res.one()

        stats: dict[str, Any] = {
            "total_sites": row.total_sites or 0,
            "total_cities": row.total_cities or 0,
            "total_media_types": row.total_media_types or 0,
            "cost_metrics": {
                "avg_total_cost": _to_float(row.avg_total_cost),
                "min_total_cost": _to_float(row.min_total_cost),
                "max_total_cost": _to_float(row.max_total_cost),
            },
            "audience_metrics": {
                "total_reach": row.total_reach or 0,
                "avg_reach": _to_float(row.avg_reach),
                "avg_ots": _to_float(row.avg_ots),
                "avg_lts_score": _to_float(row.avg_lts_score),
            },
        }

        # Breakdown if requested
        valid_breakdowns = {
            "city": MediaInventory.city,
            "media_type": MediaInventory.media_type,
            "category": MediaInventory.category,
            "media_owner": MediaInventory.media_owner,
        }
        if breakdown_by and breakdown_by.lower() in valid_breakdowns:
            col = valid_breakdowns[breakdown_by.lower()]
            breakdown_q = (
                select(col, func.count(MediaInventory.id))
                .select_from(MediaInventory)
                .where(col.isnot(None), col != "")
            )
            if conditions:
                breakdown_q = breakdown_q.where(*conditions)
            breakdown_q = breakdown_q.group_by(col).order_by(
                func.count(MediaInventory.id).desc()
            )
            bd_res = await self.db.execute(breakdown_q)
            stats["breakdown"] = {
                (key or "Unknown"): count for key, count in bd_res.all()
            }

        return stats

    async def find_related(
        self,
        reference_identifier: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float = 5.0,
        same_media_type: bool = False,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        target_lat = latitude
        target_lng = longitude
        ref_media_type = None
        ref_id = None

        if reference_identifier:
            ref = await self.get_media_by_identifier(reference_identifier)
            if not ref:
                return []
            ref_id = ref["id"]
            target_lat = ref.get("latitude")
            target_lng = ref.get("longitude")
            ref_media_type = ref.get("media_type")

        if target_lat is None or target_lng is None:
            return []

        # Bounding box filter first for performance (approx 1 deg lat ~ 111 km)
        lat_delta = radius_km / 111.0
        lng_delta = radius_km / (111.0 * math.cos(math.radians(target_lat)) or 1.0)

        admavin_model, join_on = self._build_admavin_join()
        conditions = [
            MediaInventory.latitude.between(target_lat - lat_delta, target_lat + lat_delta),
            MediaInventory.longitude.between(target_lng - lng_delta, target_lng + lng_delta),
        ]
        if ref_id:
            conditions.append(MediaInventory.id != uuid.UUID(ref_id))

        if same_media_type and ref_media_type:
            conditions.append(
                func.lower(MediaInventory.media_type) == ref_media_type.lower()
            )

        query = (
            select(MediaInventory, admavin_model)
            .outerjoin(admavin_model, join_on)
            .where(*conditions)
            .limit(limit * 3)  # fetch buffer before exact distance sorting
        )
        res = await self.db.execute(query)

        scored: list[tuple[float, dict[str, Any]]] = []
        for media, admavin in res.all():
            m_lat = _to_float(media.latitude)
            m_lng = _to_float(media.longitude)
            if m_lat is None or m_lng is None:
                continue
            dist = haversine_distance_km(target_lat, target_lng, m_lat, m_lng)
            if dist <= radius_km:
                item = serialize_media_item(media, admavin)
                item["distance_km"] = round(dist, 2)
                item["relation_rationale"] = (
                    f"Located {dist:.2f} km away in {media.city or 'nearby'}"
                    + (
                        f" (same media type: {media.media_type})"
                        if same_media_type
                        else ""
                    )
                )
                scored.append((dist, item))

        scored.sort(key=lambda x: x[0])
        bounded_limit = min(max(limit, 1), 50)
        return [item for _, item in scored[:bounded_limit]]
