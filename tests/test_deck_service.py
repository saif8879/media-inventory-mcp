import io
import json
from pathlib import Path
import re
from unittest.mock import AsyncMock, MagicMock, patch

from botocore.exceptions import ClientError
from httpx import ASGITransport, AsyncClient
from PIL import Image
import pptx
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
import pytest

from mcp_server.server import create_app, create_mcp_server
from mcp_server.services.deck_service import DeckBuilderService, _add_para, format_inr
from mcp_server.tools.generate_campaign_deck import generate_campaign_deck_handler


def test_deck_dependencies_and_exports_dir():
    assert pptx.__version__ is not None
    assert Image.__version__ is not None


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

    # Edge cases: 0 or negative dimensions should fall back to box dimensions
    x3, y3, w3, h3 = service.compute_contain_fit(0, 0, box_x=1.0, box_y=1.0, box_w=8.0, box_h=6.0)
    assert (x3, y3, w3, h3) == (1.0, 1.0, 8.0, 6.0)


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
            },
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
    assert summary["total_reach"] == 1250000
    assert summary["cities"] == ["Mumbai"]

    # Verify PPTX is readable
    prs = Presentation(io.BytesIO(deck_bytes))
    # 3 slides: Cover, Site 1, Closing
    assert len(prs.slides) == 3
    # Check 16:9 widescreen dimensions (13.333" x 7.50")
    assert round(prs.slide_width.inches, 3) == 13.333
    assert round(prs.slide_height.inches, 2) == 7.50


def test_build_deck_classic_theme_and_multiple_sites():
    service = DeckBuilderService()
    sample_sites = [
        {
            "id": "site-1",
            "inventory_code": "MI1",
            "city": "Mumbai",
            "area": "Bandra West",
            "location": "Linking Road",
            "media_type": "Billboard",
            "sub_type": "Frontlit",
            "facing": "North",
            "width": 30.0,
            "height": 15.0,
            "area_sq_ft": 450.0,
            "total_cost": 250000.0,
            "image_url": None,
        },
        {
            "id": "site-2",
            "inventory_code": "MI2",
            "city": "Delhi",
            "area": "Connaught Place",
            "location": "Inner Circle",
            "media_type": "Unipole",
            "sub_type": "Backlit",
            "facing": "South",
            "width": 40.0,
            "height": 20.0,
            "area_sq_ft": 800.0,
            "total_cost": 350000.0,
            "image_url": None,
        },
    ]
    deck_bytes, summary = service.build_deck(
        sites=sample_sites,
        campaign_title="National Brand Rollout",
        client_name="Acme Corp",
        theme="classic",
        include_commercials=False,
        include_audience_metrics=False,
    )
    assert len(deck_bytes) > 0
    assert summary["site_count"] == 2
    assert summary["total_monthly_cost"] == 600000.0
    assert sorted(summary["cities"]) == ["Delhi", "Mumbai"]

    prs = Presentation(io.BytesIO(deck_bytes))
    # 4 slides: Cover, Site 1, Site 2, Closing
    assert len(prs.slides) == 4


