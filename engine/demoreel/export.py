"""Export an already-rendered mp4 to an animated GIF and/or animated WebP.

The small, shareable companions to the full mp4 — for READMEs, social posts, and chat where
an autoplaying loop beats a video player. The pure core (frames_to_gif / frames_to_webp)
encodes in-memory RGB frames via Pillow and is what the unit tests exercise; the mp4_*
wrappers lazy-import cv2 to read + downsample the source video, then hand off to the core.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image


def frames_to_gif(
    frames: list[np.ndarray], out_path: str | Path, *, fps: int = 15, loop: int = 0
) -> Path:
    """Encode HxWx3 uint8 RGB frames into an optimized looping GIF via Pillow."""
    out = Path(out_path)
    if not frames:
        raise ValueError("frames is empty")
    # adaptive per-frame palette: GIF is 256 colors, so quantizing each frame keeps the
    # demo's gradient backdrop from banding into a single shared palette.
    images = [Image.fromarray(f).quantize(method=Image.Quantize.MEDIANCUT) for f in frames]
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=round(1000 / fps),
        loop=loop,
        optimize=True,
        disposal=2,  # restore-to-background so frames don't ghost onto each other
    )
    return out


def frames_to_webp(
    frames: list[np.ndarray],
    out_path: str | Path,
    *,
    fps: int = 15,
    quality: int = 80,
    loop: int = 0,
) -> Path:
    """Encode HxWx3 uint8 RGB frames into an animated WebP via Pillow."""
    out = Path(out_path)
    if not frames:
        raise ValueError("frames is empty")
    # WebP keeps full color, so no palette step; method=6 is the slowest/best compression.
    images = [Image.fromarray(f) for f in frames]
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=round(1000 / fps),
        loop=loop,
        quality=quality,
        method=6,
    )
    return out


def mp4_to_gif(
    mp4_path: str | Path,
    out_path: str | Path,
    *,
    width: int = 720,
    fps: int = 15,
    max_seconds: float | None = None,
    log: Callable[[str], None] | None = None,
) -> Path:
    """Read an mp4, downsample to `fps` at `width`, and write an animated GIF."""
    frames = _read_frames(mp4_path, width=width, fps=fps, max_seconds=max_seconds, log=log)
    _log = log or (lambda *_a: None)
    _log(f"  encoding {len(frames)} frames → gif")
    return frames_to_gif(frames, out_path, fps=fps)


def mp4_to_webp(
    mp4_path: str | Path,
    out_path: str | Path,
    *,
    width: int = 720,
    fps: int = 15,
    quality: int = 80,
    max_seconds: float | None = None,
    log: Callable[[str], None] | None = None,
) -> Path:
    """Read an mp4, downsample to `fps` at `width`, and write an animated WebP."""
    frames = _read_frames(mp4_path, width=width, fps=fps, max_seconds=max_seconds, log=log)
    _log = log or (lambda *_a: None)
    _log(f"  encoding {len(frames)} frames → webp")
    return frames_to_webp(frames, out_path, fps=fps, quality=quality)


# --------------------------------------------------------------------------- helpers


def _sample_step(src_fps: float, target_fps: int) -> int:
    """How many source frames to advance per kept frame to hit ~target_fps.

    Decimation only — we never upsample, so the step floors at 1 (keep every frame) when
    the source is already at or below the target rate.
    """
    if src_fps <= 0 or target_fps <= 0:
        return 1
    return max(1, round(src_fps / target_fps))


def _target_size(src_w: int, src_h: int, width: int) -> tuple[int, int]:
    """Scale to `width` preserving aspect; height rounded to an even number.

    Even height keeps the output friendly to encoders that dislike odd dimensions, and
    matches the rest of the pipeline (the stage renders at even sizes).
    """
    width = max(2, width)
    if src_w <= 0 or src_h <= 0:
        return width, width
    h = round(width * src_h / src_w)
    h = max(2, h - (h % 2))  # force even, never below 2
    return width, h


def _read_frames(
    mp4_path: str | Path,
    *,
    width: int,
    fps: int,
    max_seconds: float | None,
    log: Callable[[str], None] | None,
) -> list[np.ndarray]:
    """Lazy-import cv2, decode the mp4, decimate to `fps`, resize, and return RGB frames."""
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - exercised only without cv2 installed
        raise RuntimeError(
            "opencv (cv2) is not installed; cannot read the mp4. `pip install opencv-python-headless`."
        ) from exc

    _log = log or (lambda *_a: None)
    path = Path(mp4_path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"could not open video: {path}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or float(fps)
    step = _sample_step(src_fps, fps)
    # cap kept frames by source-frame count, not wall time, so it lines up with `step`.
    max_kept = None if max_seconds is None else max(1, int(max_seconds * fps))

    frames: list[np.ndarray] = []
    size: tuple[int, int] | None = None
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                if size is None:
                    sh, sw = frame.shape[:2]
                    size = _target_size(sw, sh, width)
                resized = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
                frames.append(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB))
                if max_kept is not None and len(frames) >= max_kept:
                    break
            idx += 1
    finally:
        cap.release()

    if not frames:
        raise RuntimeError(f"no frames decoded from video: {path}")
    _log(f"  read {len(frames)} frames @ {fps}fps from {path.name}")
    return frames
