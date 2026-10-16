from __future__ import annotations

from mcp_server.schemas.common import ErrorPayload, PaginationMeta, StandardResponse


def test_standard_response_success():
    resp = StandardResponse.success_response(
        data=[{"id": "1", "code": "MI1"}],
        pagination=PaginationMeta(offset=0, limit=20, total=1),
    )
    assert resp.success is True
    assert len(resp.data) == 1
    assert resp.pagination is not None
    assert resp.pagination.total == 1
    assert resp.error is None


def test_standard_response_error():
    resp = StandardResponse.error_response(
        code="ITEM_NOT_FOUND",
        message="Item not found",
        details={"identifier": "MI999"},
    )
    assert resp.success is False
    assert resp.data is None
    assert resp.pagination is None
    assert resp.error is not None
    assert resp.error.code == "ITEM_NOT_FOUND"
    assert resp.error.details == {"identifier": "MI999"}