def test_build_deck_with_embedded_image():
    service = DeckBuilderService()
    # Create a small valid test image in-memory
    img = Image.new("RGB", (640, 480), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    img_bytes = buf.getvalue()

    sample_sites = [
        {
            "id": "site-img",
            "inventory_code": "MI-IMG",
            "city": "Bengaluru",
            "area": "Indiranagar",
            "location": "100ft Road",
            "media_type": "Billboard",
            "sub_type": "Digital",
            "facing": "East",
            "width": 20.0,
            "height": 10.0,
            "area_sq_ft": 200.0,
            "total_cost": 150000.0,
            "image_url": "https://example.com/photo.jpg",
        }
    ]

    with patch.object(service, "fetch_image", return_value=(io.BytesIO(img_bytes), (640, 480))):
        deck_bytes, summary = service.build_deck(
            sites=sample_sites,
            campaign_title="Bengaluru Tech Tour",
            client_name="Tech Co",
            theme="editorial",
        )
        assert len(deck_bytes) > 0
        prs = Presentation(io.BytesIO(deck_bytes))
        assert len(prs.slides) == 3
        # Site slide is slide index 1
        site_slide = prs.slides[1]
        # Verify at least one picture shape was added
        picture_shapes = [s for s in site_slide.shapes if s.shape_type == pptx.enum.shapes.MSO_SHAPE_TYPE.PICTURE]
        assert len(picture_shapes) >= 1


def test_save_and_upload_success(tmp_path):
    mock_s3 = MagicMock()
    mock_s3.put_object.return_value = {}
    mock_s3.generate_presigned_url.return_value = "https://s3.ap-south-1.amazonaws.com/test-bucket/campaign-decks/campaign_deck_test.pptx"

    service = DeckBuilderService(s3_client=mock_s3, bucket="test-bucket", exports_dir=tmp_path)
    result = service.save_and_upload(
        deck_bytes=b"fake-pptx-data",
        file_slug="mumbai_launch",
        expires_in=600,
    )

    assert result["file_name"].startswith("campaign_deck_mumbai_launch_")
    assert result["file_name"].endswith(".pptx")
    assert Path(result["local_file_path"]).exists()
    assert Path(result["local_file_path"]).read_bytes() == b"fake-pptx-data"
    assert result["s3_download_url"] == "https://s3.ap-south-1.amazonaws.com/test-bucket/campaign-decks/campaign_deck_test.pptx"
    assert result["expires_in_seconds"] == 600

    mock_s3.put_object.assert_called_once()
    mock_s3.generate_presigned_url.assert_called_once()


def test_save_and_upload_s3_error_handled(tmp_path):
    mock_s3 = MagicMock()
    mock_s3.put_object.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "PutObject")

    service = DeckBuilderService(s3_client=mock_s3, bucket="test-bucket", exports_dir=tmp_path)
    result = service.save_and_upload(
        deck_bytes=b"fake-pptx-data",
        file_slug="error_test",
        expires_in=600,
    )

    assert Path(result["local_file_path"]).exists()
    assert result["s3_download_url"] is None
    assert "warnings" in result
    assert len(result["warnings"]) == 1
    assert "S3 upload failed; presentation is saved locally only." in result["warnings"][0]
    assert re.search(r"_[a-f0-9]{6}\.pptx$", result["file_name"]) is not None


def test_format_inr_numbers():
    assert format_inr(None) == "—"
    assert format_inr(0) == "0"
    assert format_inr(500) == "500"
    assert format_inr(450000) == "4,50,000"
    assert format_inr(10000000) == "1,00,00,000"
    assert format_inr(-500) == "-500"
    assert format_inr(-450000) == "-4,50,000"


def test_fetch_image_bucket_none():
    service = DeckBuilderService()
    service.bucket = None

    # 1. With HTTP URL that fails to download or returns 404 (mock httpx)
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        img_stream, dims = service.fetch_image("https://example.com/test.jpg")
        assert img_stream is None
        assert dims is None

    # 2. With S3 key string when bucket is None
    img_stream_key, dims_key = service.fetch_image("inventory/site1.jpg")
    assert img_stream_key is None
    assert dims_key is None


