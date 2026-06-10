from pathlib import Path

from yt2md.subs import parse_json3

FIXTURE = Path(__file__).parent / "fixtures" / "sample.json3"


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
