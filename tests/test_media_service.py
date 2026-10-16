from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import pytest

from mcp_server.services.media_service import MediaInventoryService, haversine_distance_km


def test_haversine_distance():
    # Mumbai Marine Drive to Nariman Point (~1.5 km)
    dist = haversine_distance_km(18.951392, 72.817609, 18.9256, 72.8242)
    assert 2.0 < dist < 4.0


@pytest.mark.asyncio
async def test_get_media_by_identifier_not_found():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_session.execute.return_value = mock_result

    service = MediaInventoryService(mock_session)
    result = await service.get_media_by_identifier("NONEXISTENT_CODE")
    assert result is None
