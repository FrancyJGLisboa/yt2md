"""Markdown rendering: timestamps, headers, transcript paragraphs."""

import re


def fmt_ts(ms: int) -> str:
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def safe_name(name: str, fallback: str) -> str:
    name = re.sub(r'[/\\:*?"<>|]', "-", name).strip(". ")
    return name[:120] or fallback


def render(info: dict, cues: list[tuple[int, str]], lang: str, is_auto: bool,
           interval_s: int) -> str:
    vid = info["id"]
    base = f"https://youtu.be/{vid}"
    upload = info.get("upload_date", "")
    upload_fmt = f"{upload[:4]}-{upload[4:6]}-{upload[6:]}" if len(upload) == 8 else "unknown"

    lines = [f"# {info.get('title', vid)}", ""]
    lines.append(f"- **Video:** <{info.get('webpage_url', base)}>")
    channel = info.get("channel") or info.get("uploader") or "unknown"
    if info.get("channel_url"):
        lines.append(f"- **Channel:** [{channel}]({info['channel_url']})")
    else:
        lines.append(f"- **Channel:** {channel}")
    lines.append(f"- **Uploaded:** {upload_fmt}")
    lines.append(f"- **Duration:** {fmt_ts(int(info.get('duration', 0)) * 1000)}")
    cap_kind = "auto-generated" if is_auto else "manual"
    lines.append(f"- **Captions:** {lang} ({cap_kind})" if lang else "- **Captions:** none found")
    lines += ["", "---", "", "## Transcript", ""]

    if not cues:
        lines.append("_No captions available for this video._")
        return "\n".join(lines) + "\n"

    para_start = cues[0][0]
    para_text: list[str] = []
    for start_ms, text in cues:
        if para_text and start_ms - para_start >= interval_s * 1000:
            sec = para_start // 1000
            lines.append(f"**[{fmt_ts(para_start)}]({base}?t={sec})** {' '.join(para_text)}")
            lines.append("")
            para_start, para_text = start_ms, []
        para_text.append(text)
    sec = para_start // 1000
    lines.append(f"**[{fmt_ts(para_start)}]({base}?t={sec})** {' '.join(para_text)}")
    return "\n".join(lines) + "\n"
