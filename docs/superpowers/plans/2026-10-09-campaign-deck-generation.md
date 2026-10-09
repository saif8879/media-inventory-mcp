# Campaign Deck Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `generate_campaign_deck` MCP tool to create agency-style 16:9 widescreen PowerPoint (`.pptx`) decks for selected OOH media inventory sites matching `media-inventory` (Editorial Navy & Classic White), saving locally to `exports/` and uploading to private S3 storage with presigned download links.

**Architecture:** A native `python-pptx` and `Pillow` presentation builder (`DeckBuilderService`) that queries existing database records and AdMavin metrics via `MediaInventoryService`, downloads photo assets in-memory from S3 or external URLs, renders 62%/38% split site slides with contain-fit aspect ratio scaling, exports native `.pptx` slides, and delivers both local file paths and short-lived S3 presigned URLs.

**Tech Stack:** Python 3.12, `python-pptx>=1.0.2`, `Pillow>=12.3.0`, `boto3`, `fastapi`, `mcp`, `pytest`, `pytest-asyncio`.

## Global Constraints

- Slide aspect ratio must strictly be 16:9 widescreen: width = 13.333 inches, height = 7.50 inches.
- Default theme is `"editorial"` (`#0B1F3A` Navy, `#4B8EFF` electric blue accent). Also support `"classic"` (`#FFFFFF` White).
- Images must never be stretched or distorted; compute contain-fit bounding box within `8.0" × 6.20"` left container.
- Missing images must gracefully render a dark placeholder ("Site Photo Pending / Unavailable") without failing deck generation.
- Empty or completely invalid site identifiers must return `StandardResponse.error_response(code="NO_VALID_SITES")`.
- Output `.pptx` must be saved locally to `exports/campaign_deck_<slug>_<timestamp>.pptx` AND uploaded to S3 if accessible.

---

### Task 1: Add Dependencies & Create Output Directory Structure

**Files:**
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Test: `tests/test_deck_service.py`

**Interfaces:**
- Produces: `exports/` directory ignored by git, `python-pptx` and `Pillow` declared in `requirements.txt`.

- [ ] **Step 1: Write the failing test for export directory and dependency imports**

Create `tests/test_deck_service.py`:
```python
from pathlib import Path
import pptx
from PIL import Image

def test_deck_dependencies_and_exports_dir():
    assert pptx.__version__ is not None
    assert Image.__version__ is not None
```

- [ ] **Step 2: Run test to verify it executes cleanly**

Run: `.venv/bin/pytest tests/test_deck_service.py -v`
Expected: PASS (since libraries are installed).

- [ ] **Step 3: Update requirements.txt and .gitignore**

Add to `requirements.txt`:
```
python-pptx>=1.0.2
Pillow>=10.4.0
```
Add to `.gitignore`:
```
exports/
*.pptx
```

- [ ] **Step 4: Commit changes**

```bash
git add requirements.txt .gitignore tests/test_deck_service.py
git commit -m "chore: add python-pptx and Pillow dependencies, ignore exports"
```

---

### Task 2: Build DeckBuilderService (Slide Styling, Aspect Ratio Math, S3 Upload)

**Files:**
- Create: `mcp_server/services/deck_service.py`
- Test: `tests/test_deck_service.py`

**Interfaces:**
- Produces: `DeckBuilderService` with methods:
  - `compute_contain_fit(img_w: float, img_h: float, box_x: float, box_y: float, box_w: float, box_h: float) -> tuple[float, float, float, float]`
  - `build_deck(sites: list[dict[str, Any]], campaign_title: str, client_name: str, theme: str, include_commercials: bool, include_audience_metrics: bool) -> tuple[bytes, dict[str, Any]]`
  - `save_and_upload(deck_bytes: bytes, file_slug: str, expires_in: int) -> dict[str, Any]`

- [ ] **Step 1: Write unit tests for aspect ratio math and presentation generation**

Append to `tests/test_deck_service.py`:
```python
import io
from pptx import Presentation
from mcp_server.services.deck_service import DeckBuilderService

def test_compute_contain_fit():
    service = DeckBuilderService()
    # Wide image: 1600x800 into 8.0 x 6.0 box
    x, y, w, h = service.compute_contain_fit(1600, 800, box_x=1.0, box_y=1.0, box_w=8.0, box_h=6.0)
    assert round(w, 2) == 8.0
    assert round(h, 2) == 4.0
    assert round(x, 2) == 1.0
    assert round(y, 2) == 2.0  # Centered vertically in 6.0 box

    # Tall image: 800x1600 into 8.0 x 6.0 box
    x2, y2, w2, h2 = service.compute_contain_fit(800, 1600, box_x=1.0, box_y=1.0, box_w=8.0, box_h=6.0)
    assert round(h2, 2) == 6.0
    assert round(w2, 2) == 3.0
    assert round(x2, 2) == 3.5  # Centered horizontally in 8.0 box

def test_build_deck_creates_valid_pptx():
    service = DeckBuilderService()
    sample_sites = [
        {
            "id": "site-1",
            "inventory_code": "MI1",
            "city": "Mumbai",
            "area": "Bandra West",
            "location": "Linking Road, Bandra",
            "media_type": "Billboard",
            "sub_type": "Frontlit",
            "facing": "North",
            "width": 30.0,
            "height": 15.0,
            "area_sq_ft": 450.0,
            "total_cost": 450000.0,
            "image_url": None,
            "admavin": {
                "reach": 1250000,
                "ots": 3400000,
                "lts_score": 0.88,
            }
        }
    ]
    deck_bytes, summary = service.build_deck(
        sites=sample_sites,
        campaign_title="Q4 Festival Campaign",
        client_name="Test Brand",
        theme="editorial",
        include_commercials=True,
        include_audience_metrics=True,
    )
    assert len(deck_bytes) > 0
    assert summary["site_count"] == 1
    assert summary["total_monthly_cost"] == 450000.0

    # Verify PPTX is readable
    prs = Presentation(io.BytesIO(deck_bytes))
    # 3 slides: Cover, Site 1, Closing
    assert len(prs.slides) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_deck_service.py -k test_compute_contain_fit -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server.services.deck_service'`

