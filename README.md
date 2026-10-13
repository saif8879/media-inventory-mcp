# Media Inventory Model Context Protocol (MCP) Server

A production-ready, independently deployable **Model Context Protocol (MCP)** server that exposes Out-of-Home (OOH) physical and digital advertising inventory, quotation history, AdMavin audience intelligence, and secure Amazon S3 photographic assets to AI assistants such as Claude, Cursor, and ChatGPT.

---

## 1. Architecture Overview & Request Flow

The server connects AI models directly to the existing Media Inventory database and private Amazon S3 asset bucket via the **Model Context Protocol** over **Streamable HTTP / SSE (Server-Sent Events)**.

```
                              +---------------------------------------+
                              | AI Client (Claude Desktop / Cursor)   |
                              +-------------------+-------------------+
                                                  |
                                                  | HTTP POST /mcp
                                                  | Header: Authorization: Bearer <access token>
                                                  v
                              +---------------------------------------+
                              | Media Inventory MCP Server            |
                              | (FastAPI + Starlette SSE on port 8090)|
                              +-------------------+-------------------+
                                                  |
                     +----------------------------+----------------------------+
                     |                                                         |
                     v                                                         v
     +-------------------------------+                         +-------------------------------+
     | MCP Tool Layer (Pydantic v2)  |                         |  Auth Middleware & Guardrails |
     | - search_media                |                         | - Google Workspace sign-in   |
     | - get_media_details           |                         |  - Rate bounds (limit <= 100) |
     | - list_media                  |                         |  - Traversal & error safety   |
     | - get_media_statistics       |                         +-------------------------------+
     | - get_media_asset             |
     | - find_related_media          |
     | - generate_campaign_deck      |
     +---------------+---------------+
                     |
  +------------------+------------------+
  |                                     |
  v                                     v
+-----------------------------+   +-----------------------------+
| PostgreSQL (AWS RDS)        |   | Amazon S3 (Private Bucket)  |
| - media_inventory           |   | - buzzomni-media-inventory  |
| - media_inventory_prices    |   | - boto3 presigned URLs      |
| - admavin_media_inventory   |   | - Time-bounded TTL (900s)   |
+-----------------------------+   +-----------------------------+
```

### Key Highlights
* **Zero Duplication**: Leverages existing database tables, columns, and data conventions.
* **Separation of Concerns**: Runs as a separate process on a dedicated port (default `8090`), leaving the existing FastAPI backend (`8080`) and Next.js frontend (`3000`) untouched.
* **Streamable HTTP / SSE**: Compatible with remote MCP deployments through reverse proxies (Nginx / Caddy).
* **Private S3 Assets**: S3 bucket remains strictly private. Assets are delivered using short-lived time-bounded presigned URLs. AWS credentials are never exposed in tool responses.

---

## 2. Implemented MCP Tools & Schemas

All tools return a standardized response format:
```json
{
  "success": true,
  "data": ...,
  "pagination": { "offset": 0, "limit": 20, "total": 1 },
  "error": null
}
```

### 1. `search_media`
* **Description**: Search OOH media inventory (billboards, unipoles, gantries, bus shelters) by keyword query, city, media type, concessionaire/owner, cost bounds, and audience metrics (reach, OTS).
* **Parameters**:
  * `query` *(string, optional)*: Keyword matched against `inventory_code`, `city`, `area`, `location`, `category`, `media_type`, `sub_type`, `media_owner`.
  * `city` *(string, optional)*: Filter by exact city name (case-insensitive, e.g. "Mumbai").
  * `media_type` *(string, optional)*: Filter by media type (e.g. "BillBoard", "Gantry").
  * `media_owner` *(string, optional)*: Filter by concessionaire name.
  * `min_total_cost` *(float, optional)*: Minimum total cost in INR.
  * `max_total_cost` *(float, optional)*: Maximum total cost in INR.
  * `min_reach` *(int, optional)*: Minimum monthly unique reach.
  * `min_ots` *(int, optional)*: Minimum Opportunity-to-See (OTS).
  * `has_image` *(bool, optional)*: Restrict results to records with site photos.
  * `offset` *(int, default: 0)*: Result offset.
  * `limit` *(int, default: 20, max: 100)*: Result limit.

