from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import io
import logging
from pathlib import Path
import re
from typing import Any
import urllib.parse

import boto3
from botocore.exceptions import BotoCoreError, ClientError
import httpx
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from mcp_server.config import get_settings

logger = logging.getLogger("mcp_server.deck")


@dataclass(frozen=True)
class ThemeColors:
    name: str
    bg_color: RGBColor
    card_bg: RGBColor
    photo_bg: RGBColor
    accent_color: RGBColor
    text_primary: RGBColor
    text_muted: RGBColor
    border_color: RGBColor


EDITORIAL_THEME = ThemeColors(
    name="editorial",
    bg_color=RGBColor(11, 31, 58),        # Dark Navy #0B1F3A
    card_bg=RGBColor(17, 42, 77),         # Deep Slate Navy #112A4D
    photo_bg=RGBColor(22, 32, 46),        # Charcoal #16202E
    accent_color=RGBColor(75, 142, 255),  # Electric Blue #4B8EFF
    text_primary=RGBColor(255, 255, 255), # Pure White #FFFFFF
    text_muted=RGBColor(148, 163, 184),   # Slate #94A3B8
    border_color=RGBColor(30, 58, 95),    # Slate #1E3A5F
)

CLASSIC_THEME = ThemeColors(
    name="classic",
    bg_color=RGBColor(255, 255, 255),     # Pure White #FFFFFF
    card_bg=RGBColor(248, 250, 252),      # Light Gray #F8FAFC
    photo_bg=RGBColor(241, 245, 249),     # Slate Light #F1F5F9
    accent_color=RGBColor(37, 99, 235),   # Royal Blue #2563EB
    text_primary=RGBColor(15, 23, 42),    # Charcoal Navy #0F172A
    text_muted=RGBColor(100, 116, 139),   # Slate #64748B
    border_color=RGBColor(226, 232, 240), # Light Border #E2E8F0
)


def format_inr(amount: float | int | None) -> str:
    """Format a monetary amount in Indian numbering format (e.g. 4,50,000)."""
    if amount is None:
        return "—"
    try:
        value = int(round(float(amount)))
        if value < 0:
            return "-" + format_inr(abs(value))
        s = str(value)
        if len(s) <= 3:
            return s
        last_three = s[-3:]
        remaining = s[:-3]
        groups = []
        while len(remaining) > 2:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            groups.insert(0, remaining)
        return ",".join(groups) + "," + last_three
    except Exception:
        return str(amount)


def format_number(val: int | float | None) -> str:
    """Format integer with thousands separator."""
    if val is None:
        return "—"
    try:
        return f"{int(val):,}"
    except Exception:
        return str(val)


