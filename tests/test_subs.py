import types
from pathlib import Path

import yt2md.subs as subs
from yt2md.subs import parse_json3

FIXTURE = Path(__file__).parent / "fixtures" / "sample.json3"


def test_expand_passes_cookies_from_browser(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        return types.SimpleNamespace(
            returncode=0,
            stdout='{"_type": "playlist", "title": "t", "entries": [{"id": "a"}]}',
            stderr="",
        )

    monkeypatch.setattr(subs.subprocess, "run", fake_run)
    title, ids = subs.expand("http://x", cookies_from_browser="firefox")
    assert title == "t" and ids == ["a"]
    assert "--cookies-from-browser" in captured["cmd"]
    assert "firefox" in captured["cmd"]


def test_expand_omits_cookies_when_none(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        return types.SimpleNamespace(
            returncode=0, stdout='{"_type": "video", "id": "a"}', stderr=""
        )

    monkeypatch.setattr(subs.subprocess, "run", fake_run)
    subs.expand("http://x")
    assert "--cookies-from-browser" not in captured["cmd"]


def test_fetch_passes_cookies_from_browser(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        (tmp_path / "vid.info.json").write_text(
            '{"id": "vid", "title": "T", "subtitles": {}}'
        )
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subs.subprocess, "run", fake_run)
    info, sub, lang = subs.fetch(
        "vid", "en", str(tmp_path), cookies_from_browser="chrome"
    )
    assert info["id"] == "vid"
    assert "--cookies-from-browser" in captured["cmd"]
    assert "chrome" in captured["cmd"]


def test_throttle_args_reach_expand_and_fetch(monkeypatch, tmp_path):
    """Request-level throttling must be on every yt-dlp call (checks 2-3)."""
    captured = {}

    def fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        (tmp_path / "vid.info.json").write_text('{"id": "vid", "title": "T", "subtitles": {}}')
        return types.SimpleNamespace(
            returncode=0, stdout='{"_type": "video", "id": "a"}', stderr="")

    monkeypatch.setattr(subs.subprocess, "run", fake_run)

    subs.expand("http://x")
    assert "--sleep-requests" in captured["cmd"]
    assert "--retry-sleep" in captured["cmd"]
    assert "--sleep-subtitles" not in captured["cmd"]  # only meaningful for subtitle fetch

    subs.fetch("vid", "en", str(tmp_path))
    assert "--sleep-requests" in captured["cmd"]
    assert "--sleep-subtitles" in captured["cmd"]


def test_player_client_opt_in(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        (tmp_path / "vid.info.json").write_text('{"id": "vid", "title": "T", "subtitles": {}}')
        return types.SimpleNamespace(
            returncode=0, stdout='{"_type": "video", "id": "a"}', stderr="")

    monkeypatch.setattr(subs.subprocess, "run", fake_run)

    subs.fetch("vid", "en", str(tmp_path))  # default: no client override
    assert "--extractor-args" not in captured["cmd"]

    subs.fetch("vid", "en", str(tmp_path), player_client="web_safari,mweb")
    assert "--extractor-args" in captured["cmd"]
    assert "youtube:player_client=web_safari,mweb" in captured["cmd"]


def test_stale_ytdlp_warning(monkeypatch):
    from datetime import date

    monkeypatch.setattr(subs, "ytdlp_version", lambda: "2026.01.01")
    assert subs.stale_ytdlp_warning(today=date(2026, 6, 23)) is not None  # ~173 days

    monkeypatch.setattr(subs, "ytdlp_version", lambda: "2026.06.09")
    assert subs.stale_ytdlp_warning(today=date(2026, 6, 23)) is None  # 14 days, fresh

    monkeypatch.setattr(subs, "ytdlp_version", lambda: None)  # probe failed
    assert subs.stale_ytdlp_warning(today=date(2026, 6, 23)) is None  # no false alarm


def test_parse_json3_extracts_cues():
    cues = parse_json3(FIXTURE)
    assert cues == [
        (0, "hello world"),
        (2000, "second line"),
        (35000, "after the gap"),
        (70000, "final words"),
    ]


def test_parse_json3_skips_segless_and_newline_only_events():
    cues = parse_json3(FIXTURE)
    starts = [start for start, _ in cues]
    assert 1500 not in starts  # newline-only event dropped
    assert 5000 not in starts  # seg-less event dropped