### 2. `get_media_details`
* **Description**: Retrieve complete details for a single media inventory site by its unique inventory code (e.g. 'MI1', 'MI42') or UUID.
* **Parameters**:
  * `identifier` *(string, required)*: Unique inventory code (e.g. `"MI1"`) or UUID.
  * `include_price_history` *(bool, default: true)*: Include quotation negotiation history and comments.
  * `include_audience_metrics` *(bool, default: true)*: Include AdMavin demographic breakdown (gender, age, income), traffic profile, and nearby landmarks.

### 3. `list_media`
* **Description**: List and filter media inventory records with structured filters with pagination.
* **Parameters**:
  * `city`, `category`, `media_type`, `sub_type`, `orientation`, `media_owner` *(strings, optional)*.
  * `is_synced` *(bool, optional)*: Excel import status.
  * `admavin_sync_status` *(string, optional)*: Sync status (`"ok"`, `"partial"`, `"failed"`, `"none"`).
  * `offset` *(int, default: 0)*, `limit` *(int, default: 20, max: 100)*.

### 4. `get_media_statistics`
* **Description**: Calculate aggregate statistics: total sites, active cities, media types, cost metrics (avg, min, max), audience reach totals, and optional categorical breakdowns.
* **Parameters**:
  * `city` *(string, optional)*: Restrict aggregates to a specific city.
  * `media_type` *(string, optional)*: Restrict aggregates to a specific media type.
  * `breakdown_by` *(string, optional)*: Grouping dimension: `"city"`, `"media_type"`, `"category"`, or `"media_owner"`.

### 5. `get_media_asset`
* **Description**: Retrieve the photograph asset reference and generate a short-lived S3 presigned URL for a media site.
* **Parameters**:
  * `identifier` *(string, required)*: The site inventory code or UUID.
  * `expires_in` *(int, default: 900, min: 60, max: 3600)*: Expiry time for the signed URL in seconds.

### 6. `find_related_media`
* **Description**: Discover related or nearby media sites using geographic proximity (Haversine distance) from a reference site or GPS coordinates within a radius (km).
* **Parameters**:
  * `reference_identifier` *(string, optional)*: Reference site inventory code (e.g. `"MI1"`).
  * `latitude` / `longitude` *(float, optional)*: Center GPS coordinates (if not providing a reference site).
  * `radius_km` *(float, default: 5.0, max: 50.0)*: Radius in kilometers.
  * `same_media_type` *(bool, default: false)*: Restrict results to the same media type.
  * `limit` *(int, default: 10, max: 50)*: Maximum results.

### 7. `generate_campaign_deck`
* **Description**: Generate an Out-of-Home (OOH) campaign pitch presentation deck in 16:9 widescreen PPTX format (`.pptx`, 13.333" x 7.50") for selected media inventory sites. Embeds high-resolution site photographs, technical specifications (dimensions, illumination), location attributes, AdMavin audience intelligence, and quotation costs. Delivers both local file path and a private S3 presigned download URL.
* **Layout & Structure**:
  * **16:9 Widescreen Layout**: Engineered for modern enterprise displays (`13.333"` x `7.50"`).
  * **Color Themes**:
    * `"editorial"` (Default): Sophisticated dark palette (deep navy `#0B1F3A`, panel `#112A4D`, electric blue accent `#4B8EFF`).
    * `"classic"`: Minimalist executive light palette (clean white `#FFFFFF`, cool slate `#F4F6F9`, dark navy text `#0F172A`, vibrant blue accent `#2563EB`).
  * **Cover Slide**: Campaign kicker, title, client subtitle, date badge, and campaign summary metrics.
  * **Site Detail Slides**: One slide per inventory site featuring an aspect-ratio-preserving photo container (contain-fit with letterboxing prevention), site identifier badge, technical dimensions, illumination status, location highlights, AdMavin audience metrics grid, and commercial pricing card.
  * **Closing Slide**: Executive campaign recap card aggregating total sites, target cities, combined audience reach, and total monthly investment with confidentiality notice.
* **Parameters**:
  * `site_identifiers` *(list of strings, required)*: List of site inventory codes (e.g. `["MI1", "MI7"]`) or UUIDs.
  * `campaign_title` *(string, default: "Campaign Proposal")*: Title for the campaign deck.
  * `client_name` *(string, optional, default: "")*: Name of the client or brand.
  * `theme` *(string, default: "editorial")*: Color theme (`"editorial"` or `"classic"`).
  * `include_commercials` *(bool, default: true)*: Include pricing cards, monthly rate, and quotation rates.
  * `include_audience_metrics` *(bool, default: true)*: Include monthly reach, impressions, OTS, and AdMavin audience metrics.
  * `expires_in` *(int, default: 900, min: 60, max: 3600)*: Expiry time in seconds for the S3 presigned download URL.
