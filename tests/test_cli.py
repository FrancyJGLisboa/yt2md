import types
from pathlib import Path

import pytest

import yt2md.cli as cli


def make_args(**overrides):
    defaults = dict(lang="en", interval=30, max_retries=2)
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def test_existing_transcript_matches_id_suffix(tmp_path):
    (tmp_path / "Some Title [ABC123].md").write_text("x")
    assert cli.existing_transcript(tmp_path, "ABC123") is not None
    assert cli.existing_transcript(tmp_path, "ZZZ999") is None
    assert cli.existing_transcript(tmp_path / "missing", "ABC123") is None


def test_process_video_retries_on_429(tmp_path, monkeypatch):
    calls, sleeps = [], []

    def fake_fetch(vid, langs, tmpdir):
        calls.append(vid)
        if len(calls) <= 2:
            raise RuntimeError("ERROR: HTTP Error 429: Too Many Requests")
        return {"id": vid, "title": "Retry Test", "subtitles": {}}, None, ""

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    monkeypatch.setattr(cli.time, "sleep", sleeps.append)

    out = cli.process_video("FAKEID12345", tmp_path, make_args())
    assert out.name == "Retry Test [FAKEID12345].md"
    assert len(calls) == 3
    assert sleeps == [15, 60]


def test_process_video_gives_up_after_max_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli, "fetch",
        lambda *a: (_ for _ in ()).throw(RuntimeError("HTTP Error 429")),
    )
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="429"):
        cli.process_video("FAKEID12345", tmp_path, make_args(max_retries=1))


def test_process_video_no_retry_on_fatal_error(tmp_path, monkeypatch):
    calls = []

    def fatal_fetch(vid, langs, tmpdir):
        calls.append(vid)
        raise RuntimeError("ERROR: Video unavailable")

    monkeypatch.setattr(cli, "fetch", fatal_fetch)
    with pytest.raises(RuntimeError, match="unavailable"):
        cli.process_video("FAKEID12345", tmp_path, make_args())
    assert len(calls) == 1


def test_process_video_writes_transcript(tmp_path, monkeypatch):
    def fake_fetch(vid, langs, tmpdir):
        sub = Path(tmpdir) / f"{vid}.en.json3"
        sub.write_text('{"events": [{"tStartMs": 0, "segs": [{"utf8": "hello"}]}]}')
        info = {"id": vid, "title": "A/B|C", "subtitles": {"en": []}, "duration": 5}
        return info, sub, "en"

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    out = cli.process_video("VID42", tmp_path, make_args())
    assert out.name == "A-B-C [VID42].md"
    md = out.read_text()
    assert "**[00:00](https://youtu.be/VID42?t=0)** hello" in md
    assert "- **Captions:** en (manual)" in md
