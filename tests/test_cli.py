import types
from pathlib import Path

import pytest

import yt2md.cli as cli


def make_args(**overrides):
    defaults = dict(lang="en", interval=30, max_retries=2, since=None, until=None,
                    cookies_from_browser=None, player_client=None)
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def test_existing_transcript_matches_id_suffix(tmp_path):
    (tmp_path / "Some Title [ABC123].md").write_text("x")
    assert cli.existing_transcript(tmp_path, "ABC123") is not None
    assert cli.existing_transcript(tmp_path, "ZZZ999") is None
    assert cli.existing_transcript(tmp_path / "missing", "ABC123") is None


def test_process_video_retries_on_429(tmp_path, monkeypatch):
    calls, sleeps = [], []

    def fake_fetch(vid, langs, tmpdir, cookies=None, player_client=None):
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

    def fatal_fetch(vid, langs, tmpdir, cookies=None, player_client=None):
        calls.append(vid)
        raise RuntimeError("ERROR: Video unavailable")

    monkeypatch.setattr(cli, "fetch", fatal_fetch)
    with pytest.raises(RuntimeError, match="unavailable"):
        cli.process_video("FAKEID12345", tmp_path, make_args())
    assert len(calls) == 1


def test_date_arg_parses_and_rejects():
    assert cli.date_arg("2026-03-01") == "20260301"
    with pytest.raises(Exception):
        cli.date_arg("03/01/2026")


def test_in_window():
    assert cli.in_window("20260315", "20260301", "20260415")
    assert not cli.in_window("20260228", "20260301", None)
    assert not cli.in_window("20260501", None, "20260415")
    assert cli.in_window("", "20260301", "20260415")  # unknown date kept
    assert cli.in_window("20260315", None, None)


def test_process_video_filters_outside_window(tmp_path, monkeypatch):
    def fake_fetch(vid, langs, tmpdir, cookies=None, player_client=None):
        return {"id": vid, "title": "Old Video", "upload_date": "20200101",
                "subtitles": {}}, None, ""

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    args = make_args(since="20260101")
    assert cli.process_video("VID1", tmp_path, args) is None
    assert not list(tmp_path.glob("*.md"))  # nothing written

    args = make_args(since="20190101", until="20210101")
    out = cli.process_video("VID1", tmp_path, args)
    assert out is not None and out.exists()


def test_main_search_creates_query_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "expand", lambda q, c=None, pc=None: ("kw", ["AAA", "BBB"]))
    monkeypatch.setattr(cli, "missing_js_runtime", lambda: False)
    paths = []

    def fake_process(vid, target, args):
        p = target / f"t [{vid}].md"
        target.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        paths.append(p)
        return p

    monkeypatch.setattr(cli, "process_video", fake_process)
    rc = cli.main(["--search", "soy outlook", "--out-dir", str(tmp_path), "--sleep", "0"])
    assert rc == 0
    assert all(p.parent.name == "Search - soy outlook" for p in paths)
    assert len(paths) == 2
    assert "search 'soy outlook': 2 results" in capsys.readouterr().out


def test_main_threads_cookies_to_expand_and_fetch(tmp_path, monkeypatch):
    captured = {}

    def fake_expand(url, cookies_from_browser=None, player_client=None):
        captured["expand"] = cookies_from_browser
        captured["expand_pc"] = player_client
        return ("pl", ["AAA"])

    def fake_process(vid, target, args):
        captured["fetch"] = args.cookies_from_browser
        captured["fetch_pc"] = args.player_client
        return None

    monkeypatch.setattr(cli, "expand", fake_expand)
    monkeypatch.setattr(cli, "missing_js_runtime", lambda: False)
    monkeypatch.setattr(cli, "process_video", fake_process)
    cli.main(["http://x", "--out-dir", str(tmp_path), "--sleep", "0",
              "--cookies-from-browser", "firefox", "--player-client", "web_safari,mweb"])
    assert captured["expand"] == "firefox"
    assert captured["fetch"] == "firefox"
    assert captured["expand_pc"] == "web_safari,mweb"
    assert captured["fetch_pc"] == "web_safari,mweb"


def test_circuit_breaker_aborts_on_consecutive_429(tmp_path, monkeypatch):
    calls = []

    def boom(vid, target, args):
        calls.append(vid)
        raise RuntimeError("ERROR: HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(cli, "expand", lambda u, c=None, pc=None: ("pl", list("ABCDE")))
    monkeypatch.setattr(cli, "missing_js_runtime", lambda: False)
    monkeypatch.setattr(cli, "process_video", boom)
    rc = cli.main(["http://x", "--out-dir", str(tmp_path), "--sleep", "0"])
    assert rc == 2  # nothing written
    assert len(calls) == cli.CONSECUTIVE_429_LIMIT  # stopped early, didn't grind all 5
    queued = (tmp_path / "_failed.txt").read_text().strip().splitlines()
    assert len(queued) == 5  # 3 attempted + 2 unattempted, all queued for resume


def test_circuit_breaker_resets_on_success(tmp_path, monkeypatch):
    """A 429 between successes must not accumulate toward the abort threshold."""
    seq = iter([
        RuntimeError("429"), None,  # fail, then a real video
        RuntimeError("429"), None,
        RuntimeError("429"), None,
    ])

    def flaky(vid, target, args):
        item = next(seq)
        if isinstance(item, Exception):
            raise item
        p = target / f"t [{vid}].md"
        target.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        return p

    monkeypatch.setattr(cli, "expand", lambda u, c=None, pc=None: ("pl", list("ABCDEF")))
    monkeypatch.setattr(cli, "missing_js_runtime", lambda: False)
    monkeypatch.setattr(cli, "process_video", flaky)
    rc = cli.main(["http://x", "--out-dir", str(tmp_path), "--sleep", "0"])
    assert rc == 1  # partial: 3 written, 3 failed — but NOT aborted early


def test_empty_run_exits_nonzero_when_all_filtered(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "expand", lambda u, c=None, pc=None: ("pl", ["A"]))
    monkeypatch.setattr(cli, "missing_js_runtime", lambda: False)
    monkeypatch.setattr(cli, "process_video", lambda vid, target, args: None)
    rc = cli.main(["http://x", "--out-dir", str(tmp_path), "--sleep", "0"])
    assert rc == 2  # 0 written must not look like success


def test_main_requires_some_input(monkeypatch):
    with pytest.raises(SystemExit):
        cli.main([])


def test_process_video_writes_transcript(tmp_path, monkeypatch):
    def fake_fetch(vid, langs, tmpdir, cookies=None, player_client=None):
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