* **Output Payload**:
  ```json
  {
    "success": true,
    "data": {
      "file_name": "campaign_deck_proposal_20261009_120000.pptx",
      "local_file_path": "/path/to/media-in-mcp/exports/campaign_deck_proposal_20261009_120000.pptx",
      "s3_download_url": "https://buzzomni-media-inventory.s3.ap-south-1.amazonaws.com/campaign-decks/campaign_deck_...pptx?...",
      "expires_in_seconds": 900,
      "site_count": 2,
      "theme": "editorial",
      "summary": {
        "site_count": 2,
        "cities": ["Mumbai"],
        "total_monthly_cost": 450000.0,
        "total_reach": 850000
      },
      "warnings": []
    },
    "error": null
  }
  ```

---

## 3. Security & Safety

1. **Authentication**:
   * HTTP clients (`/mcp`, `/sse`, `/messages`) sign in with Google. Only a verified `@wrap2earn.com` Workspace account is accepted.
   * The browser opens Google's own sign-in. This server then gives the MCP client a short-lived access token.
   * A missing or expired token receives `401` and a `WWW-Authenticate` header so the client can start sign-in again.
   * The old shared `MCP_API_KEY`, `X-MCP-Key`, and `?token=` values are not accepted.
   * Local stdio (running this Python process on your own machine) stays open. There is no browser in that mode.
   * `/health` stays open for load balancer probes.
   * On startup the server creates `oauth_clients`, `oauth_auth_codes`, and `oauth_refresh_tokens` in the same Postgres database. The database user needs permission to create those tables.
2. **Private S3 Assets**:
   * S3 bucket remains strictly private.
   * `boto3` generates time-bound Presigned URLs with standard expiration (default 15 minutes, maximum 1 hour).
   * Path traversal (`..`) attempts in object keys are rejected.
3. **Database Guardrails**:
   * All queries are strictly parameterized using SQLAlchemy 2.0 (no SQL injection vulnerabilities).
   * Enforced upper bounds on `limit` (max 100) prevent unbounded table scans.
4. **Read-Only Assurance**:
   * Write and mutation tools (`create`, `update`, `delete`) are disabled to protect production data from unintended modifications.

---

## 4. Environment Configuration (`.env`)

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL async connection string (`postgresql+asyncpg://...`) | *Required* |
| `MCP_SERVER_HOST` | Host to bind the MCP server | `0.0.0.0` |
| `MCP_SERVER_PORT` | Port for the MCP server | `8090` |
| `MCP_PUBLIC_URL` | Public HTTPS origin of this server, no trailing slash | *Required for HTTP* |
| `GOOGLE_CLIENT_ID` | Google OAuth client id (Internal app) | *Required for HTTP* |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret | *Required for HTTP* |
| `GOOGLE_HOSTED_DOMAIN` | Workspace domain allowed to sign in | `wrap2earn.com` |
| `OAUTH_JWT_SECRET` | Secret used to sign MCP access tokens (32+ bytes) | *Required for HTTP* |
| `AWS_ACCESS_KEY_ID` | AWS access key for S3 | *Required for S3* |
| `AWS_SECRET_ACCESS_KEY`| AWS secret key for S3 | *Required for S3* |
| `AWS_BUCKET` | S3 bucket name | `buzzomni-media-inventory` |
| `AWS_DEFAULT_REGION` | AWS region | `ap-south-1` |
| `PRESIGNED_URL_EXPIRY` | Presigned URL duration in seconds | `900` |

---

## 5. Local Development Instructions

### 1. Setup Virtual Environment
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your PostgreSQL and AWS credentials
```

### 3. Run Automated Tests
```bash
pytest -v
```

### 4. Start the MCP Server Locally
```bash
python -m mcp_server.server
# or
uvicorn mcp_server.server:app --host 0.0.0.0 --port 8090 --reload
```

Test health check:
```bash
curl http://localhost:8090/health
```

---

## 6. Production Deployment Instructions

### Option A: Docker Container (Recommended)

1. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Ensure DATABASE_URL, Google OAuth settings, and AWS credentials are set
   ```