def test_fetch_image_s3_url_unquotes_key():
    mock_s3 = MagicMock()
    img = Image.new("RGB", (100, 100), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    img_bytes = buf.getvalue()

    mock_body = MagicMock()
    mock_body.read.return_value = img_bytes
    mock_s3.get_object.return_value = {"Body": mock_body}

    service = DeckBuilderService(s3_client=mock_s3, bucket="my-bucket")
    url = "https://my-bucket.s3.ap-south-1.amazonaws.com/my-bucket/site%20photos/photo%201.jpg"
    stream, dims = service.fetch_image(url)

    assert stream is not None
    assert dims == (100, 100)
    mock_s3.get_object.assert_called_once_with(
        Bucket="my-bucket",
        Key="site photos/photo 1.jpg",
    )


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


@pytest.mark.asyncio
async def test_generate_campaign_deck_handler_all_invalid_sites():
    server = create_mcp_server()
    with patch("mcp_server.tools.generate_campaign_deck.MediaInventoryService") as mock_srv_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.get_media_by_identifier = AsyncMock(return_value=None)
        res = await server.call_tool(
            "generate_campaign_deck",
            {"site_identifiers": ["INVALID_CODE_1", "INVALID_CODE_2"]}
        )
        assert not res.is_error
        data = json.loads(res.content[0].text)
        assert data["success"] is False
        assert data["error"]["code"] == "NO_VALID_SITES"
        assert len(data["error"]["details"]["warnings"]) == 2


@pytest.mark.asyncio
async def test_generate_campaign_deck_handler_success_with_warnings(tmp_path):
    server = create_mcp_server()
    site_valid = {
        "id": "site-1",
        "inventory_code": "MI1",
        "city": "Mumbai",
        "area": "Bandra West",
        "location": "Linking Road",
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
        },
    }

    async def mock_get_by_id(identifier, **kwargs):
        if identifier == "MI1":
            return site_valid
        return None

    with patch("mcp_server.tools.generate_campaign_deck.MediaInventoryService") as mock_srv_cls, \
         patch("mcp_server.tools.generate_campaign_deck.DeckBuilderService") as mock_deck_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.get_media_by_identifier = AsyncMock(side_effect=mock_get_by_id)

        mock_deck_instance = MagicMock()
        mock_deck_cls.return_value = mock_deck_instance
        mock_deck_instance.build_deck.return_value = (b"fake-pptx", {
            "site_count": 1,
            "total_monthly_cost": 450000.0,
            "total_reach": 1250000,
            "cities": ["Mumbai"],
        })
        mock_deck_instance.save_and_upload.return_value = {
            "file_name": "campaign_deck_proposal_test.pptx",
            "local_file_path": str(tmp_path / "campaign_deck_proposal_test.pptx"),
            "s3_download_url": "https://s3.example.com/test.pptx",
            "expires_in_seconds": 900,
        }

        res = await server.call_tool(
            "generate_campaign_deck",
            {
                "site_identifiers": ["MI1", "NON_EXISTENT"],
                "campaign_title": "Summer Festival",
                "client_name": "Pepsi",
                "theme": "editorial",
                "include_commercials": True,
                "include_audience_metrics": True,
                "expires_in": 900,
            }
        )
        assert not res.is_error
        data = json.loads(res.content[0].text)
        assert data["success"] is True
        deck_data = data["data"]
        assert deck_data["site_count"] == 1
        assert deck_data["theme"] == "editorial"
        assert deck_data["file_name"] == "campaign_deck_proposal_test.pptx"
        assert deck_data["s3_download_url"] == "https://s3.example.com/test.pptx"
        assert len(deck_data["warnings"]) == 1
        assert "NON_EXISTENT" in deck_data["warnings"][0]
        mock_deck_instance.build_deck.assert_called_once_with(
            sites=[site_valid],
            campaign_title="Summer Festival",
            client_name="Pepsi",
            theme="editorial",
            include_commercials=True,
            include_audience_metrics=True,
        )
        mock_deck_instance.save_and_upload.assert_called_once_with(
            deck_bytes=b"fake-pptx",
            file_slug="Summer Festival",
            expires_in=900,
        )


@pytest.mark.asyncio
async def test_health_endpoint_lists_generate_campaign_deck():
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        res = await client.get("/health")
        assert res.status_code == 200
        health_data = res.json()
        assert "generate_campaign_deck" in health_data["tools"]


