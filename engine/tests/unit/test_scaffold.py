"""Unit tests for demoreel/scaffold.py — the pure `demoreel init` scaffolder.

Covers TEMPLATES integrity + copy isolation, template_answers errors, merge_answers
precedence/skipping, slugify cases, and that every template's build_spec output parses
AND validates through demoreel.spec.load_spec. No browser, no moviepy, no network.
"""

from __future__ import annotations

import pytest

from demoreel.scaffold import (
    QUESTIONS,
    TEMPLATES,
    Question,
    build_spec,
    merge_answers,
    slugify,
    template_answers,
)
from demoreel.spec import load_spec

TEMPLATE_NAMES = ("minimal", "tour", "social", "hero")


# --------------------------------------------------------------------------- templates


def test_templates_has_four_names():
    for name in TEMPLATE_NAMES:
        assert name in TEMPLATES


def test_social_template_is_vertical_phone():
    s = TEMPLATES["social"]
    assert s["device"] == "phone"
    assert s["resolution"] == "vertical"
    assert s["preset"] == "studio"


def test_tour_template_is_multi_scene():
    assert len(TEMPLATES["tour"]["scenes"]) >= 3


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_template_answers_returns_copy(name):
    a = template_answers(name)
    assert a == TEMPLATES[name]
    # mutating the returned copy must not touch the canonical template
    a["title"] = "MUTATED"
    a["scenes"].append({"narrate": "extra", "goto": "/"})
    a["scenes"][0]["narrate"] = "CHANGED"
    assert TEMPLATES[name]["title"] != "MUTATED"
    assert len(TEMPLATES[name]["scenes"]) < len(a["scenes"])
    assert TEMPLATES[name]["scenes"][0]["narrate"] != "CHANGED"


def test_template_answers_unknown_raises_helpful():
    with pytest.raises(ValueError) as exc:
        template_answers("nope")
    msg = str(exc.value)
    assert "nope" in msg
    for name in TEMPLATE_NAMES:
        assert name in msg


# --------------------------------------------------------------------------- questions


def test_questions_keys_subset_of_answer_keys():
    assert all(isinstance(q, Question) for q in QUESTIONS)
    known = {
        "template",
        "title",
        "url",
        "preset",
        "resolution",
        "device",
        "voice_engine",
        "transition",
    }
    for q in QUESTIONS:
        assert q.key in known


def test_question_choices_are_tuples_or_none():
    for q in QUESTIONS:
        assert q.choices is None or isinstance(q.choices, tuple)


# --------------------------------------------------------------------------- merge_answers


def test_merge_later_wins():
    out = merge_answers({"title": "A"}, {"title": "B"})
    assert out["title"] == "B"


def test_merge_skips_none_and_empty():
    out = merge_answers({"title": "A", "url": "u"}, {"title": None, "url": ""})
    assert out["title"] == "A"
    assert out["url"] == "u"


def test_merge_ignores_empty_layers():
    out = merge_answers({}, None, {"title": "A"}, {})  # type: ignore[arg-type]
    assert out == {"title": "A"}


def test_merge_accumulates_keys():
    out = merge_answers({"title": "A"}, {"url": "u"})
    assert out == {"title": "A", "url": "u"}


# --------------------------------------------------------------------------- slugify


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("My Demo", "my-demo"),
        ("My Demo!", "my-demo"),
        ("  leading trailing  ", "leading-trailing"),
        ("a/b  c", "a-b-c"),
        ("Already-slugged", "already-slugged"),
        ("UPPER_case", "upper-case"),
        ("--dashes--", "dashes"),
        ("café déjà", "caf-d-j"),
        ("multiple   spaces", "multiple-spaces"),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected


# --------------------------------------------------------------------------- build_spec


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_build_spec_nonempty_and_has_core_fields(name):
    text = build_spec(template_answers(name))
    assert text.strip()
    assert "title:" in text
    assert "url:" in text
    assert "output:" in text
    assert "scenes:" in text


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_build_spec_parses_and_validates(tmp_path, name):
    answers = template_answers(name)
    text = build_spec(answers)
    path = tmp_path / f"{name}.yaml"
    path.write_text(text)
    spec = load_spec(path)
    assert spec.title == answers["title"]
    expected_output = answers.get("output") or f"{slugify(answers['title'])}.mp4"
    assert spec.output == expected_output
    assert len(spec.scenes) >= 1


def test_build_spec_derives_output_from_title(tmp_path):
    text = build_spec({"title": "My Cool App", "url": "https://x.test"})
    assert 'output: "my-cool-app.mp4"' in text
    path = tmp_path / "d.yaml"
    path.write_text(text)
    spec = load_spec(path)
    assert spec.output == "my-cool-app.mp4"


def test_build_spec_explicit_output_wins(tmp_path):
    text = build_spec({"title": "Whatever", "output": "custom.mp4"})
    path = tmp_path / "d.yaml"
    path.write_text(text)
    assert load_spec(path).output == "custom.mp4"


def test_build_spec_empty_answers_falls_back_to_minimal(tmp_path):
    text = build_spec({})
    path = tmp_path / "d.yaml"
    path.write_text(text)
    spec = load_spec(path)
    assert spec.title
    assert spec.url
    assert len(spec.scenes) >= 1


def test_build_spec_ignores_unknown_keys(tmp_path):
    text = build_spec({"title": "T", "url": "https://x.test", "bogus_key": "ignored"})
    assert "bogus_key" not in text
    path = tmp_path / "d.yaml"
    path.write_text(text)
    load_spec(path)


def test_build_spec_render_hint_in_comment():
    text = build_spec({"title": "My App"})
    assert "demoreel render" in text
    assert "my-app.mp4" in text


def test_build_spec_social_emits_phone_and_vertical(tmp_path):
    text = build_spec(template_answers("social"))
    assert "device: phone" in text
    assert "resolution: vertical" in text
    path = tmp_path / "social.yaml"
    path.write_text(text)
    spec = load_spec(path)
    assert spec.frame.device == "phone"
    assert spec.quality.size == (1080, 1920)


def test_build_spec_merged_flags_override(tmp_path):
    answers = merge_answers(
        template_answers("minimal"),
        {"title": "Override Title", "url": "https://over.test", "preset": "dark"},
    )
    text = build_spec(answers)
    path = tmp_path / "d.yaml"
    path.write_text(text)
    spec = load_spec(path)
    assert spec.title == "Override Title"
    assert spec.url == "https://over.test"
    assert spec.output == "override-title.mp4"
