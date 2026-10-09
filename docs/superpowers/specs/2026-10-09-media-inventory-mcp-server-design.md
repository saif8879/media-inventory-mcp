# Production-Ready Media Inventory MCP Server — Design Specification

## 1. Executive Summary & Reality Check

This specification defines the architecture, tools, security model, and implementation standards for a production-grade **Model Context Protocol (MCP)** server for the **Media Inventory** system.

### Reality Check: Business Domain Mapping
While high-level requests often refer generically to digital media concepts (creators, campaigns, videos), the Media Inventory system is an **Out-of-Home (OOH) physical and digital media inventory management platform** (Billboards, Gantries, Unipoles, Bus Shelters, LED screens, Mall Media).

The MCP server connects AI assistants (Claude, ChatGPT, Cursor) directly to:
1. **Physical Media Inventory** (`media_inventory` table): Geographic locations, dimensions, illumination types (Front Lit, Back Lit, Non-Lit, LED), display and fabrication costs, ownership, and photo assets.
2. **Quotation History** (`media_inventory_price_history` table): Historical quotations, client negotiations, and internal notes.
3. **Audience & Traffic Intelligence** (`admavin_media_inventory` table): AdMavin metrics including Gross Reach, Opportunity-to-See (OTS), Average Dwell Time, Location Traffic Score (LTS rating & score), Demographics (Gender, Age, SEC Income groups), and Nearby Landmarks (banks, malls, restaurants).
4. **Asset Management (Amazon S3)**: Secure retrieval of media photographs via time-bounded presigned URLs.

---

## 2. Architecture & Request Flow

```
                                      +-------------------------------+
                                      | AI Client (Claude / ChatGPT) |
                                      +---------------+---------------+
                                                      |
                                                      | SSE / Streamable HTTP
                                                      | Header: Authorization: Bearer <token>
                                                      v
                                      +-------------------------------+
                                      |  FastAPI / Starlette App      |
                                      |  (MCP Server on port 8090)    |
                                      +---------------+---------------+
                                                      |
                         +----------------------------+----------------------------+
                         |                                                         |
                         v                                                         v
         +-------------------------------+                         +-------------------------------+
         | MCP Tool Layer (Pydantic v2)  |                         |  Auth & Security Middleware   |
         | - search_media                |                         |  - Token verification         |
         | - get_media_details           |                         |  - Rate limiting & bounds     |
         | - list_media                  |                         |  - Error sanitization         |
         | - get_media_statistics       |                         +-------------------------------+
         | - get_media_asset             |
         | - find_related_media          |
         +---------------+---------------+
                         |
      +------------------+------------------+
      |                                     |
      v                                     v
+-----------------------------+   +-----------------------------+
| Shared DB Layer             |   | S3 Storage Service          |
| - SQLAlchemy Async Engine   |   | - boto3 presigned URL gen   |
| - asyncpg Connection Pool   |   | - Non-public bucket access  |
| - PostgreSQL (RDS)          |   | - Configurable TTL (900s)   |
+-----------------------------+   +-----------------------------+
```

### Transport & Packaging
* **Protocol**: Model Context Protocol (MCP) using Python SDK (`mcp>=1.0.0`).
* **Transport**: **Streamable HTTP (SSE - Server-Sent Events)** powered by FastAPI / Starlette, enabling remote deployment and standard HTTP reverse proxy compatibility (Nginx / Caddy).
* **Port**: Configurable via `MCP_SERVER_PORT` (default `8090`), avoiding conflicts with the backend (`8080`) and frontend (`3000`).
* **Process Separation**: Runs as an independent process (e.g. systemd service `media-inventory-mcp`), keeping the existing FastAPI backend (`media-inventory-backend`) untouched.

---

## 3. Database & Service Integration

Instead of duplicating database connection logic or schemas:
* Connects directly via async SQLAlchemy engine using PostgreSQL connection pool (`pool_pre_ping=True`, configurable pool sizes).
* Reuses existing schema column definitions and naming conventions:
  * `media_inventory`
  * `media_inventory_price_history`
  * `admavin_media_inventory`
* AdMavin join logic: Correlates `media_inventory` and `admavin_media_inventory` on `(round(latitude, 6), round(longitude, 6), derived_lit)`.

---

## 4. MCP Tool Inventory (Read-Only Specification)

Every tool returns structured responses conforming to:
```json
{
  "success": true,
  "data": ...,
  "pagination": {
    "offset": 0,
    "limit": 20,
    "total": 100
  },
  "error": null
}
```

### Tool 1: `search_media`
* **Purpose**: Free-text keyword search across inventory code, city, area, location, media type, and owner, with optional numerical filters.
* **Input Parameters**:
  * `query` (str, optional): Keyword query matched against `inventory_code`, `city`, `location`, `category`, `media_type`, `sub_type`, `media_owner`.
  * `city` (str, optional): Exact filter for city (e.g. "Mumbai", "Delhi").
  * `media_type` (str, optional): Media type (e.g. "BillBoard", "Gantry", "Unipole").
  * `media_owner` (str, optional): Filter by concessionaire / vendor.
  * `min_total_cost` (float, optional): Minimum total cost.
  * `max_total_cost` (float, optional): Maximum total cost.
  * `min_reach` (int, optional): Minimum monthly reach.
  * `min_ots` (int, optional): Minimum Opportunity to See.
  * `has_image` (bool, optional): Restrict to sites with photographs.
  * `offset` (int, default 0, min 0): Pagination offset.
  * `limit` (int, default 20, min 1, max 100): Result count limit.
