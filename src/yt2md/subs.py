"""yt-dlp interaction: URL expansion, subtitle download, json3 parsing."""

import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

JS_RUNTIMES = ("deno", "node", "bun", "qjs")
YTDLP_STALE_DAYS = 45  # YouTube extraction tends to break past this age


def ytdlp_cmd(*args: str) -> list[str]:
    """yt-dlp lives in this package's venv — call it as a module so the
    command works even when no yt-dlp executable is on PATH."""
    return [sys.executable, "-m", "yt_dlp", *args]


def missing_js_runtime() -> bool:
    """YouTube extraction needs a JS runtime (deno by default) since 2025;
    without one, subtitle downloads fail."""
    return not any(shutil.which(rt) for rt in JS_RUNTIMES)


def ytdlp_version() -> str | None:
    """The installed yt-dlp's version string (a YYYY.MM.DD date), or None."""
    try:
        r = subprocess.run(ytdlp_cmd("--version"), capture_output=True,
                           text=True, timeout=15)
        return r.stdout.strip() or None
    except Exception:
        return None


def stale_ytdlp_warning(today: date | None = None) -> str | None:
    """yt-dlp versions are release dates; a stale one is the #1 cause of
    silent extraction breakage as YouTube changes. Returns an upgrade hint
    when the installed version is older than YTDLP_STALE_DAYS, else None."""
    v = ytdlp_version()
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", v or "")
    if not m:
        return None
    released = date(int(m[1]), int(m[2]), int(m[3]))
    age = ((today or date.today()) - released).days
    if age > YTDLP_STALE_DAYS:
        return (f"yt-dlp is {age} days old ({v}) — stale yt-dlp silently breaks "
                f"YouTube extraction. Upgrade: uv tool upgrade yt2md")
    return None


def cookies_args(cookies_from_browser: str | None) -> list[str]:
    """yt-dlp --cookies-from-browser passthrough (empty when not requested)."""
    return ["--cookies-from-browser", cookies_from_browser] if cookies_from_browser else []


def throttle_args(subtitles: bool = False) -> list[str]:
    """Native yt-dlp request-level throttling. Paces the multiple HTTP requests
    *inside* a single yt-dlp call — the burst that actually trips HTTP 429 —
    which a between-video sleep in the caller structurally cannot reach.
    --retry-sleep backs off exponentially (1s..60s) on yt-dlp's own 429s."""
    args = ["--sleep-requests", "0.75", "--retry-sleep", "http:exp=1:60"]
    if subtitles:
        args += ["--sleep-subtitles", "3"]
    return args


def player_client_args(player_client: str | None) -> list[str]:
    """Opt-in: impersonate specific YouTube client(s), e.g. "web_safari,mweb".
    A different client hits a different quota bucket and often dodges 429.
    Off by default — which clients work shifts as yt-dlp updates."""
    return (["--extractor-args", f"youtube:player_client={player_client}"]
            if player_client else [])


def expand(url: str, cookies_from_browser: str | None = None,
           player_client: str | None = None) -> tuple[str | None, list[str]]:
    """Resolve a URL to (playlist_title | None, [video_id, ...])."""
    cmd = ytdlp_cmd("--flat-playlist", "-J", "--no-warnings",
                    *throttle_args(), *player_client_args(player_client),
                    *cookies_args(cookies_from_browser), url)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"could not resolve {url}:\n{result.stderr.strip()}")
    data = json.loads(result.stdout)
    if data.get("_type") == "playlist":
        ids = [e["id"] for e in data.get("entries") or [] if e and e.get("id")]
        return data.get("title") or "playlist", ids
    return None, [data["id"]]


def fetch(video_id: str, langs: str, tmpdir: str,
          cookies_from_browser: str | None = None,
          player_client: str | None = None) -> tuple[dict, Path | None, str]:
    """Download info.json + subtitles. Returns (info, sub_path, lang)."""
    # exact lang + "-orig" variant only — a wildcard like "en.*" matches every
    # auto-translated track (en-de, en-fr, ...) and triggers HTTP 429
    sub_langs = ",".join(
        f"{lang.strip()},{lang.strip()}-orig" for lang in langs.split(",")
    )
    cmd = ytdlp_cmd(
        "--skip-download", "--write-info-json",
        "--write-subs", "--write-auto-subs",
        "--sub-langs", sub_langs, "--sub-format", "json3",
        *throttle_args(subtitles=True), *player_client_args(player_client),
        *cookies_args(cookies_from_browser),
        "-o", "%(id)s.%(ext)s", "-P", tmpdir, "--no-progress",
        f"https://www.youtube.com/watch?v={video_id}",
    )
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed:\n{result.stderr.strip()}")

    info_files = list(Path(tmpdir).glob("*.info.json"))
    if not info_files:
        raise RuntimeError("no metadata written")
    info = json.loads(info_files[0].read_text())

    # requested_subtitles is null in info.json with --skip-download, so find
    # the downloaded files by name: {id}.{lang}.json3
    vid = info["id"]
    wanted = [lang.strip() for lang in langs.split(",")]
    manual_langs = set(info.get("subtitles") or {})
    candidates = {}
    for path in Path(tmpdir).glob(f"{vid}.*.json3"):
        lang = path.name[len(vid) + 1 : -len(".json3")]
        candidates[lang] = path

    def rank(lang: str) -> tuple[int, int]:
        base = lang.split("-")[0]
        try:
            pos = next(i for i, w in enumerate(wanted) if base == w or lang.startswith(w))
        except StopIteration:
            pos = len(wanted)
        return (pos, 0 if lang in manual_langs else 1)

    for lang in sorted(candidates, key=rank):
        return info, candidates[lang], lang
    return info, None, ""


def parse_json3(path: Path) -> list[tuple[int, str]]:
    """Returns [(start_ms, text), ...] cues."""
    data = json.loads(path.read_text())
    cues = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(seg.get("utf8", "") for seg in segs)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            cues.append((event.get("tStartMs", 0), text))
    return cues
