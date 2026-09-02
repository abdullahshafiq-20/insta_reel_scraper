import pytest
from app.utils.validators import extract_shortcode, is_valid_instagram_url, parse_hashtags, parse_mentions
from app.services.scraper.instagram_scraper import parse_page_data


def test_url_validation():
    assert is_valid_instagram_url("https://www.instagram.com/reel/DE48s0_vG4v/") is True
    assert is_valid_instagram_url("https://instagram.com/p/C_12345/") is True
    assert is_valid_instagram_url("https://example.com/not-instagram") is False


def test_shortcode_extraction():
    assert extract_shortcode("https://www.instagram.com/reel/DE48s0_vG4v/") == "DE48s0_vG4v"
    assert extract_shortcode("https://instagram.com/p/C_12345/?igsh=123") == "C_12345"


def test_tag_and_mention_parsing():
    caption = "Enjoying the sunset in #nature and #mountains with @john_doe and @jane!"
    assert parse_hashtags(caption) == ["nature", "mountains"]
    assert parse_mentions(caption) == ["john_doe", "jane"]


def test_parse_page_data():
    sample_html = """
    <html>
      <head>
        <meta property="og:description" content="12.5K likes, 340 comments - creator_handle on August 20, 2026: &quot;Amazing view #nature&quot;.">
        <meta property="og:url" content="https://www.instagram.com/creator_handle/reel/DE48s0_vG4v/">
      </head>
      <body></body>
    </html>
    """
    dom_data = {
        "username": None,
        "caption": None,
        "like_count_raw": None,
        "comment_count_raw": None,
        "share_count_raw": "500",
        "video_src": None,
        "all_video_sources": ["https://video.cdn.instagram.com/reel.mp4"],
    }
    result = parse_page_data(sample_html, "DE48s0_vG4v", "https://www.instagram.com/reel/DE48s0_vG4v/", dom_data)
    assert result["shortcode"] == "DE48s0_vG4v"
    assert result["username"] == "creator_handle"
    assert result["like_count_raw"] == "12.5K"
    assert result["comment_count_raw"] == "340"
    assert result["share_count_raw"] == "500"
    assert result["caption"] == "Amazing view #nature"
    assert result["hashtags"] == ["nature"]
    assert result["video_url"] == "https://video.cdn.instagram.com/reel.mp4"