class DeckBuilderService:
    def __init__(
        self,
        s3_client: Any = None,
        bucket: str | None = None,
        exports_dir: Path | str | None = None,
    ) -> None:
        settings = get_settings()
        self.bucket = bucket or settings.aws_s3_bucket
        if s3_client is not None:
            self._s3_client = s3_client
        else:
            kwargs: dict[str, Any] = {"region_name": settings.aws_s3_region}
            if settings.aws_access_key_id and settings.aws_secret_access_key:
                kwargs["aws_access_key_id"] = settings.aws_access_key_id
                kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
            self._s3_client = boto3.client("s3", **kwargs)

        if exports_dir is not None:
            self.exports_dir = Path(exports_dir)
        else:
            self.exports_dir = Path(__file__).resolve().parent.parent.parent / "exports"
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def compute_contain_fit(
        self,
        img_w: float,
        img_h: float,
        box_x: float,
        box_y: float,
        box_w: float,
        box_h: float,
    ) -> tuple[float, float, float, float]:
        """Compute contain-fit dimensions and centered offsets inside bounding box."""
        if img_w <= 0 or img_h <= 0 or box_w <= 0 or box_h <= 0:
            return (box_x, box_y, box_w, box_h)

        scale = min(box_w / img_w, box_h / img_h)
        w = img_w * scale
        h = img_h * scale
        x = box_x + (box_w - w) / 2.0
        y = box_y + (box_h - h) / 2.0
        return (x, y, w, h)

    def fetch_image(
        self, image_url: str | None
    ) -> tuple[io.BytesIO | None, tuple[int, int] | None]:
        """Fetch image bytes into memory and extract native dimensions (width, height)."""
        if not image_url or not str(image_url).strip():
            return None, None

        cleaned = str(image_url).strip()
        raw_bytes: bytes | None = None

        try:
            if cleaned.startswith(("http://", "https://")):
                # Check if it points to our configured S3 bucket
                if self.bucket and self.bucket in cleaned:
                    try:
                        parsed = urllib.parse.urlparse(cleaned)
                        key = urllib.parse.unquote(parsed.path.lstrip("/"))
                        if key.startswith(f"{self.bucket}/"):
                            key = key[len(self.bucket) + 1 :]
                        resp = self._s3_client.get_object(Bucket=self.bucket, Key=key)
                        raw_bytes = resp["Body"].read()
                    except Exception:
                        raw_bytes = None

                # Fallback to direct HTTP download
                if not raw_bytes:
                    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                        resp = client.get(cleaned)
                        if resp.status_code == 200:
                            raw_bytes = resp.content

            elif Path(cleaned).exists() and Path(cleaned).is_file():
                raw_bytes = Path(cleaned).read_bytes()
            elif self.bucket:
                # S3 key
                normalized_key = urllib.parse.unquote(cleaned.lstrip("/"))
                resp = self._s3_client.get_object(Bucket=self.bucket, Key=normalized_key)
                raw_bytes = resp["Body"].read()

            if raw_bytes:
                with Image.open(io.BytesIO(raw_bytes)) as img:
                    w, h = img.size
                return io.BytesIO(raw_bytes), (w, h)
        except Exception as exc:
            logger.warning(
                "failed_to_fetch_image_for_deck",
                extra={"image_url": cleaned, "error": str(exc)},
            )

        return None, None

    def build_deck(
        self,
        sites: list[dict[str, Any]],
        campaign_title: str = "Campaign Proposal",
        client_name: str = "",
        theme: str = "editorial",
        include_commercials: bool = True,
        include_audience_metrics: bool = True,
    ) -> tuple[bytes, dict[str, Any]]:
        """Build 16:9 widescreen PowerPoint presentation for the selected sites."""
        theme_colors = CLASSIC_THEME if theme.lower() == "classic" else EDITORIAL_THEME

        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.50)

        site_count = len(sites)
        total_monthly_cost = sum(
            float(s["total_cost"]) for s in sites if s.get("total_cost") is not None
        )
        total_reach = sum(
            int(s["admavin"]["reach"])
            for s in sites
            if s.get("admavin") and s["admavin"].get("reach") is not None
        )
        cities = sorted(list({str(s["city"]) for s in sites if s.get("city")}))

        summary: dict[str, Any] = {
            "site_count": site_count,
            "total_monthly_cost": round(total_monthly_cost, 2),
            "total_reach": total_reach,
            "cities": cities,
        }

        # 1. Cover Slide
        self._add_cover_slide(
            prs=prs,
            theme=theme_colors,
            campaign_title=campaign_title,
            client_name=client_name,
            site_count=site_count,
            cities=cities,
        )

        # 2. Site Slides
        total_slides = site_count + 2
        for idx, site in enumerate(sites):
            img_stream, img_dims = self.fetch_image(site.get("image_url"))
            self._add_site_slide(
                prs=prs,
                theme=theme_colors,
                site=site,
                idx=idx,
                total_sites=site_count,
                total_slides=total_slides,
                img_stream=img_stream,
                img_dims=img_dims,
                include_commercials=include_commercials,
                include_audience_metrics=include_audience_metrics,
            )

        # 3. Closing Slide
        self._add_closing_slide(
            prs=prs,
            theme=theme_colors,
            summary=summary,
            include_commercials=include_commercials,
            include_audience_metrics=include_audience_metrics,
        )

        deck_buf = io.BytesIO()
        prs.save(deck_buf)
        return deck_buf.getvalue(), summary

    def _set_slide_background(self, slide: Any, theme: ThemeColors) -> None:
        """Create full-bleed background rectangle to guarantee exact theme color across viewers."""
        bg = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.50)
        )
        bg.fill.solid()
        bg.fill.fore_color.rgb = theme.bg_color
        bg.line.color.rgb = theme.bg_color

    def _add_cover_slide(
        self,
        prs: Presentation,
        theme: ThemeColors,
        campaign_title: str,
        client_name: str,
        site_count: int,
        cities: list[str],
    ) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        self._set_slide_background(slide, theme)

        # Accent vertical bar on the left
        bar = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.0), Inches(0.15), Inches(5.5)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = theme.accent_color
        bar.line.color.rgb = theme.accent_color

        # Title block
        tb = slide.shapes.add_textbox(
            Inches(1.25), Inches(1.15), Inches(11.2), Inches(3.8)
        )
        tf = tb.text_frame
        tf.word_wrap = True

        p_kicker = tf.paragraphs[0]
        p_kicker.text = "CAMPAIGN PROPOSAL & MEDIA PLAN"
        p_kicker.font.name = "Arial"
        p_kicker.font.size = Pt(11)
        p_kicker.font.bold = True
        p_kicker.font.color.rgb = theme.accent_color
        p_kicker.space_after = Pt(14)

        p_title = tf.add_paragraph()
        p_title.text = campaign_title
        p_title.font.name = "Arial"
        p_title.font.size = Pt(38)
        p_title.font.bold = True
        p_title.font.color.rgb = theme.text_primary
        p_title.space_after = Pt(12)

        if client_name.strip():
            p_sub = tf.add_paragraph()
            p_sub.text = f"Prepared for: {client_name.strip()}"
            p_sub.font.name = "Arial"
            p_sub.font.size = Pt(18)
            p_sub.font.color.rgb = theme.text_muted

        # Bottom metadata badge
        meta_tb = slide.shapes.add_textbox(
            Inches(1.25), Inches(5.3), Inches(11.2), Inches(1.2)
        )
        meta_tf = meta_tb.text_frame
        meta_tf.word_wrap = True

        cities_str = f"Coverage: {', '.join(cities[:5])}" if cities else ""
        if len(cities) > 5:
            cities_str += f" +{len(cities) - 5} more"

        p_badge = meta_tf.paragraphs[0]
        p_badge.text = f"✦  {site_count} Selected OOH Sites    |    {cities_str}"
        p_badge.font.name = "Arial"
        p_badge.font.size = Pt(13)
        p_badge.font.bold = True
        p_badge.font.color.rgb = theme.text_primary
        p_badge.space_after = Pt(6)

        p_footer = meta_tf.add_paragraph()
        p_footer.text = f"BuzzOmni Media Inventory  •  Generated {datetime.now().strftime('%B %Y')}"
        p_footer.font.name = "Arial"
        p_footer.font.size = Pt(11)
        p_footer.font.color.rgb = theme.text_muted

    def _add_site_slide(
        self,
        prs: Presentation,
        theme: ThemeColors,
        site: dict[str, Any],
        idx: int,
        total_sites: int,
        total_slides: int,
        img_stream: io.BytesIO | None,
        img_dims: tuple[int, int] | None,
        include_commercials: bool,
        include_audience_metrics: bool,
    ) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        self._set_slide_background(slide, theme)

        # 62% Photo Container (8.0" x 6.20" at x=0.6", y=0.65")
        box_x, box_y, box_w, box_h = 0.6, 0.65, 8.0, 6.20
        photo_box = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(box_x),
            Inches(box_y),
            Inches(box_w),
            Inches(box_h),
        )
        photo_box.fill.solid()
        photo_box.fill.fore_color.rgb = theme.photo_bg
        photo_box.line.color.rgb = theme.border_color
        photo_box.line.width = Pt(1)

        if img_stream is not None and img_dims is not None:
            fit_x, fit_y, fit_w, fit_h = self.compute_contain_fit(
                img_dims[0], img_dims[1], box_x, box_y, box_w, box_h
            )
            slide.shapes.add_picture(
                img_stream,
                Inches(fit_x),
                Inches(fit_y),
                Inches(fit_w),
                Inches(fit_h),
            )
        else:
            tf_box = photo_box.text_frame
            tf_box.word_wrap = True
            p_fallback = tf_box.paragraphs[0]
            p_fallback.text = "Site Photo Pending / Unavailable"
            p_fallback.alignment = PP_ALIGN.CENTER
            p_fallback.font.name = "Arial"
            p_fallback.font.size = Pt(14)
            p_fallback.font.bold = True
            p_fallback.font.color.rgb = theme.text_muted

        # 38% Spec Panel (3.95" x 6.20" at x=8.8", y=0.65")
        card_x, card_y, card_w, card_h = 8.8, 0.65, 3.95, 6.20
        spec_card = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(card_x),
            Inches(card_y),
            Inches(card_w),
            Inches(card_h),
        )
        spec_card.fill.solid()
        spec_card.fill.fore_color.rgb = theme.card_bg
        spec_card.line.color.rgb = theme.border_color
        spec_card.line.width = Pt(1.5)

        spec_tb = slide.shapes.add_textbox(
            Inches(card_x + 0.18),
            Inches(card_y + 0.18),
            Inches(card_w - 0.36),
            Inches(card_h - 0.36),
        )
        tf_spec = spec_tb.text_frame
        tf_spec.word_wrap = True
        tf_spec.margin_left = Inches(0.05)
        tf_spec.margin_right = Inches(0.05)
        tf_spec.margin_top = Inches(0.05)
        tf_spec.margin_bottom = Inches(0.05)

        # 1. Kicker
        p_kicker = tf_spec.paragraphs[0]
        p_kicker.text = f"SITE {idx + 1:02d} / {total_sites:02d}"
        p_kicker.font.name = "Arial"
        p_kicker.font.size = Pt(9.5)
        p_kicker.font.bold = True
        p_kicker.font.color.rgb = theme.accent_color
        p_kicker.space_after = Pt(2)

        # 2. Site Code
        site_code = site.get("inventory_code") or site.get("id") or f"SITE-{idx + 1}"
        p_code = tf_spec.add_paragraph()
        p_code.text = str(site_code)
        p_code.font.name = "Arial"
        p_code.font.size = Pt(20)
        p_code.font.bold = True
        p_code.font.color.rgb = theme.text_primary
        p_code.space_after = Pt(2)

        # 3. Location & Area
        loc_str = site.get("location") or site.get("area") or "Location Unavailable"
        p_loc = tf_spec.add_paragraph()
        p_loc.text = str(loc_str)
        p_loc.font.name = "Arial"
        p_loc.font.size = Pt(12)
        p_loc.font.bold = True
        p_loc.font.color.rgb = theme.text_primary

        city_area_parts = [site.get("area"), site.get("city")]
        city_area_str = ", ".join([str(p) for p in city_area_parts if p])
        p_area = tf_spec.add_paragraph()
        p_area.text = city_area_str or "—"
        p_area.font.name = "Arial"
        p_area.font.size = Pt(10)
        p_area.font.color.rgb = theme.text_muted
        p_area.space_after = Pt(8)

        # 4. Specifications
        p_spec_head = tf_spec.add_paragraph()
        p_spec_head.text = "SPECIFICATIONS"
        p_spec_head.font.name = "Arial"
        p_spec_head.font.size = Pt(9)
        p_spec_head.font.bold = True
        p_spec_head.font.color.rgb = theme.accent_color
        p_spec_head.space_after = Pt(2)

        media_type = site.get("media_type") or "—"
        sub_type = site.get("sub_type") or "—"
        type_str = f"• Type: {media_type} ({sub_type})" if sub_type != "—" else f"• Type: {media_type}"
        p_type = tf_spec.add_paragraph()
        p_type.text = type_str
        p_type.font.name = "Arial"
        p_type.font.size = Pt(9.5)
        p_type.font.color.rgb = theme.text_primary

        w_ft = site.get("width")
        h_ft = site.get("height")
        sqft = site.get("area_sq_ft")
        dim_str = f"• Size: {w_ft or '—'} × {h_ft or '—'} ft"
        if sqft:
            dim_str += f" ({sqft:g} sq ft)" if isinstance(sqft, float) else f" ({sqft} sq ft)"
        p_dim = tf_spec.add_paragraph()
        p_dim.text = dim_str
        p_dim.font.name = "Arial"
        p_dim.font.size = Pt(9.5)
        p_dim.font.color.rgb = theme.text_primary

        facing = site.get("facing") or "—"
        orientation = site.get("orientation") or "—"
        p_facing = tf_spec.add_paragraph()
        p_facing.text = f"• Facing: {facing} | {orientation}"
        p_facing.font.name = "Arial"
        p_facing.font.size = Pt(9.5)
        p_facing.font.color.rgb = theme.text_primary
        p_facing.space_after = Pt(8)

        # 5. Audience Metrics (if enabled)
        if include_audience_metrics and site.get("admavin"):
            adm = site["admavin"]
            p_aud_head = tf_spec.add_paragraph()
            p_aud_head.text = "AUDIENCE METRICS (ADMAVIN)"
            p_aud_head.font.name = "Arial"
            p_aud_head.font.size = Pt(9)
            p_aud_head.font.bold = True
            p_aud_head.font.color.rgb = theme.accent_color
            p_aud_head.space_after = Pt(2)

            reach = adm.get("reach")
            ots = adm.get("ots")
            lts = adm.get("lts_score") or adm.get("lts_rating")

            p_reach = tf_spec.add_paragraph()
            p_reach.text = f"• Monthly Reach: {format_number(reach)}"
            p_reach.font.name = "Arial"
            p_reach.font.size = Pt(9.5)
            p_reach.font.color.rgb = theme.text_primary

            p_ots = tf_spec.add_paragraph()
            p_ots.text = f"• OTS Impressions: {format_number(ots)}"
            p_ots.font.name = "Arial"
            p_ots.font.size = Pt(9.5)
            p_ots.font.color.rgb = theme.text_primary

            if lts is not None:
                p_lts = tf_spec.add_paragraph()
                p_lts.text = f"• LTS Score: {lts}"
                p_lts.font.name = "Arial"
                p_lts.font.size = Pt(9.5)
                p_lts.font.color.rgb = theme.text_primary

            p_ots.space_after = Pt(8)

        # 6. Commercials (if enabled)
        if include_commercials and site.get("total_cost") is not None:
            p_comm_head = tf_spec.add_paragraph()
            p_comm_head.text = "INVESTMENT"
            p_comm_head.font.name = "Arial"
            p_comm_head.font.size = Pt(9)
            p_comm_head.font.bold = True
            p_comm_head.font.color.rgb = theme.accent_color
            p_comm_head.space_after = Pt(2)

            p_cost = tf_spec.add_paragraph()
            p_cost.text = f"₹{format_inr(site.get('total_cost'))} / mo"
            p_cost.font.name = "Arial"
            p_cost.font.size = Pt(14)
            p_cost.font.bold = True
            p_cost.font.color.rgb = theme.text_primary

        # Slide Numbering
        footer_tb = slide.shapes.add_textbox(
            Inches(card_x), Inches(6.95), Inches(card_w), Inches(0.35)
        )
        tf_footer = footer_tb.text_frame
        p_foot = tf_footer.paragraphs[0]
        p_foot.text = f"Slide {idx + 2:02d} / {total_slides:02d}"
        p_foot.alignment = PP_ALIGN.RIGHT
        p_foot.font.name = "Arial"
        p_foot.font.size = Pt(9)
        p_foot.font.color.rgb = theme.text_muted

    def _add_closing_slide(
        self,
        prs: Presentation,
        theme: ThemeColors,
        summary: dict[str, Any],
        include_commercials: bool,
        include_audience_metrics: bool,
    ) -> None:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        self._set_slide_background(slide, theme)

        # Centered Heading
        heading_tb = slide.shapes.add_textbox(
            Inches(1.5), Inches(0.9), Inches(10.333), Inches(1.5)
        )
        tf_h = heading_tb.text_frame
        tf_h.word_wrap = True

        p_thanks = tf_h.paragraphs[0]
        p_thanks.text = "Thank You"
        p_thanks.alignment = PP_ALIGN.CENTER
        p_thanks.font.name = "Arial"
        p_thanks.font.size = Pt(38)
        p_thanks.font.bold = True
        p_thanks.font.color.rgb = theme.text_primary
        p_thanks.space_after = Pt(6)

        p_sub = tf_h.add_paragraph()
        p_sub.text = "Campaign Proposal & OOH Media Inventory Summary"
        p_sub.alignment = PP_ALIGN.CENTER
        p_sub.font.name = "Arial"
        p_sub.font.size = Pt(15)
        p_sub.font.color.rgb = theme.text_muted

        # Summary Card
        card_w, card_h = 8.0, 3.2
        card_x = (13.333 - card_w) / 2.0
        card_y = 2.6

        card = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(card_x),
            Inches(card_y),
            Inches(card_w),
            Inches(card_h),
        )
        card.fill.solid()
        card.fill.fore_color.rgb = theme.card_bg
        card.line.color.rgb = theme.border_color
        card.line.width = Pt(1.5)

        card_tb = slide.shapes.add_textbox(
            Inches(card_x + 0.4),
            Inches(card_y + 0.3),
            Inches(card_w - 0.8),
            Inches(card_h - 0.6),
        )
        tf_card = card_tb.text_frame
        tf_card.word_wrap = True

        p_chead = tf_card.paragraphs[0]
        p_chead.text = "CAMPAIGN SUMMARY"
        p_chead.font.name = "Arial"
        p_chead.font.size = Pt(11)
        p_chead.font.bold = True
        p_chead.font.color.rgb = theme.accent_color
        p_chead.space_after = Pt(10)

        p_sites = tf_card.add_paragraph()
        p_sites.text = f"• Total Media Sites: {summary['site_count']}"
        p_sites.font.name = "Arial"
        p_sites.font.size = Pt(12)
        p_sites.font.color.rgb = theme.text_primary
        p_sites.space_after = Pt(6)

        cities_str = ", ".join(summary["cities"]) if summary["cities"] else "—"
        p_cities = tf_card.add_paragraph()
        p_cities.text = f"• Target Cities: {cities_str}"
        p_cities.font.name = "Arial"
        p_cities.font.size = Pt(12)
        p_cities.font.color.rgb = theme.text_primary
        p_cities.space_after = Pt(6)

        if include_audience_metrics:
            p_reach = tf_card.add_paragraph()
            p_reach.text = f"• Combined Reach: {format_number(summary['total_reach'])} audience impressions"
            p_reach.font.name = "Arial"
            p_reach.font.size = Pt(12)
            p_reach.font.color.rgb = theme.text_primary
            p_reach.space_after = Pt(6)

        if include_commercials:
            p_cost = tf_card.add_paragraph()
            p_cost.text = f"• Total Monthly Investment: ₹{format_inr(summary['total_monthly_cost'])} / month"
            p_cost.font.name = "Arial"
            p_cost.font.size = Pt(13)
            p_cost.font.bold = True
            p_cost.font.color.rgb = theme.text_primary

        # Bottom Disclaimer
        disc_tb = slide.shapes.add_textbox(
            Inches(1.5), Inches(6.3), Inches(10.333), Inches(0.5)
        )
        tf_disc = disc_tb.text_frame
        p_disc = tf_disc.paragraphs[0]
        p_disc.text = "BuzzOmni Media Network  •  Commercial rates valid for 15 days  •  Confidential"
        p_disc.alignment = PP_ALIGN.CENTER
        p_disc.font.name = "Arial"
        p_disc.font.size = Pt(10)
        p_disc.font.color.rgb = theme.text_muted

    def save_and_upload(
        self,
        deck_bytes: bytes,
        file_slug: str = "proposal",
        expires_in: int = 900,
    ) -> dict[str, Any]:
        """Save presentation file to disk and upload to S3 private storage."""
        slug_clean = re.sub(r"[^a-zA-Z0-9_-]", "_", (file_slug or "proposal").strip().lower()).strip("_") or "proposal"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"campaign_deck_{slug_clean}_{timestamp}.pptx"

        local_file_path = self.exports_dir / file_name
        local_file_path.write_bytes(deck_bytes)

        safe_expiry = min(max(expires_in, 60), 3600)
        s3_key = f"campaign-decks/{file_name}"
        s3_url: str | None = None

        try:
            self._s3_client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=deck_bytes,
                ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
            s3_url = self._s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": s3_key},
                ExpiresIn=safe_expiry,
            )
        except (ClientError, BotoCoreError, Exception) as exc:
            logger.warning(
                "s3_deck_upload_failed",
                extra={"error": str(exc), "bucket": self.bucket, "key": s3_key},
            )
            s3_url = None

        return {
            "file_name": file_name,
            "local_file_path": str(local_file_path.resolve()),
            "s3_download_url": s3_url,
            "expires_in_seconds": safe_expiry if s3_url else None,
        }
