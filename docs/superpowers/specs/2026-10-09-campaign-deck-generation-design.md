# Campaign Deck Generation (`generate_campaign_deck`) Design Specification

## 1. Overview & Business Intent

In the `media-inventory` system, users export curated Out-of-Home (OOH) media proposals into branded PowerPoint presentations (Cover slide, 62%/38% split photo-to-specs slides, and Closing thank-you slide in Editorial and Classic themes).

This specification adds a native MCP tool (`generate_campaign_deck`) to the `media-in-mcp` server. It enables AI assistants (in Cursor, Claude Desktop, or ChatGPT) to automatically generate, style, save locally, and upload to S3 private storage professional 16:9 widescreen PowerPoint (`.pptx`) decks for any selected list of media sites.

---

## 2. MCP Tool Contract: `generate_campaign_deck`

* **Tool Name**: `generate_campaign_deck`
* **Description**:
  > "Generate an Out-of-Home (OOH) presentation deck (.pptx format, 16:9 widescreen) for selected media sites matching the agency pitch deck designs from media-inventory (Editorial Navy or Classic White). Embeds site photographs, technical dimensions, location details, audience metrics, and quotation costs. Delivers both local file path and private S3 presigned download URL."
* **Parameters**:
  * `site_identifiers` *(list[str], required)*: List of site inventory codes (e.g., `["MI1", "MI7", "MI42"]`) or UUIDs in desired presentation order.
  * `campaign_title` *(str, optional, default: `"Campaign Proposal"`)*: Main title on the cover slide.
  * `client_name` *(str, optional, default: `""`)*: Client or brand name for whom the deck is prepared.
  * `theme` *(str, optional, default: `"editorial"`)*: Visual theme: `"editorial"` (Navy `#0B1F3A` background) or `"classic"` (Clean White background).
  * `include_commercials` *(bool, optional, default: `True`)*: Whether to display total monthly cost and rate breakdown on the site slides.
  * `include_audience_metrics` *(bool, optional, default: `True`)*: Whether to display AdMavin audience metrics (Reach, OTS, LTS rating).
  * `expires_in` *(int, optional, default: `900`)*: S3 presigned URL expiration duration in seconds (min: 60, max: 3600).

* **Output Schema**:
  ```json
  {
    "success": true,
    "data": {
      "file_name": "campaign_deck_mumbai_launch_20261009_111500.pptx",
      "local_file_path": "/Users/saifidrisi/Documents/media-in-mcp/exports/campaign_deck_mumbai_launch_20261009_111500.pptx",
      "s3_download_url": "https://buzzomni-media-inventory.s3.ap-south-1.amazonaws.com/campaign-decks/...",
      "expires_in_seconds": 900,
      "site_count": 3,
      "theme": "editorial",
      "summary": {
        "total_monthly_cost": 2450000.0,
        "total_reach": 1820000,
        "cities": ["Mumbai"]
      },
      "warnings": []
    },
    "error": null
  }
  ```

---

## 3. Visual Layout & Typography (16:9 Widescreen)

Slide dimensions: **13.333 inches (960pt)** wide by **7.50 inches (540pt)** high.

### A. Editorial Theme (Default)
1. **Color Palette**:
   - Background: Dark Navy `#0B1F3A` (`RGB(11, 31, 58)`)
   - Accent / Kicker: Electric Blue `#4B8EFF` (`RGB(75, 142, 255)`)
   - Secondary Panel: Deep Slate Navy `#112A4D` (`RGB(17, 42, 77)`)
   - Text Primary: Pure White `#FFFFFF` (`RGB(255, 255, 255)`)
   - Text Muted: Light Slate `#94A3B8` (`RGB(148, 163, 184)`)
   - Border / Dividers: Slate `#1E3A5F` (`RGB(30, 58, 95)`)

2. **Cover Slide Layout**:
   - Left accent line: Width `0.15"`, Height `5.5"`, Color `#4B8EFF` at `x=0.8"`, `y=1.0"`.
   - Kicker: `CAMPAIGN PROPOSAL & MEDIA PLAN`, 11pt, bold, `#4B8EFF`.
   - Title: Dynamic `campaign_title`, 36–42pt bold, `#FFFFFF`.
   - Subtitle: `client_name` (if provided), 18pt, `#94A3B8`.
   - Footer metadata: Site count badge (`"X Selected OOH Sites"`), generation date, and agency branding.

3. **Site Slide Layout (62% / 38% Split)**:
   - **Left Photo Container** (`x=0.6"`, `y=0.65"`, `w=8.0"`, `h=6.20"`):
     - Background: Charcoal `#16202E`.
     - Image scaling: Contain-fit preserving native aspect ratio.
     - Fallback: Dark container with centered icon/text `"Site Photo Pending / Unavailable"` in `#64748B`.
   - **Right Spec Panel** (`x=8.8"`, `y=0.65"`, `w=3.95"`, `h=6.20"`):
     - Background: `#112A4D` with `#1E3A5F` border.
     - Top Kicker: `SITE 01 / 05` (`#4B8EFF`, 10pt bold).
     - Site Code: e.g. `MI7` (22pt bold, `#FFFFFF`).
     - Location & City: 13pt bold `#FFFFFF`, with sub-location in 11pt `#94A3B8`.
     - Technical Specs Grid:
       - Media Type / Subtype (e.g. `Billboard — Frontlit`)
       - Dimensions: `W × H ft` and `Area sq ft`
       - Facing & Orientation
     - Audience Metrics (if enabled & available):
       - Reach & OTS impressions
       - LTS Score / Rating
     - Commercials (if enabled):
       - Total monthly investment formatted in INR (`₹8,58,640 / mo`).
   - **Slide Footer**: `"Slide 03 / 08"` right-aligned.