* **Returns**: Paginated list of media summary records with identification, dimensions, pricing, audience metrics, and coordinates.

### Tool 2: `get_media_details`
* **Purpose**: Retrieve comprehensive information for a single media inventory site.
* **Input Parameters**:
  * `identifier` (str, required): Either the unique `inventory_code` (e.g., `"MI1"`, `"MI42"`) or UUID string (`id`).
  * `include_price_history` (bool, default true): Include quotation negotiation history.
  * `include_audience_metrics` (bool, default true): Include AdMavin demographic breakdowns, nearby landmarks, and LTS metrics.
* **Returns**: Complete site details, pricing, recent quotations, AdMavin demographics (age, gender, SEC income), traffic profile, and landmarks. Returns clear error if not found.

### Tool 3: `list_media`
* **Purpose**: Retrieve paginated media records using structured attributes and filter criteria.
* **Input Parameters**:
  * `city` (str, optional): City name.
  * `category` (str, optional): Category (e.g., "Outdoor", "Transit").
  * `media_type` (str, optional): Media type.
  * `sub_type` (str, optional): Lighting sub-type (e.g., "Front Lit", "Back Lit", "LED").
  * `orientation` (str, optional): Facing orientation.
  * `media_owner` (str, optional): Media concessionaire name.
  * `is_synced` (bool, optional): Excel-uploaded source status.
  * `admavin_sync_status` (str, optional): "ok", "partial", "failed", or "none".
  * `offset` (int, default 0, min 0): Pagination offset.
  * `limit` (int, default 20, min 1, max 100): Result page limit.
* **Returns**: Filtered media records and total count.

### Tool 4: `get_media_statistics`
* **Purpose**: Calculate aggregate statistics across the media inventory.
* **Input Parameters**:
  * `city` (str, optional): Restrict aggregates to a specific city.
  * `media_type` (str, optional): Restrict aggregates to a media type.
  * `breakdown_by` (str, optional): Grouping dimension: `"city"`, `"media_type"`, `"category"`, or `"media_owner"`.
* **Returns**: Total sites, city counts, average/min/max costs, total/average reach, and breakdown distributions.

### Tool 5: `get_media_asset`
* **Purpose**: Retrieve secure, short-lived presigned URLs for a site's photograph.
* **Input Parameters**:
  * `identifier` (str, required): The `inventory_code` or UUID `id`.
  * `expires_in` (int, default 900, min 60, max 3600): Expiry in seconds for the presigned URL.
* **Returns**: S3 object key, temporary presigned URL, expiration timestamp, and content format.

### Tool 6: `find_related_media`
* **Purpose**: Discover related sites by geographical proximity or similar specs.
* **Input Parameters**:
  * `reference_identifier` (str, optional): Site `inventory_code` or `id` to find neighbors for.
  * `latitude` (float, optional): Center latitude (if reference_identifier is not supplied).
  * `longitude` (float, optional): Center longitude (if reference_identifier is not supplied).
  * `radius_km` (float, default 5.0, min 0.1, max 50.0): Search radius in kilometers.
  * `same_media_type` (bool, default false): Restrict to the same media type.
  * `limit` (int, default 10, min 1, max 50): Max results.
* **Returns**: Ordered list of nearby sites with calculated distance in kilometers and reason for matching.

---

## 5. Security & Safety Plan

1. **Client Authentication**:
   * All requests to the MCP endpoint (`/mcp` or `/sse`) must supply `Authorization: Bearer <MCP_API_KEY>` or `X-MCP-Key: <MCP_API_KEY>`.
   * Unauthenticated or invalid requests receive 401 Unauthorized immediately.
2. **S3 Private Asset Protection**:
   * S3 bucket remains private with public access blocked.
   * `boto3` generates time-bound Presigned URLs with standard expiration (default 15 minutes, maximum 1 hour).
   * Credentials (AWS keys, secret keys, RDS password) are never included in outputs or error responses.
3. **Database Guardrails & Bounded Limits**:
   * Enforce hard upper bounds on `limit` (max 100) to prevent unbounded scans.
   * All queries parameterized via SQLAlchemy (no SQL injection vulnerabilities).
4. **Prompt Injection & Untrusted Data**:
   * Remarks, locations, vendor descriptions, and text fields are strictly inert JSON strings.
   * The AI prompt instructions instruct the model that content inside `data` represents retrieved inventory data, not instructions.
5. **No Write Operations**:
   * Write tools (`create`, `update`, `delete`) are completely disabled and omitted from tool registration in this phase.

---

## 6. Error Handling Strategy

Standardized error payload:
```json
{
  "success": false,
  "data": null,
  "pagination": null,
  "error": {
    "code": "ITEM_NOT_FOUND",
    "message": "Media inventory item 'MI999' was not found",
    "details": null
  }
}
```
Error codes:
* `UNAUTHORIZED`: Invalid or missing credentials.
* `INVALID_INPUT`: Validation failure on input schema.
* `ITEM_NOT_FOUND`: Target entity could not be located.
* `DATABASE_ERROR`: Sanitized database error.
* `STORAGE_ERROR`: S3 retrieval or presigning error.

---

## 7. Deployment Strategy

* Standalone FastAPI service running via Uvicorn.
* Dedicated systemd unit: `/etc/systemd/system/media-inventory-mcp.service`.
* Environment file: `/documents/media-inventory/mcp/.env` with chmod 600.
* Supervised restart policy: `Restart=always`, `RestartSec=5`.
* Health check endpoint: `GET /health` returning `{"status": "ok", "service": "media-inventory-mcp"}`.