- [ ] **Step 3: Implement DeckBuilderService in `mcp_server/services/deck_service.py`**

Create `mcp_server/services/deck_service.py` with:
- Themes configuration (`Editorial` vs `Classic`)
- 16:9 dimensions (`Inches(13.333)`, `Inches(7.50)`)
- Slide builders: `_add_cover_slide`, `_add_site_slide`, `_add_closing_slide`
- In-memory asset loader (fetching S3 bytes or HTTP, decoding with PIL)
- Dual delivery helper: `save_and_upload` saving to `exports/` and uploading to S3 if configured.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_deck_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add mcp_server/services/deck_service.py tests/test_deck_service.py
git commit -m "feat: implement DeckBuilderService with 16:9 widescreen layout and dual storage"
```

---

### Task 3: Implement MCP Tool `generate_campaign_deck` & Register on Server

**Files:**
- Create: `mcp_server/tools/generate_campaign_deck.py`
- Modify: `mcp_server/tools/__init__.py`
- Modify: `mcp_server/server.py`
- Test: `tests/test_deck_service.py`

**Interfaces:**
- Produces: `generate_campaign_deck_handler` tool function, registered in `create_mcp_server()`.

- [ ] **Step 1: Write integration test for `generate_campaign_deck` tool handler**

Append to `tests/test_deck_service.py`:
```python
import pytest
import json
from unittest.mock import AsyncMock, patch
from mcp_server.server import create_mcp_server

@pytest.mark.asyncio
async def test_mcp_server_lists_generate_campaign_deck():
    server = create_mcp_server()
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}
    assert "generate_campaign_deck" in tool_names

@pytest.mark.asyncio
async def test_generate_campaign_deck_handler_no_sites():
    server = create_mcp_server()
    res = await server.call_tool(
        "generate_campaign_deck",
        {"site_identifiers": []}
    )
    assert not res.is_error
    data = json.loads(res.content[0].text)
    assert data["success"] is False
    assert data["error"]["code"] == "NO_VALID_SITES"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_deck_service.py -k test_mcp_server_lists_generate_campaign_deck -v`
Expected: FAIL (tool not yet registered).

- [ ] **Step 3: Implement tool handler and registration**

Create `mcp_server/tools/generate_campaign_deck.py`:
- Validate `site_identifiers`
- Query sites in order using `MediaInventoryService.get_media_by_identifier`
- Call `DeckBuilderService().build_deck(...)`
- Call `DeckBuilderService().save_and_upload(...)`
- Return `StandardResponse.success_response(...)`

Update `mcp_server/tools/__init__.py` and `mcp_server/server.py` (`/health` endpoint tool list) to include `generate_campaign_deck`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_deck_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**

```bash
git add mcp_server/tools/generate_campaign_deck.py mcp_server/tools/__init__.py mcp_server/server.py tests/test_deck_service.py
git commit -m "feat: register generate_campaign_deck MCP tool"
```

---

### Task 4: Comprehensive Tests and Live System End-to-End Verification

**Files:**
- Modify: `tests/test_live_system.py`
- Modify: `README.md`

- [ ] **Step 1: Add live deck generation test to `tests/test_live_system.py`**

Append to `test_live_system_verification` in `tests/test_live_system.py`:
- Call `generate_campaign_deck` for actual site codes (e.g. `["MI7"]`)
- Verify `.pptx` file was generated in `exports/`
- Verify S3 presigned URL is returned and active
- Verify total slides == 3 (Cover, Site, Closing)

- [ ] **Step 2: Run full test suite with network access**

Run: `.venv/bin/pytest -v`
Expected: All tests PASS.

- [ ] **Step 3: Update README.md with tool documentation**

Document `generate_campaign_deck` in `README.md` under Section 2 (Tools).

- [ ] **Step 4: Commit changes**

```bash
git add tests/test_live_system.py README.md
git commit -m "docs: document generate_campaign_deck tool and add live verification"
```
