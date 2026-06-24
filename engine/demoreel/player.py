"""Interactive HTML chapter player — wrap a rendered mp4 in a single shareable page.

Emits one self-contained dark, brand-styled document (gradient backdrop, indigo accent, a
macOS-ish rounded video card) that references the video, captions, and poster by *relative*
filename — so dropping the .html next to the .mp4/.vtt just works. The chapter rail seeks the
video on click and tracks the active chapter as it plays; keyboard shortcuts cover play/pause,
seek, prev/next chapter, and caption toggle. All CSS and JS are inlined: no CDN, no fonts, no
external JS. Every interpolated string is HTML-escaped before it lands in the document.
"""

from __future__ import annotations

import html
from pathlib import Path

# A system font stack — no network/CDN font fetch.
_FONT_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def build_player(
    out_path: str | Path,
    *,
    video_filename: str,
    title: str,
    chapters: list[tuple[float, str]],
    vtt_filename: str | None = None,
    poster_filename: str | None = None,
    accent: str = "#6C5CE7",
    description: str | None = None,
) -> Path:
    """Write a self-contained chapter-player HTML file and return its path.

    The video / captions / poster are referenced by relative filename so the page is portable
    next to its assets. ``chapters`` is a list of ``(seconds, title)`` pairs; an empty list
    renders the player with no chapter rail.
    """
    out_path = Path(out_path)
    out_path.write_text(
        render_player_html(
            video_filename=video_filename,
            title=title,
            chapters=chapters,
            vtt_filename=vtt_filename,
            poster_filename=poster_filename,
            accent=accent,
            description=description,
        ),
        encoding="utf-8",
    )
    return out_path


def render_player_html(
    *,
    video_filename: str,
    title: str,
    chapters: list[tuple[float, str]],
    vtt_filename: str | None = None,
    poster_filename: str | None = None,
    accent: str = "#6C5CE7",
    description: str | None = None,
) -> str:
    """Pure core: build the full HTML document as a string (no IO)."""
    accent_css = _sanitize_color(accent)
    head = _render_head(title, accent_css)
    video = _render_video(video_filename, vtt_filename, poster_filename)
    rail = _render_rail(chapters)
    desc = (
        f'\n      <p class="desc">{_esc(description)}</p>'
        if description and description.strip()
        else ""
    )
    layout = "with-rail" if chapters else "no-rail"
    script = _render_script(bool(vtt_filename))

    return f"""<!doctype html>
<html lang="en">
{head}
<body>
  <main class="wrap">
    <header class="head">
      <h1>{_esc(title)}</h1>{desc}
    </header>
    <div class="stage {layout}">
      <section class="card">
{video}
      </section>
{rail}
    </div>
    <footer class="credit">made with <span class="mark">demoreel</span></footer>
  </main>
{script}
</body>
</html>
"""


