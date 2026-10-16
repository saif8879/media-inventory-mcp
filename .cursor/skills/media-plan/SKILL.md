---
name: media-plan
description: >-
  Builds an OOH media plan from the media-inventory MCP and always prints the
  full recommended inventory and nearby competitor media as tables. Use when
  the user asks to build, make, plan, or recommend a media plan, campaign plan,
  or OOH plan for a brand, city, or budget (for example "Build a media plan
  for Croma in Mumbai with a ₹20 lakh budget"), even if they do not mention
  competitors, tables, billboards, or a radius.
---

# Media plan

A media-plan request always includes nearby competitor media. The user does not need to ask for competitors or a table.

## Call the tool

Use the `generate_media_plan` tool on the media-inventory MCP. Do not invent sites, prices, coordinates, or competitors. Do not answer the plan from `search_media` alone.

Parse the brief:

- `brand` and `city` are required. If either is missing, ask only for that.
- `budget` is INR. `₹20 lakh` or `20 lakh` is `2000000`. `1 crore` is `10000000`. A bare rupee amount is used as given.
- `media_type` only when the user names one (`billboard`, `gantry`, `bus shelter`). Otherwise pass an empty string. Billboard, billboards, and billording are `billboard`.
- For a billboard brief, do not pass `competitor_media_type`. Inventory stays billboards. Competitor tables include every nearby competitor type inside the radius (hoarding, bus shelter, digital, and the rest), ordered by distance from that site's latitude and longitude. Show each row's stored media type. Pass `competitor_media_type` only when the user names a competitor type other than billboard.
- Omit `radius_km` so `.env` `COMPETITOR_DEFAULT_RADIUS_KM` applies. Pass a radius only when the user gives one.
- Pass `max_competitors` `50` and `max_sites` `25` unless the user sets a smaller number. These are the tool caps. The goal is the full result, not a sample.

## Print the result in this order

Use Indian grouping for money (`₹19,22,000`). Keep coordinates and `distance_km` exactly as returned. Do not shorten a list that has rows.

Leave out `none_in_radius`, `none_in_catalog`, and `skipped_missing_coordinates`. Do not print those statuses, their messages, or a blank competitor row. If every recommended site has an empty `nearby_competitors` list, omit the Competitors section completely.

If the tool returns `COMPETITOR_DATA_UNAVAILABLE`, say the competitor file could not be read. Do not show an empty competitor table.

### 1. Plan

| Brand | City | Budget | Media type | Radius (km) |
| --- | --- | --- | --- | --- |

Media type is the requested type, or `All types` when the user did not name one. Radius is `competitor_search.radius_km`.

### 2. Budget

| Total budget | Estimated spend | Remaining |
| --- | --- | --- |

`Estimated spend` is `budget_summary.estimated_spend`, the sum of every recommended site.

### 3. Recommended sites

One row per recommended site. Keep a column when its value is null.

| Code | Name | Media type | Location | Latitude | Longitude | Estimated cost | Reach | OTS | Nearby |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

`Nearby` is the number of competitor rows for that site. `0` is allowed here. This table is the plan. It stays even when every nearby count is 0.

### 4. Competitors

Include this section only when at least one site has a non-empty `nearby_competitors` list.

For each of those sites, add a heading `### {inventory_code} — {location}` and one table of that site's competitors only. Skip every other site.

| Competitor | Source | Media type | Location | Latitude | Longitude | Distance (km) | Minimum billing |
| --- | --- | --- | --- | --- | --- | --- | --- |

### 5. Not included

Add this table only when `excluded_inventory` is non-empty.

| Code | Location | Reason |
| --- | --- | --- |

## After the tables

One short line per recommended site from `selection_reason`, without any sentence that says no competitor was found. Do not calculate CPM, reach, or a rate the tool did not return.
