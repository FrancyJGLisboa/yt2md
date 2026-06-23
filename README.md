# yt2md

Extract YouTube transcripts as Markdown with clickable timestamps.

Feed it video URLs, playlist URLs, or a file of URLs. Each video becomes a
`.md` file with a metadata header (title, channel, upload date, duration,
caption type) and a transcript whose paragraph timestamps link straight to
that second of the video.

```markdown
# [1hr Talk] Intro to Large Language Models

- **Video:** <https://www.youtube.com/watch?v=zjkBMFhNj_g>
- **Channel:** [Andrej Karpathy](https://www.youtube.com/channel/UCXUPKJO5MZQN11PqgIvyuvQ)
- **Uploaded:** 2023-11-23
- **Duration:** 59:48
- **Captions:** en-orig (auto-generated)

---

## Transcript

**[00:00](https://youtu.be/zjkBMFhNj_g?t=0)** hi everyone so recently I gave a 30-minute talk...

**[00:31](https://youtu.be/zjkBMFhNj_g?t=31)** hypothetical directory so for example...
```

## Install

```bash
uv tool install git+https://github.com/FrancyJGLisboa/yt2md
```

(or `pipx install git+https://github.com/FrancyJGLisboa/yt2md`)

**Prerequisite:** a JavaScript runtime — YouTube extraction requires one
since 2025. On macOS: `brew install deno`. yt2md warns at startup if none
is found.

## Usage

```bash
yt2md URL [URL ...]                          # one .md per video, in cwd
yt2md --out-dir ~/Transcripts PLAYLIST_URL   # → ~/Transcripts/<Playlist Name>/*.md
yt2md --from-file urls.txt                   # one URL per line, # = comment
yt2md --lang pt URL                          # Portuguese captions
yt2md --limit 5 PLAYLIST_URL                 # first 5 videos only

# no URL needed — search YouTube and transcribe the results
yt2md --search "soybean market outlook" --search-limit 25
yt2md --search "fed rate decision" --since 2026-05-01 --until 2026-06-01
```

| Option | Default | Meaning |
|---|---|---|
| `--search` | — | YouTube search query; results go to a `Search - <query>/` folder |
| `--search-limit` | `10` | max search results to transcribe |
| `--since` / `--until` | — | only videos uploaded inside this window (YYYY-MM-DD); applies to any input |
| `--lang` | `en` | comma-separated caption language preference |
| `--out-dir` | `.` | output directory; playlists get a subfolder |
| `--interval` | `30` | seconds of speech per transcript paragraph |
| `--limit` | none | max videos taken from each playlist |
| `--sleep` | `3` | pause between videos, jittered 0.6–1.6× (rate-limit politeness) |
| `--max-retries` | `2` | retries per video on HTTP 429 (15s/60s/240s backoff) |
| `--cookies-from-browser` | — | load cookies from a browser (`firefox`, `chrome`, `safari`, …) to pass YouTube bot/sign-in checks on large batches |
| `--player-client` | — | opt-in: yt-dlp `youtube` player client(s) to impersonate (e.g. `web_safari,mweb`) — a different quota bucket that often dodges 429. Brittle; off by default |

Behavior on batches:

- **Resume-safe** — files are named `Title [videoID].md`; videos whose ID
  already exists in the target folder are skipped, so interrupting a long
  playlist and re-running the same command picks up where it left off.
- **Failures never stop the batch** — failed URLs are reported, written to
  `_failed.txt` at the `--out-dir` root (not inside playlist subfolders,
  since one run can span several), and the run exits 1. Retry only the
  failures with `yt2md --from-file <out-dir>/_failed.txt`.
- **Circuit-breaker** — after 3 consecutive HTTP 429 failures the batch
  aborts early (rather than grinding backoff on every remaining video); the
  unattempted videos are queued into `_failed.txt` so a re-run resumes them.
  The hint: re-run with `--cookies-from-browser`.
- **Exit codes** — `0` success, `1` finished with some failures, `2` wrote
  **zero** transcripts (empty/degraded run — the reason is printed, e.g. all
  filtered by date window, all 429, or no input resolved). `2` exists so a
  hollow run can't masquerade as success in a script or pipeline.
- Manual captions are preferred over auto-generated when both exist.

Date-window caveats: YouTube search doesn't expose upload dates cheaply, so
`--since`/`--until` are enforced by checking each candidate's metadata —
out-of-window videos still cost one metadata request each, and they are
reported as skipped (never silently dropped). Search results are ranked by
relevance, so a narrow window over a broad query may filter out most hits;
raise `--search-limit` to compensate. Videos with no parseable upload date
are kept.

## Troubleshooting

- **"No supported JavaScript runtime"** — install deno (see above).
- **Extraction suddenly returns nothing / cryptic errors** — almost always a
  stale yt-dlp; YouTube changes often. yt2md warns at startup when yt-dlp is
  >45 days old. Fix: `uv tool upgrade yt2md`.
- **HTTP 429 Too Many Requests** — YouTube rate-limited you. yt2md already
  throttles at the request level (`--sleep-requests`/`--sleep-subtitles`),
  jitters the between-video pause, and retries with backoff. If it persists,
  in rough order of effectiveness: pass `--cookies-from-browser` (authenticated
  requests have far higher limits), try `--player-client web_safari,mweb`,
  raise `--sleep`, or wait a few minutes and re-run (it resumes).

## Development

```bash
git clone https://github.com/FrancyJGLisboa/yt2md && cd yt2md
uv run pytest
```

Tests are fully offline (fixtures + mocks); nothing in the suite touches
YouTube.