def _render_head(title: str, accent: str) -> str:
    return f"""<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>
    :root {{ --accent: {accent}; }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; }}
    body {{
      min-height: 100vh;
      font-family: {_FONT_STACK};
      color: #E9E9F2;
      background:
        radial-gradient(1200px 600px at 50% -10%, rgba(108,92,231,0.18), transparent 60%),
        linear-gradient(135deg, #1B1B2E 0%, #0B0B12 100%);
      -webkit-font-smoothing: antialiased;
    }}
    .wrap {{ max-width: 1160px; margin: 0 auto; padding: 40px 24px 56px; }}
    .head h1 {{ margin: 0 0 6px; font-size: 26px; font-weight: 650; letter-spacing: -0.01em; }}
    .head .desc {{ margin: 0; color: #A7A7BC; font-size: 15px; line-height: 1.5; }}
    .stage {{ display: grid; gap: 22px; margin-top: 28px; align-items: start; }}
    .stage.with-rail {{ grid-template-columns: minmax(0, 1fr) 320px; }}
    .stage.no-rail {{ grid-template-columns: minmax(0, 1fr); }}
    @media (max-width: 880px) {{
      .stage.with-rail {{ grid-template-columns: minmax(0, 1fr); }}
    }}
    .card {{
      position: relative;
      border-radius: 16px;
      overflow: hidden;
      background: #07070C;
      border: 1px solid rgba(255,255,255,0.07);
      box-shadow: 0 30px 80px -20px rgba(0,0,0,0.7), 0 0 0 1px rgba(0,0,0,0.4);
    }}
    .card::before {{
      content: "";
      display: block;
      height: 32px;
      background: linear-gradient(180deg, #20202E, #15151F);
      border-bottom: 1px solid rgba(255,255,255,0.05);
    }}
    .traffic {{ position: absolute; top: 12px; left: 14px; display: flex; gap: 7px; z-index: 2; }}
    .traffic i {{ width: 11px; height: 11px; border-radius: 50%; display: block; }}
    .traffic .r {{ background: #FF5F57; }}
    .traffic .y {{ background: #FEBC2E; }}
    .traffic .g {{ background: #28C840; }}
    video {{ display: block; width: 100%; height: auto; background: #000; }}
    .rail {{
      border-radius: 14px;
      background: rgba(20,20,32,0.7);
      border: 1px solid rgba(255,255,255,0.06);
      overflow: hidden;
    }}
    .rail h2 {{
      margin: 0;
      padding: 14px 16px;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #8C8CA6;
      border-bottom: 1px solid rgba(255,255,255,0.05);
    }}
    .rail ol {{ list-style: none; margin: 0; padding: 6px; max-height: 60vh; overflow-y: auto; }}
    .chapter {{
      display: flex;
      gap: 12px;
      align-items: baseline;
      width: 100%;
      padding: 11px 12px;
      border: 0;
      border-radius: 9px;
      background: transparent;
      color: #D6D6E4;
      font: inherit;
      text-align: left;
      cursor: pointer;
      transition: background 0.12s ease;
    }}
    .chapter:hover {{ background: rgba(255,255,255,0.05); }}
    .chapter:focus-visible {{ outline: 2px solid var(--accent); outline-offset: -2px; }}
    .chapter .t {{
      flex: 0 0 auto;
      font-variant-numeric: tabular-nums;
      color: #8C8CA6;
      font-size: 13px;
    }}
    .chapter .label {{ flex: 1 1 auto; font-size: 14px; line-height: 1.35; }}
    .chapter.active {{ background: rgba(108,92,231,0.16); color: #FFF; }}
    .chapter.active .t {{ color: var(--accent); }}
    .chapter.active {{ box-shadow: inset 3px 0 0 var(--accent); }}
    .credit {{ margin-top: 30px; text-align: center; color: #6A6A82; font-size: 12px; }}
    .credit .mark {{ color: var(--accent); font-weight: 600; }}
  </style>
</head>"""


def _render_video(
    video_filename: str, vtt_filename: str | None, poster_filename: str | None
) -> str:
    poster = f' poster="{_attr(poster_filename)}"' if poster_filename else ""
    track = (
        f'\n          <track kind="captions" src="{_attr(vtt_filename)}" '
        f'srclang="en" label="English" default>'
        if vtt_filename
        else ""
    )
    return f"""        <div class="traffic"><i class="r"></i><i class="y"></i><i class="g"></i></div>
        <video id="v" controls preload="metadata"{poster} playsinline>
          <source src="{_attr(video_filename)}" type="video/mp4">{track}
        </video>"""


def _render_rail(chapters: list[tuple[float, str]]) -> str:
    if not chapters:
        return ""
    items: list[str] = []
    for seconds, label in chapters:
        secs = max(0.0, float(seconds))
        items.append(
            f'        <li><button class="chapter" type="button" data-t="{_fmt_attr(secs)}">'
            f'<span class="t">{_esc(_fmt_ts(secs))}</span>'
            f'<span class="label">{_esc(label)}</span></button></li>'
        )
    body = "\n".join(items)
    return f"""      <aside class="rail" aria-label="Chapters">
        <h2>Chapters</h2>
        <ol>
{body}
        </ol>
      </aside>"""