def test_add_para_sets_run_level_font_formatting_and_xml():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.50)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    tb = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(4))
    tf = tb.text_frame

    # 1. First paragraph populates existing empty paragraph
    p1 = _add_para(
        tf,
        "Primary Headline",
        font_size_pt=24,
        bold=True,
        color_rgb=RGBColor(75, 142, 255),
        space_after_pt=12,
        alignment=PP_ALIGN.CENTER,
    )
    assert len(tf.paragraphs) == 1
    assert len(p1.runs) == 1
    run1 = p1.runs[0]
    assert run1.text == "Primary Headline"
    assert run1.font.name == "Arial"
    assert run1.font.size == Pt(24)
    assert run1.font.bold is True
    assert run1.font.color.rgb == RGBColor(75, 142, 255)
    assert p1.space_after == Pt(12)
    assert p1.alignment == PP_ALIGN.CENTER

    # Check XML serialization for run-level font formatting
    xml1 = run1._r.xml
    assert 'sz="2400"' in xml1
    assert 'b="1"' in xml1
    assert '4B8EFF' in xml1

    # 2. Second paragraph appends a new paragraph to tf
    p2 = _add_para(
        tf,
        "Secondary Subtitle",
        font_size_pt=14,
        bold=False,
        color_rgb=RGBColor(148, 163, 184),
        space_after_pt=6,
    )
    assert len(tf.paragraphs) == 2
    assert len(p2.runs) == 1
    run2 = p2.runs[0]
    assert run2.text == "Secondary Subtitle"
    assert run2.font.name == "Arial"
    assert run2.font.size == Pt(14)
    assert run2.font.bold is False
    assert run2.font.color.rgb == RGBColor(148, 163, 184)
    xml2 = run2._r.xml
    assert 'sz="1400"' in xml2
    assert '94A3B8' in xml2


def test_build_deck_applies_run_level_styling_across_all_slides():
    service = DeckBuilderService()
    site = {
        "id": "site-test",
        "inventory_code": "TEST-01",
        "city": "Mumbai",
        "area": "Worli",
        "location": "Sea Face",
        "media_type": "Billboard",
        "sub_type": "Frontlit",
        "facing": "North",
        "width": 40.0,
        "height": 20.0,
        "area_sq_ft": 800.0,
        "total_cost": 300000.0,
        "image_url": None,
        "admavin": {
            "reach": 500000,
            "ots": 1200000,
            "lts_score": 0.85,
        },
    }
    deck_bytes, _ = service.build_deck(
        sites=[site],
        campaign_title="Run Styling Verification",
        client_name="Test Brand",
        theme="editorial",
        include_commercials=True,
        include_audience_metrics=True,
    )

    prs = Presentation(io.BytesIO(deck_bytes))
    assert len(prs.slides) == 3

    # Inspect all text shapes on all slides to confirm run-level formatting exists
    for slide_idx, slide in enumerate(prs.slides):
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            tf = shape.text_frame
            for p in tf.paragraphs:
                for run in p.runs:
                    assert run.font.name == "Arial"
                    assert run.font.size is not None
                    assert run.font.size.pt > 0
                    assert run.font.color is not None
                    assert run.font.color.rgb is not None


def test_webp_image_conversion_downscale_and_embedding(tmp_path):
    service = DeckBuilderService()

    # 1. Create a WebP image in memory
    webp_img = Image.new("RGBA", (300, 200), color=(80, 120, 200, 255))
    webp_path = tmp_path / "test_image.webp"
    webp_img.save(webp_path, format="WEBP")

    # Fetch and normalize the WebP image
    stream, dims = service.fetch_image(str(webp_path))
    assert stream is not None
    assert dims == (300, 200)

    # Verify stream can be decoded by PIL and is converted to RGB JPEG
    with Image.open(stream) as converted:
        assert converted.format == "JPEG"
        assert converted.mode == "RGB"
        assert converted.size == (300, 200)

    # 2. Test downscaling when max edge > 2000px
    large_img = Image.new("RGB", (3000, 1500), color=(10, 20, 30))
    large_path = tmp_path / "large_image.webp"
    large_img.save(large_path, format="WEBP")

    stream_large, dims_large = service.fetch_image(str(large_path))
    assert stream_large is not None
    assert dims_large == (2000, 1000)
    with Image.open(stream_large) as converted_large:
        assert converted_large.size == (2000, 1000)

    # 3. Test embedding WebP image in build_deck
    site = {
        "id": "site-webp",
        "inventory_code": "WEBP-01",
        "city": "Bengaluru",
        "area": "Koramangala",
        "location": "80ft Road",
        "media_type": "Digital Screen",
        "image_url": str(webp_path),
    }
    deck_bytes, _ = service.build_deck(
        sites=[site],
        campaign_title="WebP Deck Test",
    )
    prs = Presentation(io.BytesIO(deck_bytes))
    site_slide = prs.slides[1]
    picture_shapes = [s for s in site_slide.shapes if s.shape_type == pptx.enum.shapes.MSO_SHAPE_TYPE.PICTURE]
    assert len(picture_shapes) == 1


