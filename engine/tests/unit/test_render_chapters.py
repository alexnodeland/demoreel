"""Unit tests for demoreel.render._chapter_markers.

`_chapter_markers(spec, cap, intro_wav)` projects the player's chapter seek points onto the
FINAL composed timeline: an optional intro-card marker at 0.0, then one marker per captured
scene that names a chapter (Chapter object, raw string, or — failing that — the scene name).
Scene start times come from the capture timeline (`cap.scenes[*].t_start`, indexed by
`SceneTiming.index`), shifted by the content offset (intro card duration, minus the crossfade
overlap when the transition crossfades).

These tests build a synthetic `CaptureResult` + `DemoSpec` (no browser, no ffmpeg, no TTS) and
pass `intro_wav=None`, so the intro duration is exactly `spec.intro.seconds`.
"""

from __future__ import annotations

from demoreel.capture import CaptureResult, SceneTiming
from demoreel.keyframes import CameraTrack
from demoreel.render import _chapter_markers


def _timing(index: int, t_start: float, name: str | None = None) -> SceneTiming:
    """A SceneTiming whose only load-bearing fields here are `index` and `t_start`."""
    return SceneTiming(
        index=index,
        name=name,
        t_start=t_start,
        t_end=t_start + 1.0,
        audio_start=t_start,
        narration_wav=None,
        narration_duration=0.0,
    )


def _cap(scenes: list[SceneTiming]) -> CaptureResult:
    return CaptureResult(
        video_path="x",
        page_w=1,
        page_h=1,
        video_w=1,
        video_h=1,
        duration=10.0,
        scenes=scenes,
        camera=CameraTrack(1, 1),
    )


# --------------------------------------------------------------------------- #
# intro card marker
# --------------------------------------------------------------------------- #
def test_intro_produces_zero_marker_with_its_title(make_spec):
    spec = make_spec(
        intro={"title": "Welcome", "seconds": 3.0},
        scenes=[{"goto": "/", "name": "first"}],
    )
    cap = _cap([_timing(0, 0.0)])
    marks = _chapter_markers(spec, cap, None)
    assert marks[0] == (0.0, "Welcome")


def test_no_intro_has_no_zero_intro_marker(make_spec):
    # Without an intro card, content starts at 0 and the first marker is a scene marker.
    spec = make_spec(scenes=[{"goto": "/", "name": "first"}])
    cap = _cap([_timing(0, 0.0)])
    marks = _chapter_markers(spec, cap, None)
    assert marks == [(0.0, "first")]


def test_no_intro_scene_markers_start_at_content_start_zero(make_spec):
    # content_start == 0 with no intro: each scene marker is exactly its t_start.
    spec = make_spec(
        scenes=[
            {"goto": "/", "name": "a"},
            {"click": "#x", "name": "b"},
        ],
    )
    cap = _cap([_timing(0, 0.0), _timing(1, 4.25)])
    marks = _chapter_markers(spec, cap, None)
    assert marks == [(0.0, "a"), (4.25, "b")]


# --------------------------------------------------------------------------- #
# content offset (intro duration ± crossfade overlap)
# --------------------------------------------------------------------------- #
def test_crossfade_subtracts_overlap_from_content_start(make_spec):
    # intro.seconds (S) = 3.0, crossfade duration (d) = 0.5 -> content_start = S - d = 2.5.
    # A scene at t_start T appears at round(S - d + T, 2) = round(2.5 + 1.0) = 3.5.
    spec = make_spec(
        intro={"title": "Intro", "seconds": 3.0},
        transition={"type": "crossfade", "duration": 0.5},
        scenes=[{"goto": "/", "name": "scene"}],
    )
    cap = _cap([_timing(0, 1.0)])
    marks = _chapter_markers(spec, cap, None)
    assert marks == [(0.0, "Intro"), (3.5, "scene")]


def test_cut_transition_uses_full_intro_offset(make_spec):
    # transition 'cut' -> no overlap subtraction; scene at round(S + T, 2).
    spec = make_spec(
        intro={"title": "Intro", "seconds": 3.0},
        transition={"type": "cut", "duration": 0.5},
        scenes=[{"goto": "/", "name": "scene"}],
    )
    cap = _cap([_timing(0, 1.0)])
    marks = _chapter_markers(spec, cap, None)
    # 3.0 + 1.0 == 4.0, NOT 3.5 — the cut path never subtracts the transition duration.
    assert marks == [(0.0, "Intro"), (4.0, "scene")]


def test_dip_transition_also_uses_full_intro_offset(make_spec):
    # Only 'crossfade' subtracts the overlap; 'dip' behaves like 'cut' for the offset.
    spec = make_spec(
        intro={"title": "Intro", "seconds": 2.0},
        transition={"type": "dip", "duration": 0.5},
        scenes=[{"goto": "/", "name": "scene"}],
    )
    cap = _cap([_timing(0, 1.0)])
    marks = _chapter_markers(spec, cap, None)
    assert marks == [(0.0, "Intro"), (3.0, "scene")]


def test_crossfade_offset_clamped_to_zero_when_intro_shorter_than_overlap(make_spec):
    # intro.seconds (0.3) < crossfade duration (0.5): max(0.0, 0.3 - 0.5) == 0.0.
    spec = make_spec(
        intro={"title": "Intro", "seconds": 0.3},
        transition={"type": "crossfade", "duration": 0.5},
        scenes=[{"goto": "/", "name": "scene"}],
    )
    cap = _cap([_timing(0, 1.5)])
    marks = _chapter_markers(spec, cap, None)
    # content_start clamps to 0, so the scene marker is just its t_start.
    assert marks == [(0.0, "Intro"), (1.5, "scene")]