4. **Closing Slide Layout**:
   - Centered headline: `"Thank You"` (`#FFFFFF`, 38pt bold).
   - Campaign Summary card: Total sites, cities covered, combined reach, total estimated investment.
   - Next steps / contact disclaimer.

---

### B. Classic Theme
1. **Color Palette**:
   - Background: Pure White `#FFFFFF`.
   - Text Primary: Charcoal Navy `#0F172A`.
   - Text Muted: Slate `#64748B`.
   - Accent: Classic Royal Blue `#2563EB`.
2. **Layout**:
   - Clean centered layout with photo framed in light gray (`#F1F5F9`) and organized specification table below or beside.

---

## 4. Asset Fetching & Image Pipeline

1. **Resolution & Fetching**:
   - For each site, inspect `image_url`:
     - If local/S3 path: Read object bytes via `boto3` client `get_object(Bucket, Key)`.
     - If HTTP/HTTPS URL: Download asynchronously via `httpx.AsyncClient(timeout=10.0)`.
   - Wrap raw bytes into `io.BytesIO`.
2. **Aspect Ratio Preservation**:
   - Open image in-memory using `Pillow` (`PIL.Image.open`).
   - Extract `(img_w, img_h)`.
   - Compute contain-fit dimensions inside the target bounding box `(box_w, box_h)`:
     \[
     \text{scale} = \min\left(\frac{\text{box\_w}}{\text{img\_w}}, \frac{\text{box\_h}}{\text{img\_h}}\right)
     \]
     \[
     w = \text{img\_w} \times \text{scale}, \quad h = \text{img\_h} \times \text{scale}
     \]
     \[
     x = \text{box\_x} + \frac{\text{box\_w} - w}{2}, \quad y = \text{box\_y} + \frac{\text{box\_h} - h}{2}
     \]
   - Insert picture shape via `slide.shapes.add_picture(image_stream, x, y, width=w, height=h)`.

---

## 5. Storage, S3 Upload & Delivery

1. **Local Output Directory**:
   - Ensure directory `exports/` exists at the root of `media-in-mcp`.
   - Sanitize file name: `campaign_deck_<slug>_<YYYYMMDD_HHMMSS>.pptx`.
   - Save presentation file to disk.
2. **S3 Upload & Presigned URL**:
   - Upload file buffer to `s3://<AWS_BUCKET>/campaign-decks/<file_name>` with MIME type `application/vnd.openxmlformats-officedocument.presentationml.presentation`.
   - Generate S3 presigned URL for `get_object` with configured TTL (default 900s).
   - If S3 upload fails due to network or credential issues, catch gracefully, log warning, and return local file path with `s3_download_url: null`.

---

## 6. Error Handling & Edge Cases

1. **No Valid Sites**:
   - If `site_identifiers` is empty or none of the provided codes/UUIDs exist in the database, return `StandardResponse.error_response(code="NO_VALID_SITES", message="No valid media inventory sites found for the given identifiers")`.
2. **Partial Valid Sites**:
   - If 3 out of 5 codes exist, generate the deck for the 3 valid sites and include a `"warnings"` array specifying which identifiers were missing.
3. **Missing or Broken Images**:
   - Fall back to clean dark placeholder box labeled `"Site Photo Pending / Unavailable"`. Never crash the deck generation.
4. **Missing Optional Fields**:
   - When orientation, facing, dimensions, or audience metrics are null in the database, display `"—"` or omit cleanly rather than raising `AttributeError` or printing `"None"`.

---

## 7. Implementation Architecture

New & modified files:
- `requirements.txt`: Add `python-pptx>=1.0.2` and `Pillow>=10.4.0`.
- `mcp_server/services/deck_service.py`: `DeckBuilderService` containing:
  - Theme definitions (`EditorialTheme`, `ClassicTheme`)
  - Image downloader and dimension calculator
  - Slide builders (`build_cover_slide`, `build_site_slide`, `build_summary_slide`)
  - Deck compiler and S3 uploader
- `mcp_server/tools/generate_campaign_deck.py`: MCP tool handler exposing parameters, executing database queries, invoking `DeckBuilderService`, and formatting `StandardResponse`.
- `mcp_server/tools/__init__.py`: Register `generate_campaign_deck` with `MCPServer`.
- `tests/test_deck_service.py`: Unit tests for theme rendering, slide math, image containment, and S3 upload mocking.
- `tests/test_live_system.py`: Update to include live verification of `generate_campaign_deck`.
