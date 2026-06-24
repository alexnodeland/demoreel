"""Unit tests for demoreel.player.

Exercises the pure HTML-string core (no browser, no ffmpeg): the document shell, the
<video>/<track>/poster wiring, the chapter rail (timestamps + data-t seconds), the
empty-chapters path, timestamp formatting, and — most importantly — the _esc / _attr
security guard that escapes every interpolated string so user-supplied titles and chapter
labels can never inject raw markup.
"""

from __future__ import annotations

import pytest

from demoreel.player import (
    _esc,
    _fmt_attr,
    _fmt_ts,
    _sanitize_color,
    build_player,
    render_player_html,
)

ACCENT = "#6C5CE7"


def _build(tmp_path, **kw):
    base: dict = {
        "video_filename": "demo.mp4",
        "title": "My Demo",
        "chapters": [(0.0, "Intro"), (12.0, "The Feature"), (75.0, "Wrap up")],
    }
    base.update(kw)
    out = tmp_path / "player.html"
    return build_player(out, **base)


# --------------------------------------------------------------------------- #
# build_player — file IO + document shape
# --------------------------------------------------------------------------- #
def test_build_player_writes_file_and_returns_path(tmp_path):
    out = _build(tmp_path)
    assert out.exists()
    assert out == tmp_path / "player.html"
    assert out.read_text(encoding="utf-8").strip() != ""


def test_build_player_accepts_str_path(tmp_path):
    out = build_player(
        str(tmp_path / "p.html"),
        video_filename="demo.mp4",
        title="T",
        chapters=[],
    )
    assert out.exists()


def test_document_is_complete_dark_html(tmp_path):
    html = _build(tmp_path).read_text(encoding="utf-8")
    assert html.lstrip().startswith("<!doctype html>")
    assert "<html" in html and "</html>" in html
    assert "<video" in html
    assert "</body>" in html and "</head>" in html


def test_video_filename_referenced_relatively(tmp_path):
    html = _build(tmp_path, video_filename="my-render.mp4").read_text(encoding="utf-8")
    assert 'src="my-render.mp4"' in html
    assert 'type="video/mp4"' in html
    # Relative reference — no directory / scheme prefix injected.
    assert "/my-render.mp4" not in html
    assert "://my-render.mp4" not in html


def test_accent_color_present(tmp_path):
    html = _build(tmp_path, accent="#FF8800").read_text(encoding="utf-8")
    assert "#FF8800" in html
    assert "--accent: #FF8800" in html


def test_default_accent_used_when_not_given(tmp_path):
    html = _build(tmp_path).read_text(encoding="utf-8")
    assert ACCENT in html


def test_footer_credit_present(tmp_path):
    html = _build(tmp_path).read_text(encoding="utf-8")
    assert "demoreel" in html


def test_no_external_network_references(tmp_path):
    html = _build(tmp_path, vtt_filename="demo.vtt", poster_filename="poster.png").read_text(
        encoding="utf-8"
    )
    # Everything inlined: no CDN/script/stylesheet/font fetches over the network.
    assert "http://" not in html
    assert "https://" not in html
    assert "<link" not in html
    assert "cdn" not in html.lower()


# --------------------------------------------------------------------------- #
# chapter rail
# --------------------------------------------------------------------------- #
def test_chapter_titles_and_seconds_present(tmp_path):
    chapters = [(0.0, "Intro"), (12.0, "The Feature"), (75.0, "Wrap up")]
    html = _build(tmp_path, chapters=chapters).read_text(encoding="utf-8")
    for _, label in chapters:
        assert label in html
    # data-t carries the seek seconds; timestamps render as m:ss.
    assert 'data-t="0"' in html
    assert 'data-t="12"' in html
    assert 'data-t="75"' in html
    assert ">0:00<" in html
    assert ">0:12<" in html
    assert ">1:15<" in html


