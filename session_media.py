"""Session media archiver: copies visuals produced by CLI agents next to the archived conversation.

Layout (same for every agent):  <session_dir>/media/<title>.<ext>
Sources:
  Claude Code : mcp__visualize__show_widget widget_code (.svg / .html), SendUserFile files,
                [Image: source: ...] paths, Read tool image paths, inline base64 image blocks
  Codex       : ~/.codex/generated_images/<session id>/*  (imagegen outputs)
  Antigravity : ~/.gemini/antigravity/brain/<cid>/ images and videos (top level, scratch/)
Not covered (no local source data): ChatGPT web export (text only), Command Code (jsonl has no image data).
Used by the vault archiver (scripts/auto_archive_daemon.py); every function is fail-safe.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import unicodedata

MEDIA_DIRNAME = "media"
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
MEDIA_EXT = IMG_EXT | {".mp4", ".webm", ".mov", ".html", ".pdf"}
MAX_BYTES = 40 * 1024 * 1024
WIDGET_TOOL = "show_widget"
_MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}

SVG_DEFAULT_STYLE = (
    "<style>svg{--color-text-primary:#1f2328;--color-text-secondary:#57606a;--color-text-tertiary:#8c959f;"
    "--color-border-tertiary:#d0d7de;--color-border-secondary:#afb8c1;--color-background-primary:#ffffff;"
    "--color-background-secondary:#f6f8fa}</style>"
)


def safe_name(title, default="gorsel", max_len=80):
    t = unicodedata.normalize("NFC", str(title or "")).strip()
    t = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "_", t)
    t = re.sub(r"\s+", "_", t).strip("._ ")
    return t[:max_len] or default


def standalone_svg(code):
    """Make a widget SVG openable on its own: xmlns plus default colour variables."""
    s = code.strip()
    m = re.match(r"<svg\b([^>]*)>", s, re.I)
    if not m:
        return s
    attrs = m.group(1)
    if not re.search(r"\sxmlns\s*=", " " + attrs):
        attrs += ' xmlns="http://www.w3.org/2000/svg"'
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + "<svg%s>%s" % (attrs, SVG_DEFAULT_STYLE) + s[m.end():]


def _item(name, ext, data=None, src=None):
    return {"name": safe_name(name), "ext": ext.lower(), "data": data, "src": src}


def _from_path(path, name=None):
    ext = os.path.splitext(path)[1].lower()
    if ext not in MEDIA_EXT or not os.path.isfile(path):
        return None
    try:
        if os.path.getsize(path) <= 0 or os.path.getsize(path) > MAX_BYTES:
            return None
    except OSError:
        return None
    return _item(name or os.path.splitext(os.path.basename(path))[0], ext, src=path)


def parse_claude_media(jsonl_path):
    """Extract media items from one Claude Code session JSONL."""
    items, seen = [], set()

    def add(it):
        if not it:
            return
        key = it["src"] or hashlib.sha1(it["data"]).hexdigest()
        if key in seen:
            return
        seen.add(key)
        items.append(it)

    try:
        f = open(jsonl_path, "r", encoding="utf-8", errors="ignore")
    except OSError:
        return items
    with f:
        for line in f:
            if not any(k in line for k in ("widget_code", "SendUserFile", "[Image: source:", '"Read"', '"base64"')):
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            content = (obj.get("message") or {}).get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "tool_use":
                    name, inp = str(b.get("name", "")), b.get("input") or {}
                    if name.endswith(WIDGET_TOOL) and isinstance(inp.get("widget_code"), str):
                        code = inp["widget_code"]
                        if not code.strip():
                            continue
                        title = inp.get("title") or "widget"
                        if re.match(r"\s*<svg[\s>]", code, re.I):
                            add(_item(title, ".svg", data=standalone_svg(code).encode("utf-8")))
                        else:
                            add(_item(title, ".html", data=code.encode("utf-8")))
                    elif name == "SendUserFile":
                        for p in inp.get("files") or []:
                            if isinstance(p, str):
                                add(_from_path(p))
                    elif name == "Read" and isinstance(inp.get("file_path"), str):
                        if os.path.splitext(inp["file_path"])[1].lower() in IMG_EXT:
                            add(_from_path(inp["file_path"]))
                elif bt == "text" and isinstance(b.get("text"), str):
                    for m in re.finditer(r"\[Image: source: ([^\]\n]+)\]", b["text"]):
                        add(_from_path(m.group(1).strip()))
                elif bt == "image":
                    src = b.get("source") or {}
                    ext = _MIME_EXT.get(src.get("media_type"))
                    if ext and src.get("type") == "base64" and src.get("data"):
                        try:
                            raw = base64.b64decode(src["data"])
                        except Exception:
                            continue
                        if 0 < len(raw) <= MAX_BYTES:
                            add(_item("yapistirilan_gorsel_" + hashlib.sha1(raw).hexdigest()[:8], ext, data=raw))
    return items


def codex_media(session_id, codex_home=None):
    home = codex_home or os.path.expanduser("~/.codex")
    d = os.path.join(home, "generated_images", str(session_id))
    out = []
    if session_id and os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            it = _from_path(os.path.join(d, fn))
            if it:
                out.append(it)
    return out


def antigravity_media(cid, brain_dir):
    root = os.path.join(brain_dir, cid)
    out = []
    for sub in ("", "scratch"):
        d = os.path.join(root, sub) if sub else root
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if os.path.splitext(fn)[1].lower() in (MEDIA_EXT - {".html", ".pdf"}):
                it = _from_path(os.path.join(d, fn))
                if it:
                    out.append(it)
    return out


def _digest(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_media(session_dir, items):
    """Write items to <session_dir>/media. Idempotent: identical content is never duplicated,
    different content under the same name gets _2, _3 ... Returns the list of newly written paths."""
    written = []
    if not items:
        return written
    mdir = os.path.join(session_dir, MEDIA_DIRNAME)
    for it in items:
        try:
            data = it["data"]
            digest = hashlib.sha1(data).hexdigest() if data is not None else _digest(it["src"])
            os.makedirs(mdir, exist_ok=True)
            # Same bytes already archived under any name (e.g. pasted image + its [Image: source] file): skip.
            if any(_digest(os.path.join(mdir, fn)) == digest for fn in os.listdir(mdir)
                   if os.path.isfile(os.path.join(mdir, fn))):
                continue
            n, target = 1, None
            while True:
                cand = os.path.join(mdir, it["name"] + ("" if n == 1 else "_%d" % n) + it["ext"])
                if not os.path.exists(cand):
                    target = cand
                    break
                n += 1
            if target:
                if data is not None:
                    with open(target, "wb") as f:
                        f.write(data)
                else:
                    shutil.copy2(it["src"], target)
                written.append(target)
        except Exception:
            continue
    return written


def archive_session_media(agent, session_dir, **kw):
    """Entry point for the archiver. agent: 'claude' (jsonl=), 'codex' (session_id=), 'antigravity' (cid=, brain_dir=)."""
    try:
        if agent == "claude":
            items = parse_claude_media(kw["jsonl"])
        elif agent == "codex":
            items = codex_media(kw["session_id"], kw.get("codex_home"))
        elif agent == "antigravity":
            items = antigravity_media(kw["cid"], kw["brain_dir"])
        else:
            return []
        return write_media(session_dir, items)
    except Exception:
        return []
