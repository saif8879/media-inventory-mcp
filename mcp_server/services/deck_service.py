from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import io
import logging
from pathlib import Path
import re
from typing import Any
import urllib.parse
import uuid

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


def _add_para(
    tf: Any,
    text: str,
    font_size_pt: float,
    bold: bool = False,
    color_rgb: RGBColor | None = None,
    space_after_pt: float = 0,
    alignment: Any = None,
) -> Any:
    """Create or populate a paragraph in a text frame and apply font attributes directly to a Run."""
    if len(tf.paragraphs) == 1 and not tf.paragraphs[0].text and not tf.paragraphs[0].runs:
        p = tf.paragraphs[0]
    else:
        p = tf.add_paragraph()

    if alignment is not None:
        p.alignment = alignment
    if space_after_pt:
        p.space_after = Pt(space_after_pt)

    run = p.add_run()
    run.text = text
    run.font.name = "Arial"
    run.font.size = Pt(font_size_pt)
    run.font.bold = bold
    if color_rgb is not None:
        run.font.color.rgb = color_rgb

    return p


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
                    img = img.convert("RGB")
                    w, h = img.size
                    max_edge = max(w, h)
                    if max_edge > 2000:
                        scale = 2000.0 / max_edge
                        new_w = max(1, int(round(w * scale)))
                        new_h = max(1, int(round(h * scale)))
                        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        w, h = new_w, new_h

                    out_buf = io.BytesIO()
                    img.save(out_buf, format="JPEG", quality=85)
                    out_buf.seek(0)
                    return out_buf, (w, h)
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

        _add_para(
            tf,
            "CAMPAIGN PROPOSAL & MEDIA PLAN",
            font_size_pt=11,
            bold=True,
            color_rgb=theme.accent_color,
            space_after_pt=14,
        )
        _add_para(
            tf,
            campaign_title,
            font_size_pt=38,
            bold=True,
            color_rgb=theme.text_primary,
            space_after_pt=12,
        )

        if client_name.strip():
            _add_para(
                tf,
                f"Prepared for: {client_name.strip()}",
                font_size_pt=18,
                bold=False,
                color_rgb=theme.text_muted,
            )

        # Bottom metadata badge
        meta_tb = slide.shapes.add_textbox(
            Inches(1.25), Inches(5.3), Inches(11.2), Inches(1.2)
        )
        meta_tf = meta_tb.text_frame
        meta_tf.word_wrap = True

        cities_str = f"Coverage: {', '.join(cities[:5])}" if cities else ""
        if len(cities) > 5:
            cities_str += f" +{len(cities) - 5} more"

        _add_para(
            meta_tf,
            f"✦  {site_count} Selected OOH Sites    |    {cities_str}",
            font_size_pt=13,
            bold=True,
            color_rgb=theme.text_primary,
            space_after_pt=6,
        )
        _add_para(
            meta_tf,
            f"BuzzOmni Media Inventory  •  Generated {datetime.now().strftime('%B %Y')}",
            font_size_pt=11,
            bold=False,
            color_rgb=theme.text_muted,
        )

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

        picture_added = False
        if img_stream is not None and img_dims is not None:
            try:
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
                picture_added = True
            except Exception as exc:
                logger.warning(
                    "corrupt_or_unsupported_image_embed_failed",
                    extra={
                        "error": str(exc),
                        "site_id": site.get("id"),
                        "inventory_code": site.get("inventory_code"),
                    },
                )
                picture_added = False

        if not picture_added:
            tf_box = photo_box.text_frame
            tf_box.word_wrap = True
            _add_para(
                tf_box,
                "Site Photo Pending / Unavailable",
                font_size_pt=14,
                bold=True,
                color_rgb=theme.text_muted,
                alignment=PP_ALIGN.CENTER,
            )

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
        _add_para(
            tf_spec,
            f"SITE {idx + 1:02d} / {total_sites:02d}",
            font_size_pt=9.5,
            bold=True,
            color_rgb=theme.accent_color,
            space_after_pt=2,
        )

        # 2. Site Code
        site_code = site.get("inventory_code") or site.get("id") or f"SITE-{idx + 1}"
        _add_para(
            tf_spec,
            str(site_code),
            font_size_pt=20,
            bold=True,
            color_rgb=theme.text_primary,
            space_after_pt=2,
        )

        # 3. Location & Area
        loc_str = site.get("location") or site.get("area") or "Location Unavailable"
        _add_para(
            tf_spec,
            str(loc_str),
            font_size_pt=12,
            bold=True,
            color_rgb=theme.text_primary,
        )

        city_area_parts = [site.get("area"), site.get("city")]
        city_area_str = ", ".join([str(p) for p in city_area_parts if p])
        _add_para(
            tf_spec,
            city_area_str or "—",
            font_size_pt=10,
            bold=False,
            color_rgb=theme.text_muted,
            space_after_pt=8,
        )

        # 4. Specifications
        _add_para(
            tf_spec,
            "SPECIFICATIONS",
            font_size_pt=9,
            bold=True,
            color_rgb=theme.accent_color,
            space_after_pt=2,
        )

        media_type = site.get("media_type") or "—"
        sub_type = site.get("sub_type") or "—"
        type_str = f"• Type: {media_type} ({sub_type})" if sub_type != "—" else f"• Type: {media_type}"
        _add_para(
            tf_spec,
            type_str,
            font_size_pt=9.5,
            bold=False,
            color_rgb=theme.text_primary,
        )

        w_ft = site.get("width")
        h_ft = site.get("height")
        sqft = site.get("area_sq_ft")
        dim_str = f"• Size: {w_ft or '—'} × {h_ft or '—'} ft"
        if sqft:
            dim_str += f" ({sqft:g} sq ft)" if isinstance(sqft, float) else f" ({sqft} sq ft)"
        _add_para(
            tf_spec,
            dim_str,
            font_size_pt=9.5,
            bold=False,
            color_rgb=theme.text_primary,
        )

        facing = site.get("facing") or "—"
        orientation = site.get("orientation") or "—"
        _add_para(
            tf_spec,
            f"• Facing: {facing} | {orientation}",
            font_size_pt=9.5,
            bold=False,
            color_rgb=theme.text_primary,
            space_after_pt=8,
        )

        # 5. Audience Metrics (if enabled)
        if include_audience_metrics and site.get("admavin"):
            adm = site["admavin"]
            _add_para(
                tf_spec,
                "AUDIENCE METRICS (ADMAVIN)",
                font_size_pt=9,
                bold=True,
                color_rgb=theme.accent_color,
                space_after_pt=2,
            )

            reach = adm.get("reach")
            ots = adm.get("ots")
            lts = adm.get("lts_score") or adm.get("lts_rating")

            _add_para(
                tf_spec,
                f"• Monthly Reach: {format_number(reach)}",
                font_size_pt=9.5,
                bold=False,
                color_rgb=theme.text_primary,
            )
            _add_para(
                tf_spec,
                f"• OTS Impressions: {format_number(ots)}",
                font_size_pt=9.5,
                bold=False,
                color_rgb=theme.text_primary,
                space_after_pt=8 if lts is None else 0,
            )

            if lts is not None:
                _add_para(
                    tf_spec,
                    f"• LTS Score: {lts}",
                    font_size_pt=9.5,
                    bold=False,
                    color_rgb=theme.text_primary,
                    space_after_pt=8,
                )

        # 6. Commercials (if enabled)
        if include_commercials and site.get("total_cost") is not None:
            _add_para(
                tf_spec,
                "INVESTMENT",
                font_size_pt=9,
                bold=True,
                color_rgb=theme.accent_color,
                space_after_pt=2,
            )
            _add_para(
                tf_spec,
                f"₹{format_inr(site.get('total_cost'))} / mo",
                font_size_pt=14,
                bold=True,
                color_rgb=theme.text_primary,
            )

        # Slide Numbering
        footer_tb = slide.shapes.add_textbox(
            Inches(card_x), Inches(6.95), Inches(card_w), Inches(0.35)
        )
        tf_footer = footer_tb.text_frame
        _add_para(
            tf_footer,
            f"Slide {idx + 2:02d} / {total_slides:02d}",
            font_size_pt=9,
            bold=False,
            color_rgb=theme.text_muted,
            alignment=PP_ALIGN.RIGHT,
        )

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

        _add_para(
            tf_h,
            "Thank You",
            font_size_pt=38,
            bold=True,
            color_rgb=theme.text_primary,
            space_after_pt=6,
            alignment=PP_ALIGN.CENTER,
        )
        _add_para(
            tf_h,
            "Campaign Proposal & OOH Media Inventory Summary",
            font_size_pt=15,
            bold=False,
            color_rgb=theme.text_muted,
            alignment=PP_ALIGN.CENTER,
        )

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

        _add_para(
            tf_card,
            "CAMPAIGN SUMMARY",
            font_size_pt=11,
            bold=True,
            color_rgb=theme.accent_color,
            space_after_pt=10,
        )
        _add_para(
            tf_card,
            f"• Total Media Sites: {summary['site_count']}",
            font_size_pt=12,
            bold=False,
            color_rgb=theme.text_primary,
            space_after_pt=6,
        )

        cities_str = ", ".join(summary["cities"]) if summary["cities"] else "—"
        _add_para(
            tf_card,
            f"• Target Cities: {cities_str}",
            font_size_pt=12,
            bold=False,
            color_rgb=theme.text_primary,
            space_after_pt=6,
        )

        if include_audience_metrics:
            _add_para(
                tf_card,
                f"• Combined Reach: {format_number(summary['total_reach'])} audience impressions",
                font_size_pt=12,
                bold=False,
                color_rgb=theme.text_primary,
                space_after_pt=6,
            )

        if include_commercials:
            _add_para(
                tf_card,
                f"• Total Monthly Investment: ₹{format_inr(summary['total_monthly_cost'])} / month",
                font_size_pt=13,
                bold=True,
                color_rgb=theme.text_primary,
            )

        # Bottom Disclaimer
        disc_tb = slide.shapes.add_textbox(
            Inches(1.5), Inches(6.3), Inches(10.333), Inches(0.5)
        )
        tf_disc = disc_tb.text_frame
        if include_commercials:
            disc_text = "BuzzOmni Media Network  •  Commercial rates valid for 15 days  •  Confidential"
        else:
            disc_text = "BuzzOmni Media Network  •  Confidential"

        _add_para(
            tf_disc,
            disc_text,
            font_size_pt=10,
            bold=False,
            color_rgb=theme.text_muted,
            alignment=PP_ALIGN.CENTER,
        )

    def save_and_upload(
        self,
        deck_bytes: bytes,
        file_slug: str = "proposal",
        expires_in: int = 900,
    ) -> dict[str, Any]:
        """Save presentation file to disk and upload to S3 private storage."""
        slug_clean = re.sub(r"[^a-zA-Z0-9_-]", "_", (file_slug or "proposal").strip().lower()).strip("_") or "proposal"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        token = uuid.uuid4().hex[:6]
        file_name = f"campaign_deck_{slug_clean}_{timestamp}_{token}.pptx"

        local_file_path = self.exports_dir / file_name
        local_file_path.write_bytes(deck_bytes)

        safe_expiry = min(max(expires_in, 60), 3600)
        s3_key = f"campaign-decks/{file_name}"
        s3_url: str | None = None
        warnings: list[str] = []

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
            warnings.append("S3 upload failed; presentation is saved locally only.")

        return {
            "file_name": file_name,
            "local_file_path": str(local_file_path.resolve()),
            "s3_download_url": s3_url,
            "expires_in_seconds": safe_expiry if s3_url else None,
            "warnings": warnings,
        }