# --------------------------------------------------------------------------- #
# label resolution: Chapter / str / name / none
# --------------------------------------------------------------------------- #
def test_chapter_string_used_verbatim_as_label(make_spec):
    spec = make_spec(scenes=[{"goto": "/", "name": "the-name", "chapter": "Chapter Text"}])
    cap = _cap([_timing(0, 0.0)])
    marks = _chapter_markers(spec, cap, None)
    # The chapter string wins over the scene name.
    assert marks == [(0.0, "Chapter Text")]


def test_chapter_object_uses_its_title(make_spec):
    spec = make_spec(
        scenes=[
            {
                "goto": "/",
                "name": "the-name",
                "chapter": {"title": "Object Title", "subtitle": "ignored here"},
            }
        ],
    )
    cap = _cap([_timing(0, 0.0)])
    marks = _chapter_markers(spec, cap, None)
    assert marks == [(0.0, "Object Title")]


def test_chapter_object_subtitle_is_not_the_label(make_spec):
    spec = make_spec(
        scenes=[{"goto": "/", "chapter": {"title": "T", "subtitle": "Subtitle"}}],
    )
    cap = _cap([_timing(0, 0.0)])
    marks = _chapter_markers(spec, cap, None)
    assert marks == [(0.0, "T")]
    assert "Subtitle" not in [label for _, label in marks]


def test_name_used_when_no_chapter(make_spec):
    spec = make_spec(scenes=[{"goto": "/", "name": "just-a-name"}])
    cap = _cap([_timing(0, 0.0)])
    marks = _chapter_markers(spec, cap, None)
    assert marks == [(0.0, "just-a-name")]


def test_scene_with_neither_chapter_nor_name_is_excluded(make_spec):
    # A bare scene (no chapter, no name) produces no marker at all.
    spec = make_spec(scenes=[{"goto": "/"}])
    cap = _cap([_timing(0, 0.0)])
    marks = _chapter_markers(spec, cap, None)
    assert marks == []


def test_excluded_scene_does_not_shift_following_markers(make_spec):
    # The unnamed middle scene is dropped, but the named scenes keep their own t_starts.
    spec = make_spec(
        scenes=[
            {"goto": "/", "name": "a"},
            {"click": "#x"},  # no name/chapter -> excluded
            {"click": "#y", "name": "c"},
        ],
    )
    cap = _cap([_timing(0, 0.0), _timing(1, 2.0), _timing(2, 4.0)])
    marks = _chapter_markers(spec, cap, None)
    assert marks == [(0.0, "a"), (4.0, "c")]


# --------------------------------------------------------------------------- #
# ordering, indexing, rounding invariants
# --------------------------------------------------------------------------- #
def test_marker_order_follows_cap_scene_order(make_spec):
    spec = make_spec(
        scenes=[
            {"goto": "/", "name": "one"},
            {"click": "#x", "name": "two"},
            {"click": "#y", "name": "three"},
        ],
    )
    cap = _cap([_timing(0, 0.0), _timing(1, 1.0), _timing(2, 2.0)])
    labels = [label for _, label in _chapter_markers(spec, cap, None)]
    assert labels == ["one", "two", "three"]


def test_markers_indexed_by_scene_timing_index_not_position(make_spec):
    # cap.scenes is intentionally out of order; each timing's `index` selects its spec scene,
    # and marker order follows cap.scenes order (not spec.scenes order).
    spec = make_spec(
        scenes=[
            {"goto": "/", "name": "scene0"},
            {"click": "#x", "name": "scene1"},
        ],
    )
    cap = _cap([_timing(1, 5.0), _timing(0, 1.0)])
    marks = _chapter_markers(spec, cap, None)
    assert marks == [(5.0, "scene1"), (1.0, "scene0")]


def test_times_are_floats_rounded_to_two_dp(make_spec):
    spec = make_spec(
        intro={"title": "Intro", "seconds": 1.111},
        transition={"type": "crossfade", "duration": 0.5},
        scenes=[{"goto": "/", "name": "scene"}],
    )
    # content_start = 1.111 - 0.5 = 0.611; + t_start 0.124 = 0.735, which round(_, 2)
    # resolves to 0.73 (the binary float for 0.735 sits just under, so it rounds down).
    cap = _cap([_timing(0, 0.124)])
    marks = _chapter_markers(spec, cap, None)
    t, label = marks[1]
    assert label == "scene"
    assert isinstance(t, float)
    assert t == round(0.611 + 0.124, 2)
    assert t == 0.73


def test_empty_capture_scenes_with_intro_yields_only_intro_marker(make_spec):
    spec = make_spec(
        intro={"title": "Solo", "seconds": 2.0},
        scenes=[{"goto": "/", "name": "unused"}],
    )
    cap = _cap([])  # nothing was captured
    marks = _chapter_markers(spec, cap, None)
    assert marks == [(0.0, "Solo")]


def test_empty_capture_scenes_without_intro_yields_no_markers(make_spec):
    spec = make_spec(scenes=[{"goto": "/", "name": "unused"}])
    cap = _cap([])
    marks = _chapter_markers(spec, cap, None)
    assert marks == []