def _render_script(has_captions: bool) -> str:
    # Captions are toggled only when a track exists; otherwise the `c` key is inert.
    caption_toggle = (
        "function toggleCaptions(){var t=v.textTracks&&v.textTracks[0];"
        "if(!t)return;t.mode=t.mode==='showing'?'disabled':'showing';}"
        if has_captions
        else "function toggleCaptions(){}"
    )
    return f"""  <script>
  (function () {{
    var v = document.getElementById('v');
    var chapters = Array.prototype.slice.call(document.querySelectorAll('.chapter'));
    var times = chapters.map(function (c) {{ return parseFloat(c.getAttribute('data-t')) || 0; }});

    function seekTo(t) {{ if (!isNaN(t)) {{ v.currentTime = t; v.play(); }} }}

    chapters.forEach(function (c) {{
      c.addEventListener('click', function () {{ seekTo(parseFloat(c.getAttribute('data-t')) || 0); }});
    }});

    function activeIndex(t) {{
      var idx = -1;
      for (var i = 0; i < times.length; i++) {{ if (t + 0.25 >= times[i]) idx = i; else break; }}
      return idx;
    }}

    function highlight() {{
      var idx = activeIndex(v.currentTime);
      chapters.forEach(function (c, i) {{ c.classList.toggle('active', i === idx); }});
    }}
    v.addEventListener('timeupdate', highlight);
    v.addEventListener('loadedmetadata', highlight);

    function jumpChapter(dir) {{
      if (!times.length) return;
      var idx = activeIndex(v.currentTime);
      var next = dir < 0 ? idx - 1 : idx + 1;
      next = Math.max(0, Math.min(times.length - 1, next));
      seekTo(times[next]);
    }}

    {caption_toggle}

    document.addEventListener('keydown', function (e) {{
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      var tag = (e.target && e.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      var k = e.key;
      if (k === ' ' || k === 'k') {{ e.preventDefault(); v.paused ? v.play() : v.pause(); }}
      else if (k === 'ArrowLeft') {{ e.preventDefault(); v.currentTime = Math.max(0, v.currentTime - 5); }}
      else if (k === 'ArrowRight') {{ e.preventDefault(); v.currentTime = v.currentTime + 5; }}
      else if (k === 'j') {{ e.preventDefault(); jumpChapter(-1); }}
      else if (k === 'l') {{ e.preventDefault(); jumpChapter(1); }}
      else if (k === 'c') {{ e.preventDefault(); toggleCaptions(); }}
    }});
  }})();
  </script>"""


def _esc(text: str | None) -> str:
    """HTML-escape text for body/attribute interpolation (quotes included)."""
    return html.escape("" if text is None else str(text), quote=True)


def _attr(value: str | None) -> str:
    """Escape a value destined for a double-quoted attribute (filenames, srcs)."""
    return html.escape("" if value is None else str(value), quote=True)


def _fmt_attr(seconds: float) -> str:
    """Numeric seconds for a data-t attribute — trim a trailing .0 for whole seconds."""
    s = round(max(0.0, float(seconds)), 3)
    return str(int(s)) if s == int(s) else f"{s:g}"


def _fmt_ts(seconds: float) -> str:
    """Format seconds as m:ss, or h:mm:ss when >= one hour."""
    total = int(max(0.0, float(seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _sanitize_color(color: str) -> str:
    """Keep the accent CSS-safe — it lands unquoted inside a CSS custom property.

    Strips characters that could break out of the ``--accent: <value>;`` declaration; falls
    back to the brand indigo if nothing usable remains.
    """
    cleaned = "".join(c for c in (color or "") if c not in "{};\"'<>()\\").strip()
    return cleaned or "#6C5CE7"