def test_chapter_rail_present_with_chapters(tmp_path):
    html = _build(tmp_path).read_text(encoding="utf-8")
    assert 'class="rail"' in html
    assert "with-rail" in html
    assert html.count('class="chapter"') == 3


def test_empty_chapters_renders_without_rail(tmp_path):
    html = _build(tmp_path, chapters=[]).read_text(encoding="utf-8")
    assert "<video" in html  # player still renders
    assert 'class="rail"' not in html
    assert "no-rail" in html
    assert 'class="chapter"' not in html


def test_fractional_seconds_data_t_preserved(tmp_path):
    html = _build(tmp_path, chapters=[(12.5, "Half")]).read_text(encoding="utf-8")
    assert 'data-t="12.5"' in html


def test_negative_seconds_clamped(tmp_path):
    html = _build(tmp_path, chapters=[(-4.0, "Before")]).read_text(encoding="utf-8")
    assert 'data-t="0"' in html
    assert ">0:00<" in html


# --------------------------------------------------------------------------- #
# captions track + poster — only when given
# --------------------------------------------------------------------------- #
def test_track_present_only_when_vtt_given(tmp_path):
    with_vtt = _build(tmp_path, vtt_filename="demo.vtt").read_text(encoding="utf-8")
    assert "<track" in with_vtt
    assert 'src="demo.vtt"' in with_vtt
    assert 'kind="captions"' in with_vtt or 'kind="captions"' in with_vtt
    assert "default" in with_vtt

    without_vtt = _build(tmp_path).read_text(encoding="utf-8")
    assert "<track" not in without_vtt


def test_poster_present_only_when_given(tmp_path):
    with_poster = _build(tmp_path, poster_filename="thumb.png").read_text(encoding="utf-8")
    assert 'poster="thumb.png"' in with_poster

    without_poster = _build(tmp_path).read_text(encoding="utf-8")
    assert "poster=" not in without_poster


# --------------------------------------------------------------------------- #
# description (optional)
# --------------------------------------------------------------------------- #
def test_description_present_when_given(tmp_path):
    html = _build(tmp_path, description="A short walkthrough.").read_text(encoding="utf-8")
    assert "A short walkthrough." in html
    assert 'class="desc"' in html


def test_description_omitted_when_none_or_blank(tmp_path):
    assert 'class="desc"' not in _build(tmp_path).read_text(encoding="utf-8")
    assert 'class="desc"' not in _build(tmp_path, description="   ").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# SECURITY: escaping (the load-bearing requirement)
# --------------------------------------------------------------------------- #
def test_script_in_title_is_escaped(tmp_path):
    html = _build(tmp_path, title="<script>alert(1)</script>").read_text(encoding="utf-8")
    # The raw, executable form must NOT survive anywhere in the document...
    assert "<script>alert(1)</script>" not in html
    # ...it must appear escaped instead.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_script_in_chapter_label_is_escaped(tmp_path):
    html = _build(tmp_path, chapters=[(0.0, "<script>alert(1)</script>")]).read_text(
        encoding="utf-8"
    )
    # The injected payload must never survive in executable form; the only legitimate
    # <script> in the document is our own inline player script (which has no alert(1)).
    assert "<script>alert(1)</script>" not in html
    assert "alert(1)" not in html.replace("&lt;script&gt;alert(1)&lt;/script&gt;", "")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_ampersand_in_text_is_escaped(tmp_path):
    html = _build(tmp_path, title="Tom & Jerry", chapters=[(0.0, "Cat & Mouse")]).read_text(
        encoding="utf-8"
    )
    assert "&amp;" in html
    assert "Tom &amp; Jerry" in html
    assert "Cat &amp; Mouse" in html
    # The raw bare ampersand from our input must not appear unescaped in those phrases.
    assert "Tom & Jerry" not in html
    assert "Cat & Mouse" not in html


def test_description_is_escaped(tmp_path):
    html = _build(tmp_path, description="<b>bold</b> & <script>x</script>").read_text(
        encoding="utf-8"
    )
    assert "<b>bold</b>" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html
    assert "&amp;" in html