2. **Build and Start with Docker Compose**:
   ```bash
   docker compose up -d --build
   ```

3. **Check Container Status and Health**:
   ```bash
   docker compose ps
   curl http://localhost:8090/health
   ```

4. **View Container Logs**:
   ```bash
   docker compose logs -f
   ```

5. **Stop Container**:
   ```bash
   docker compose down
   ```

---

### Option B: Native Ubuntu Systemd Service

The repository includes a ready-to-use systemd unit file and deployment script under `deploy/`.

#### Automated Deployment
```bash
bash deploy/deploy.sh
```

#### Manual Deployment Steps
1. Create application directory:
   ```bash
   sudo mkdir -p /documents/media-inventory/mcp
   sudo chown -R ubuntu:ubuntu /documents/media-inventory/mcp
   ```
2. Copy files and install dependencies:
   ```bash
   cd /documents/media-inventory/mcp
   python3.12 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
3. Secure the environment file:
   ```bash
   chmod 600 /documents/media-inventory/mcp/.env
   ```
4. Install and start the systemd service:
   ```bash
   sudo cp deploy/media-inventory-mcp.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable media-inventory-mcp
   sudo systemctl start media-inventory-mcp
   sudo systemctl status media-inventory-mcp
   ```

---

## 7. AI Client Configuration Examples

### Claude Desktop (`claude_desktop_config.json`)

**Option A: Direct stdio (Recommended — Local Python Environment)**
```json
{
  "mcpServers": {
    "media-inventory": {
      "command": "/Users/saifidrisi/Documents/media-in-mcp/.venv/bin/python",
      "args": [
        "-m",
        "mcp_server"
      ]
    }
  }
}
```

**Option B: Remote HTTP (Google sign-in)**
```json
{
  "mcpServers": {
    "media-inventory": {
      "url": "https://mcp.example.com/mcp"
    }
  }
}
```
The client opens Google sign-in the first time it connects. Use the server's public HTTPS URL. Do not put a token in the URL.

### Google Cloud setup
In the wrap2earn Google Cloud organization:

1. Open **APIs & Services → OAuth consent screen** and set the user type to **Internal**.
2. Create an OAuth client ID of type **Web application**.
3. Add this authorized redirect URI: `https://<your-host>/auth/google/callback`
4. Put the client id, client secret, public URL, hosted domain, and JWT secret in `.env`.

> **NeuroAI Media Planner System Prompt for Claude**:
> See [`prompts/neuroai_media_planner_system_prompt.md`](prompts/neuroai_media_planner_system_prompt.md) for full instructions to configure Claude as a conversational OOH Media Planner that digests campaign briefs, evaluates AdMavin metrics, and generates presentations.

### Cursor IDE MCP Configuration
Add to `.cursor/mcp.json` or Cursor Settings → MCP Servers:
```json
{
  "mcpServers": {
    "media-inventory": {
      "url": "https://mcp.example.com/mcp"
    }
  }
}
```

---

## 8. Example Natural Language Prompts

* *"Find all Front Lit billboards in Mumbai near Marine Drive."*
* *"Show me the media sites with monthly reach greater than 200,000 in Delhi."*
* *"What is the breakdown of sites by media type and total cost across all cities?"*
* *"Get details and recent quotation price history for inventory site MI42."*
* *"Get the photo asset link for MI1."*
* *"Find all media sites within 3 km of site MI12 and tell me their distance."*
* *"Are there any digital LED screens in Bangalore with audience traffic ratings above 4.0?"*
* *"Generate a 16:9 widescreen campaign presentation deck in editorial theme for sites MI1 and MI7 for client Nike."*

---

## 9. Assumptions & Limitations

1. **Read-Only Scope**: In accordance with the safety requirements, write/mutation operations (such as creating inventory sites or modifying rates) are disabled until authorization workflows are specified.
2. **AdMavin Join**: Correlates `media_inventory` and `admavin_media_inventory` on `(round(latitude, 6), round(longitude, 6), derived_lit)`. Sites without coordinates or without AdMavin sync will display `null` for audience metrics.
3. **S3 Storage**: Photographic assets are referenced by relative object key (e.g. `media-inventory/MI1/...`). The presigned URL generator returns temporary signed URLs with configurable expiration (default 15 minutes).
# media-inventory-mcp
