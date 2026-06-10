"""CLI: batch orchestration, search, date filtering, resume, retry/backoff."""

import argparse
import re
import sys
import tempfile
import time
from pathlib import Path

from .subs import expand, fetch, missing_js_runtime, parse_json3
from .render import render, safe_name

RETRY_BACKOFF_S = [15, 60, 240]  # wait per retry attempt on HTTP 429


def date_arg(value: str) -> str:
    """YYYY-MM-DD → YYYYMMDD (yt-dlp's upload_date format)."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not m:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}")
    return "".join(m.groups())


def in_window(upload_date: str, since: str | None, until: str | None) -> bool:
    """True if the video's upload date falls inside [since, until]. Videos
    with no parseable date are kept (never silently dropped)."""
    if not re.fullmatch(r"\d{8}", upload_date or ""):
        return True
    if since and upload_date < since:
        return False
    if until and upload_date > until:
        return False
    return True


def existing_transcript(out_dir: Path, video_id: str) -> Path | None:
    if not out_dir.is_dir():
        return None
    suffix = f"[{video_id}].md"
    return next((p for p in out_dir.iterdir() if p.name.endswith(suffix)), None)


def process_video(video_id: str, out_dir: Path, args) -> Path | None:
    """Fetch one video with 429-retry. Returns written file path, or None if
    the video falls outside the --since/--until window."""
    for attempt in range(args.max_retries + 1):
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                info, sub_path, lang = fetch(video_id, args.lang, tmpdir)
                if not in_window(info.get("upload_date", ""), args.since, args.until):
                    return None
                cues = parse_json3(sub_path) if sub_path else []
                is_auto = lang not in (info.get("subtitles") or {})
                md = render(info, cues, lang, is_auto, args.interval)
            break
        except RuntimeError as exc:
            transient = "429" in str(exc) or "Too Many Requests" in str(exc)
            if transient and attempt < args.max_retries:
                wait = RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)]
                print(f"  rate-limited, retrying in {wait}s "
                      f"(attempt {attempt + 2}/{args.max_retries + 1})", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    out_dir.mkdir(parents=True, exist_ok=True)
    title = safe_name(info.get("title", video_id), video_id)
    out_path = out_dir / f"{title} [{video_id}].md"
    out_path.write_text(md)
    if not cues:
        print(f"  warning: no captions found for {video_id}", file=sys.stderr)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yt2md",
        description="Extract YouTube transcripts as Markdown with clickable timestamps.",
    )
    parser.add_argument("urls", nargs="*", help="video or playlist URL(s)")
    parser.add_argument("--from-file", help="file with one URL per line (# = comment)")
    parser.add_argument("--search", help="YouTube search query instead of / besides URLs")
    parser.add_argument("--search-limit", type=int, default=10,
                        help="max search results to transcribe (default: 10)")
    parser.add_argument("--since", type=date_arg, default=None,
                        help="only videos uploaded on/after this date (YYYY-MM-DD)")
    parser.add_argument("--until", type=date_arg, default=None,
                        help="only videos uploaded on/before this date (YYYY-MM-DD)")
    parser.add_argument("--lang", default="en",
                        help="comma-separated language preference (default: en)")
    parser.add_argument("--out-dir", default=".", help="output directory (default: cwd)")
    parser.add_argument("--interval", type=int, default=30,
                        help="seconds per paragraph (default: 30)")
    parser.add_argument("--limit", type=int, default=0,
                        help="max videos per playlist (default: no limit)")
    parser.add_argument("--sleep", type=float, default=3.0,
                        help="seconds between videos (default: 3)")
    parser.add_argument("--max-retries", type=int, default=2,
                        help="retries per video on rate limit (default: 2)")
    args = parser.parse_args(argv)

    urls = list(args.urls)
    if args.from_file:
        for line in Path(args.from_file).expanduser().read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    if not urls and not args.search:
        parser.error("no input given (pass URLs, --from-file, or --search)")

    if missing_js_runtime():
        print("warning: no JavaScript runtime found — YouTube extraction needs one.\n"
              "         install deno:  brew install deno  (macOS)  or see\n"
              "         https://github.com/yt-dlp/yt-dlp/wiki/EJS", file=sys.stderr)

    out_root = Path(args.out_dir).expanduser()

    # resolve every input to (video_id, target_dir) jobs
    jobs: list[tuple[str, Path]] = []
    failed: list[str] = []
    seen: set[str] = set()

    def add_jobs(ids: list[str], target: Path) -> None:
        for vid in ids:
            if vid not in seen:
                seen.add(vid)
                jobs.append((vid, target))

    if args.search:
        try:
            _, ids = expand(f"ytsearch{args.search_limit}:{args.search}")
            print(f"search '{args.search}': {len(ids)} results")
            # deterministic folder name so re-running the same search resumes
            add_jobs(ids, out_root / safe_name(f"Search - {args.search}", "search"))
        except RuntimeError as exc:
            print(f"FAILED search '{args.search}': {exc}", file=sys.stderr)
            failed.append(f"ytsearch:{args.search}")

    for url in urls:
        try:
            playlist_title, ids = expand(url)
        except RuntimeError as exc:
            print(f"FAILED to resolve {url}: {exc}", file=sys.stderr)
            failed.append(url)
            continue
        target = out_root / safe_name(playlist_title, "playlist") if playlist_title else out_root
        if playlist_title:
            print(f"playlist '{playlist_title}': {len(ids)} videos"
                  + (f" (limiting to {args.limit})" if args.limit and len(ids) > args.limit else ""))
        if args.limit:
            ids = ids[: args.limit]
        add_jobs(ids, target)

    written: list[Path] = []
    skipped = 0
    filtered = 0
    for i, (vid, target) in enumerate(jobs):
        already = existing_transcript(target, vid)
        if already:
            print(f"[{i + 1}/{len(jobs)}] skip (exists): {already.name}")
            skipped += 1
            continue
        if (written or filtered) and args.sleep:
            time.sleep(args.sleep)
        url = f"https://www.youtube.com/watch?v={vid}"
        try:
            path = process_video(vid, target, args)
            if path is None:
                print(f"[{i + 1}/{len(jobs)}] skip (outside {args.since or '...'}"
                      f"..{args.until or '...'} window): {url}")
                filtered += 1
                continue
            written.append(path)
            print(f"[{i + 1}/{len(jobs)}] wrote {path}")
        except Exception as exc:
            print(f"[{i + 1}/{len(jobs)}] FAILED {url}: {exc}", file=sys.stderr)
            failed.append(url)

    window_note = f", {filtered} outside date window" if (args.since or args.until) else ""
    print(f"\ndone: {len(written)} written, {skipped} skipped (already existed)"
          f"{window_note}, {len(failed)} failed")
    if failed:
        out_root.mkdir(parents=True, exist_ok=True)
        failed_file = out_root / "_failed.txt"
        failed_file.write_text("\n".join(failed) + "\n")
        print(f"failed URLs saved to {failed_file} — retry with: "
              f"yt2md --from-file '{failed_file}'", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