def test_corrupt_image_falls_back_to_placeholder_without_error():
    service = DeckBuilderService()
    site = {
        "id": "site-corrupt",
        "inventory_code": "CORRUPT-01",
        "city": "Delhi",
        "image_url": "https://example.com/corrupt.jpg",
    }

    # Return corrupt bytes buffer that will fail inside add_picture
    corrupt_stream = io.BytesIO(b"not-an-image-at-all")
    with patch.object(service, "fetch_image", return_value=(corrupt_stream, (800, 600))):
        deck_bytes, _ = service.build_deck(sites=[site])
        prs = Presentation(io.BytesIO(deck_bytes))
        site_slide = prs.slides[1]
        # Should NOT contain a picture shape, but fallback placeholder text
        picture_shapes = [s for s in site_slide.shapes if s.shape_type == pptx.enum.shapes.MSO_SHAPE_TYPE.PICTURE]
        assert len(picture_shapes) == 0

        # Check placeholder text exists in shapes
        all_text = " ".join(
            s.text_frame.text for s in site_slide.shapes if s.has_text_frame
        )
        assert "Site Photo Pending / Unavailable" in all_text


@pytest.mark.asyncio
async def test_generate_campaign_deck_deduplication_and_order():
    server = create_mcp_server()
    site_mi1 = {"id": "1", "inventory_code": "MI1", "city": "Mumbai", "image_url": None}
    site_mi2 = {"id": "2", "inventory_code": "MI2", "city": "Delhi", "image_url": None}

    lookup_order: list[str] = []

    async def mock_get_by_id(identifier, **kwargs):
        lookup_order.append(identifier)
        if identifier == "MI1":
            return site_mi1
        if identifier == "MI2":
            return site_mi2
        return None

    with patch("mcp_server.tools.generate_campaign_deck.MediaInventoryService") as mock_srv_cls, \
         patch("mcp_server.tools.generate_campaign_deck.DeckBuilderService") as mock_deck_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.get_media_by_identifier = AsyncMock(side_effect=mock_get_by_id)

        mock_deck_instance = MagicMock()
        mock_deck_cls.return_value = mock_deck_instance
        mock_deck_instance.build_deck.return_value = (b"fake-pptx", {
            "site_count": 2,
            "total_monthly_cost": 0,
            "total_reach": 0,
            "cities": ["Delhi", "Mumbai"],
        })
        mock_deck_instance.save_and_upload.return_value = {
            "file_name": "campaign_deck_test.pptx",
            "local_file_path": "/tmp/deck.pptx",
            "s3_download_url": None,
            "expires_in_seconds": None,
            "warnings": [],
        }

        # Send duplicates in specific order: MI1, MI2, MI1, MI2, MI1
        res = await server.call_tool(
            "generate_campaign_deck",
            {"site_identifiers": ["MI1", "MI2", "MI1", "MI2", "MI1"]}
        )
        assert not res.is_error
        data = json.loads(res.content[0].text)
        assert data["success"] is True
        # Verify get_media_by_identifier was called exactly twice and in order
        assert lookup_order == ["MI1", "MI2"]
        # Verify build_deck received the two deduped sites
        call_sites = mock_deck_instance.build_deck.call_args[1]["sites"]
        assert len(call_sites) == 2
        assert [s["inventory_code"] for s in call_sites] == ["MI1", "MI2"]


