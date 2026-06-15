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
