import re

from yt2md.render import fmt_ts, render, safe_name

INFO = {
    "id": "VIDEO123456",
    "title": "Test Video",
    "webpage_url": "https://www.youtube.com/watch?v=VIDEO123456",
    "channel": "Test Channel",
    "channel_url": "https://www.youtube.com/channel/UCx",
    "upload_date": "20260115",
    "duration": 125,
    "subtitles": {},
}


def test_fmt_ts():
    assert fmt_ts(0) == "00:00"
    assert fmt_ts(62_000) == "01:02"
    assert fmt_ts(3_723_000) == "1:02:03"


def test_safe_name_strips_forbidden_chars():
    assert safe_name("a|b:c/d", "x") == "a-b-c-d"
    assert safe_name("...   ", "fallback") == "fallback"
    assert len(safe_name("x" * 500, "f")) == 120


def test_render_header_fields():
    md = render(INFO, [(0, "hi")], "en", is_auto=False, interval_s=30)
    assert md.startswith("# Test Video\n")
    assert "- **Video:** <https://www.youtube.com/watch?v=VIDEO123456>" in md
    assert "- **Channel:** [Test Channel](https://www.youtube.com/channel/UCx)" in md
    assert "- **Uploaded:** 2026-01-15" in md
    assert "- **Duration:** 02:05" in md
    assert "- **Captions:** en (manual)" in md


def test_render_auto_caption_label():
    md = render(INFO, [(0, "hi")], "en-orig", is_auto=True, interval_s=30)
    assert "- **Captions:** en-orig (auto-generated)" in md


def test_render_no_captions():
    md = render(INFO, [], "", is_auto=False, interval_s=30)
    assert "- **Captions:** none found" in md
    assert "_No captions available for this video._" in md


def test_render_timestamp_labels_match_t_seconds():
    cues = [(0, "a"), (31_000, "b"), (62_000, "c"), (3_700_000, "d")]
    md = render(INFO, cues, "en", is_auto=False, interval_s=30)
    stamps = re.findall(
        r"\*\*\[([\d:]+)\]\(https://youtu\.be/VIDEO123456\?t=(\d+)\)\*\*", md
    )
    assert len(stamps) == 4
    for label, sec in stamps:
        parts = [int(x) for x in label.split(":")]
        label_s = sum(x * 60**i for i, x in enumerate(reversed(parts)))
        assert label_s == int(sec)


def test_render_paragraph_grouping():
    cues = [(0, "a"), (10_000, "b"), (29_000, "c"), (31_000, "d")]
    md = render(INFO, cues, "en", is_auto=False, interval_s=30)
    assert "**[00:00](https://youtu.be/VIDEO123456?t=0)** a b c" in md
    assert "**[00:31](https://youtu.be/VIDEO123456?t=31)** d" in md