@pytest.mark.asyncio
async def test_generate_campaign_deck_50_site_cap():
    server = create_mcp_server()

    # Case 1: 51 unique sites should be rejected
    fifty_one_sites = [f"MI{i}" for i in range(1, 52)]
    res = await server.call_tool(
        "generate_campaign_deck",
        {"site_identifiers": fifty_one_sites}
    )
    assert not res.is_error
    data = json.loads(res.content[0].text)
    assert data["success"] is False
    assert data["error"]["code"] == "TOO_MANY_SITES"
    assert "50 sites" in data["error"]["message"]

    # Case 2: 60 sites with duplicates reducing to <= 50 should be accepted
    repeated_sites = [f"MI{i % 40}" for i in range(60)]
    site_obj = {"id": "1", "inventory_code": "MI0", "city": "Mumbai", "image_url": None}

    with patch("mcp_server.tools.generate_campaign_deck.MediaInventoryService") as mock_srv_cls, \
         patch("mcp_server.tools.generate_campaign_deck.DeckBuilderService") as mock_deck_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.get_media_by_identifier = AsyncMock(return_value=site_obj)

        mock_deck_instance = MagicMock()
        mock_deck_cls.return_value = mock_deck_instance
        mock_deck_instance.build_deck.return_value = (b"fake-pptx", {
            "site_count": 40,
            "total_monthly_cost": 0,
            "total_reach": 0,
            "cities": ["Mumbai"],
        })
        mock_deck_instance.save_and_upload.return_value = {
            "file_name": "campaign_deck_test.pptx",
            "local_file_path": "/tmp/deck.pptx",
            "s3_download_url": None,
            "expires_in_seconds": None,
            "warnings": [],
        }

        res2 = await server.call_tool(
            "generate_campaign_deck",
            {"site_identifiers": repeated_sites}
        )
        data2 = json.loads(res2.content[0].text)
        assert data2["success"] is True


@pytest.mark.asyncio
async def test_generate_campaign_deck_s3_warning_propagated_to_response():
    site_obj = {"id": "1", "inventory_code": "MI1", "city": "Mumbai", "image_url": None}
    with patch("mcp_server.tools.generate_campaign_deck.MediaInventoryService") as mock_srv_cls, \
         patch("mcp_server.tools.generate_campaign_deck.DeckBuilderService") as mock_deck_cls:
        mock_srv = mock_srv_cls.return_value
        mock_srv.get_media_by_identifier = AsyncMock(return_value=site_obj)

        mock_deck_instance = MagicMock()
        mock_deck_cls.return_value = mock_deck_instance
        mock_deck_instance.build_deck.return_value = (b"fake-pptx", {
            "site_count": 1,
            "total_monthly_cost": 0,
            "total_reach": 0,
            "cities": ["Mumbai"],
        })
        mock_deck_instance.save_and_upload.return_value = {
            "file_name": "campaign_deck_test.pptx",
            "local_file_path": "/tmp/deck.pptx",
            "s3_download_url": None,
            "expires_in_seconds": None,
            "warnings": ["S3 upload failed; presentation is saved locally only."],
        }

        result_json = await generate_campaign_deck_handler(site_identifiers=["MI1"])
        data = json.loads(result_json)
        assert data["success"] is True
        assert any("S3 upload failed" in w for w in data["data"]["warnings"])


def test_closing_slide_commercials_conditionality():
    service = DeckBuilderService()
    site = {
        "id": "site-comm",
        "inventory_code": "COMM-01",
        "city": "Mumbai",
        "total_cost": 100000.0,
        "image_url": None,
    }

    # 1. include_commercials=True: should contain "Commercial rates valid for 15 days"
    deck_with_comm, _ = service.build_deck(
        sites=[site],
        include_commercials=True,
    )
    prs_comm = Presentation(io.BytesIO(deck_with_comm))
    closing_slide_comm = prs_comm.slides[-1]
    closing_text_comm = " ".join(
        shape.text_frame.text for shape in closing_slide_comm.shapes if shape.has_text_frame
    )
    assert "Commercial rates valid for 15 days" in closing_text_comm

    # 2. include_commercials=False: should NOT contain "Commercial rates valid for 15 days"
    deck_no_comm, _ = service.build_deck(
        sites=[site],
        include_commercials=False,
    )
    prs_no_comm = Presentation(io.BytesIO(deck_no_comm))
    closing_slide_no_comm = prs_no_comm.slides[-1]
    closing_text_no_comm = " ".join(
        shape.text_frame.text for shape in closing_slide_no_comm.shapes if shape.has_text_frame
    )
    assert "Commercial rates valid for 15 days" not in closing_text_no_comm
    assert "BuzzOmni Media Network  •  Confidential" in closing_text_no_comm



