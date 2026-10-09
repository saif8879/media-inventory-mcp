from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MediaInventory(Base):
    __tablename__ = "media_inventory"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    inventory_code: Mapped[str | None] = mapped_column(
        String(32), unique=True, nullable=True, index=True
    )
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sub_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    orientation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    width: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    height: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    facing: Mapped[str | None] = mapped_column(String(100), nullable=True)
    area_sq_ft: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    elevation: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    tilt: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    pixels: Mapped[str | None] = mapped_column(String(255), nullable=True)
    excel_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qty: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)
    number_of_slots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    printing_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    installation_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    is_synced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MediaInventoryPriceHistory(Base):
    __tablename__ = "media_inventory_price_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    media_inventory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    quotation_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdMavinMediaInventory(Base):
    __tablename__ = "admavin_media_inventory"
    __table_args__ = (
        UniqueConstraint(
            "latitude",
            "longitude",
            "lit",
            name="ux_admavin_media_inventory_latlong_lit",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lit: Mapped[str] = mapped_column(String(20), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    date: Mapped[date_type | None] = mapped_column(Date, nullable=True)

    # Generic Metrics
    reach: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    avg_frequency: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    avg_dwell_time: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    reach_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    ots: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    frequency_wise_reach: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    # LTS
    lts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    lts_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    lts_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)

    # Demographics & Location Summary
    location_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    traffic_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    demographic_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    landmarks_nearby: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    # Target Group splits
    tg_gender: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tg_age: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tg_income: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Sync status
    sync_status: Mapped[str] = mapped_column(String(16), nullable=False)
    sync_error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generated_on: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