def test_quote_in_attribute_context_is_escaped(tmp_path):
    # A filename containing a quote must not break out of the src="" attribute.
    html = _build(tmp_path, vtt_filename='a".vtt', poster_filename='b".png').read_text(
        encoding="utf-8"
    )
    assert 'src="a".vtt"' not in html
    assert "&quot;" in html


def test_esc_helper_directly():
    assert _esc("<script>") == "&lt;script&gt;"
    assert _esc("a & b") == "a &amp; b"
    assert _esc('"quoted"') == "&quot;quoted&quot;"
    assert _esc(None) == ""
    assert _esc(123) == "123"


# --------------------------------------------------------------------------- #
# _fmt_ts
# --------------------------------------------------------------------------- #
def test_fmt_ts_seconds():
    assert _fmt_ts(5) == "0:05"


def test_fmt_ts_minutes():
    assert _fmt_ts(75) == "1:15"


def test_fmt_ts_zero():
    assert _fmt_ts(0) == "0:00"


def test_fmt_ts_hour_form():
    out = _fmt_ts(3661)
    assert out == "1:01:01"
    assert out.count(":") == 2


def test_fmt_ts_exactly_one_hour_uses_hour_form():
    assert _fmt_ts(3600) == "1:00:00"


def test_fmt_ts_just_under_hour_stays_m_ss():
    assert _fmt_ts(3599) == "59:59"


def test_fmt_ts_negative_clamps_to_zero():
    assert _fmt_ts(-10) == "0:00"


def test_fmt_ts_truncates_fractional():
    assert _fmt_ts(5.9) == "0:05"


# --------------------------------------------------------------------------- #
# _fmt_attr
# --------------------------------------------------------------------------- #
def test_fmt_attr_whole_seconds_have_no_decimal():
    assert _fmt_attr(12.0) == "12"
    assert _fmt_attr(0.0) == "0"


def test_fmt_attr_keeps_fraction():
    assert _fmt_attr(12.5) == "12.5"


def test_fmt_attr_clamps_negative():
    assert _fmt_attr(-3.0) == "0"


# --------------------------------------------------------------------------- #
# _sanitize_color
# --------------------------------------------------------------------------- #
def test_sanitize_color_passes_clean_hex():
    assert _sanitize_color("#6C5CE7") == "#6C5CE7"


def test_sanitize_color_strips_css_breakout_chars():
    out = _sanitize_color("#fff; } body { background: url(evil)")
    assert "{" not in out
    assert "}" not in out
    assert ";" not in out
    assert "(" not in out


def test_sanitize_color_falls_back_when_empty():
    assert _sanitize_color("") == "#6C5CE7"
    assert _sanitize_color("{};") == "#6C5CE7"


def test_sanitized_accent_used_in_render(tmp_path):
    html = _build(tmp_path, accent="red; } body{display:none").read_text(encoding="utf-8")
    # The breakout attempt is neutralized inside the CSS custom property.
    assert "} body{display:none" not in html
    assert "--accent: red body" in html or "--accent: red" in html


# --------------------------------------------------------------------------- #
# render_player_html — pure core, no file
# --------------------------------------------------------------------------- #
def test_render_player_html_returns_string():
    html = render_player_html(video_filename="x.mp4", title="Pure", chapters=[(0.0, "Start")])
    assert isinstance(html, str)
    assert "<!doctype html>" in html
    assert "Pure" in html


def test_keyboard_and_seek_script_inlined(tmp_path):
    html = _build(tmp_path).read_text(encoding="utf-8")
    assert "keydown" in html
    assert "timeupdate" in html
    assert "currentTime" in html
    assert "data-t" in html


@pytest.mark.parametrize("title", ["Plain", "Tom & Jerry", "<i>x</i>", "你好"])
def test_various_titles_do_not_crash(tmp_path, title):
    out = _build(tmp_path, title=title)
    assert out.exists()
