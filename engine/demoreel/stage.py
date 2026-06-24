"""Studio framing — float the recording on a backdrop inside a browser window, then
run the camera over the whole composition.

The recording is the page content. We lay it out as an inset window (gradient backdrop +
drop shadow + macOS browser chrome + rounded corners), then the camera (zoom/pan) operates
on the *framed* result, so zooming pushes past the window edge into the content — the
Screen-Studio feel.

Click/zoom focus points were captured in page/CSS pixels; ``page_to_stage`` maps them into
output pixels so the camera frames the right spot through all the framing math.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .capture import CaptureResult
from .keyframes import CameraTrack, remap
from .spec import DemoSpec, GradientBg
from .subtitles import resolve_font


class StageCompositor:
    def __init__(self, spec: DemoSpec, cap: CaptureResult) -> None:
        self.spec = spec
        self.cap = cap
        self.OW, self.OH = spec.output_size()
        fc = spec.frame
        studio = fc.style == "studio"
        # device shells (phone/tablet) replace the browser chrome with a bezel + notch/home.
        self.device = fc.device if studio else "none"
        is_device = self.device != "none"

        pad = int(fc.padding * min(self.OW, self.OH)) if studio else 0
        self.bezel = int(0.015 * min(self.OW, self.OH)) if is_device else 0
        # browser chrome bar only in browser mode; a device draws its own status furniture
        self.chrome_h = (
            int(0.045 * self.OH) if (studio and fc.chrome == "browser" and not is_device) else 0
        )

        avail_w = self.OW - 2 * pad - 2 * self.bezel
        avail_h = self.OH - 2 * pad - 2 * self.bezel - self.chrome_h
        page_aspect = cap.page_w / cap.page_h
        if avail_w / avail_h > page_aspect:
            ch = avail_h
            cw = ch * page_aspect
        else:
            cw = avail_w
            ch = cw / page_aspect
        self.cw, self.ch = round(cw), round(ch)
        # win_* is the OUTER box (browser window, or device body incl. bezel); content_* is the
        # page area inside it. With bezel=0 (browser) win == content origin, as before.
        self.win_w = self.cw + 2 * self.bezel
        self.win_h = self.ch + self.chrome_h + 2 * self.bezel
        self.win_x = (self.OW - self.win_w) // 2
        self.win_y = (self.OH - self.win_h) // 2
        self.content_x = self.win_x + self.bezel
        self.content_y = self.win_y + self.bezel + self.chrome_h
        self.sx = self.cw / cap.page_w
        self.sy = self.ch / cap.page_h
        self.body_radius, self.screen_radius = self._radii(fc)

        self._build_static_layers(studio)

        cam = spec.camera
        self.camera: CameraTrack = remap(
            cap.camera,
            self.page_to_stage,
            self.OW,
            self.OH,
            easing=cam.easing,
            overshoot=cam.overshoot,
            idle_drift=cam.idle_drift,
            drift_amount=cam.drift_amount,
        )

    # ------------------------------------------------------------------ coordinate map

    def page_to_stage(self, px: float, py: float) -> tuple[float, float]:
        return (self.content_x + px * self.sx, self.content_y + py * self.sy)

    # ------------------------------------------------------------------ static layers

    def _radii(self, fc) -> tuple[int, int]:
        """(body_radius, screen_radius) for the outer shell and the page corners."""
        if self.device == "phone":
            body = int(min(self.win_w, self.win_h) * 0.085)
            return body, max(0, body - self.bezel)
        if self.device == "tablet":
            body = int(min(self.win_w, self.win_h) * 0.045)
            return body, max(0, body - self.bezel)
        return fc.radius, fc.radius

    def _build_static_layers(self, studio: bool) -> None:
        fc = self.spec.frame
        backdrop = _build_background(fc.background, self.OW, self.OH)  # RGB uint8
        base = Image.fromarray(backdrop).convert("RGBA")  # mode inferred from (H,W,3)

        if studio:
            if fc.shadow:
                base.alpha_composite(self._shadow_layer())
            if self.device != "none":
                base.alpha_composite(self._device_body_layer())
            else:
                base.alpha_composite(self._window_layer())

        self.stage_base = np.array(base.convert("RGB"))

        # rounded-corner alpha mask for the page content
        if self.device != "none":
            corners = (True, True, True, True)
            radius = self.screen_radius
        else:
            corners = (False, False, True, True) if self.chrome_h else (True, True, True, True)
            radius = fc.radius if studio else 0
        mask_img = Image.new("L", (self.cw, self.ch), 0)
        d = ImageDraw.Draw(mask_img)
        d.rounded_rectangle(
            [0, 0, self.cw - 1, self.ch - 1], radius=radius, fill=255, corners=corners
        )
        self.mask = (np.asarray(mask_img, dtype=np.float32) / 255.0)[:, :, None]

        # device notch/home indicator float OVER the page, so they're composited per-frame;
        # precompute the float alpha/rgb split once (the layer is static).
        self._fg_a: np.ndarray | None = None
        self._fg_rgb: np.ndarray | None = None
        if self.device != "none":
            arr = np.asarray(self._device_fg_layer()).astype(np.float32)
            self._fg_a = arr[:, :, 3:4] / 255.0
            self._fg_rgb = arr[:, :, :3]

    def _shadow_layer(self) -> Image.Image:
        fc = self.spec.frame
        layer = Image.new("RGBA", (self.OW, self.OH), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        dy = int(self.OH * 0.012)
        a = int(255 * fc.shadow_opacity)
        d.rounded_rectangle(
            [self.win_x, self.win_y + dy, self.win_x + self.win_w, self.win_y + self.win_h + dy],
            radius=self.body_radius + 4,
            fill=(0, 0, 0, a),
        )
        return layer.filter(ImageFilter.GaussianBlur(fc.shadow_blur))

    def _window_layer(self) -> Image.Image:
        fc = self.spec.frame
        layer = Image.new("RGBA", (self.OW, self.OH), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        light = _is_light(fc.background)
        chrome_col = (238, 240, 245, 255) if light else (32, 33, 44, 255)
        # Opaque "paper" behind the page. Without it, an app with a transparent or glassy
        # background lets the dark backdrop bleed through and the whole window reads as a
        # washed-out ghost. A solid panel guarantees crisp contrast and gives the window body.
        panel_col = (252, 252, 254, 255) if light else (16, 16, 22, 255)
        win_bottom = self.win_y + self.chrome_h + self.ch

        d.rounded_rectangle(
            [self.win_x, self.win_y, self.win_x + self.cw, win_bottom],
            radius=fc.radius,
            fill=panel_col,
        )
        # window border — a touch brighter than the panel so the edge always catches light
        d.rounded_rectangle(
            [self.win_x - 1, self.win_y - 1, self.win_x + self.cw, win_bottom],
            radius=fc.radius,
            outline=(0, 0, 0, 60) if light else (255, 255, 255, 60),
            width=1,
        )
        if not self.chrome_h:
            return layer

        # chrome bar (rounded only on top corners)
        d.rounded_rectangle(
            [self.win_x, self.win_y, self.win_x + self.cw, self.win_y + self.chrome_h],
            radius=fc.radius,
            fill=chrome_col,
            corners=(True, True, False, False),
        )
        # traffic lights
        r = max(5, int(self.chrome_h * 0.16))
        cy = self.win_y + self.chrome_h // 2
        for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            cx = self.win_x + int(self.chrome_h * 0.55) + i * int(r * 3.4)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        # url pill
        pill_w = int(self.cw * 0.46)
        pill_h = int(self.chrome_h * 0.56)
        px0 = self.win_x + (self.cw - pill_w) // 2
        py0 = cy - pill_h // 2
        pill_col = (255, 255, 255, 235) if light else (18, 18, 26, 235)
        d.rounded_rectangle(
            [px0, py0, px0 + pill_w, py0 + pill_h], radius=pill_h // 2, fill=pill_col
        )
        url = fc.chrome_url or self.cap.page_url or self.spec.url or ""
        url = _clean_url(url)
        if url:
            font = resolve_font(self.spec.captions.font, max(12, int(pill_h * 0.5)))
            tcol = (70, 70, 80) if light else (200, 200, 210)
            tw = int(font.getbbox(url)[2])
            d.text((px0 + (pill_w - tw) // 2, cy - int(pill_h * 0.32)), url, font=font, fill=tcol)
        return layer

    # ------------------------------------------------------------------ device shell

    def _device_body_layer(self) -> Image.Image:
        """The phone/tablet body: a dark rounded shell with a faint light edge, drawn behind
        the page so the screen's rounded corners reveal the bezel rather than the backdrop."""
        layer = Image.new("RGBA", (self.OW, self.OH), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        box = [self.win_x, self.win_y, self.win_x + self.win_w, self.win_y + self.win_h]
        d.rounded_rectangle(box, radius=self.body_radius, fill=(20, 21, 26, 255))
        d.rounded_rectangle(box, radius=self.body_radius, outline=(255, 255, 255, 40), width=2)
        d.rounded_rectangle(
            [
                self.content_x - 1,
                self.content_y - 1,
                self.content_x + self.cw,
                self.content_y + self.ch,
            ],
            radius=self.screen_radius,
            outline=(0, 0, 0, 180),
            width=1,
        )
        return layer

    def _device_fg_layer(self) -> Image.Image:
        """Notch / dynamic-island + home indicator (phone) or a camera dot (tablet). These ride
        ON TOP of the page, like the real hardware cutouts do."""
        layer = Image.new("RGBA", (self.OW, self.OH), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        cx = self.content_x + self.cw // 2
        if self.device == "phone":
            iw = max(60, int(self.cw * 0.34))
            ih = max(16, int(self.bezel * 1.5))
            iy = self.content_y + int(self.ch * 0.018)
            d.rounded_rectangle(
                [cx - iw // 2, iy, cx + iw // 2, iy + ih], radius=ih // 2, fill=(0, 0, 0, 255)
            )
            hw = int(self.cw * 0.32)
            hh = max(4, int(self.bezel * 0.34))
            hy = self.content_y + self.ch - int(self.ch * 0.018) - hh
            d.rounded_rectangle(
                [cx - hw // 2, hy, cx + hw // 2, hy + hh], radius=hh // 2, fill=(255, 255, 255, 210)
            )
        else:  # tablet — a small front camera dot in the top bezel
            r = max(3, self.bezel // 4)
            ccy = self.win_y + self.bezel // 2
            d.ellipse([cx - r, ccy - r, cx + r, ccy + r], fill=(40, 42, 50, 255))
        return layer

    # ------------------------------------------------------------------ per-frame

    def frame(self, get_frame, t):
        import cv2

        src = get_frame(t)
        interp = cv2.INTER_AREA if self.cw < self.cap.video_w else cv2.INTER_LINEAR
        page = cv2.resize(src, (self.cw, self.ch), interpolation=interp)

        out = self.stage_base.copy()
        y0, x0 = self.content_y, self.content_x
        region = out[y0 : y0 + self.ch, x0 : x0 + self.cw].astype(np.float32)
        blended = region * (1.0 - self.mask) + page.astype(np.float32) * self.mask
        out[y0 : y0 + self.ch, x0 : x0 + self.cw] = blended.astype(np.uint8)

        # device notch / home indicator ride on top of the page (like a real phone)
        if self._fg_a is not None:
            out = (out.astype(np.float32) * (1.0 - self._fg_a) + self._fg_rgb * self._fg_a).astype(
                np.uint8
            )

        z, cx, cy = self.camera.sample(t)
        if z > 1.001:
            cwn = max(2, min(round(self.OW / z), self.OW))
            chn = max(2, min(round(self.OH / z), self.OH))
            cx0 = round(cx - cwn / 2)
            cy0 = round(cy - chn / 2)
            cx0 = max(0, min(cx0, self.OW - cwn))
            cy0 = max(0, min(cy0, self.OH - chn))
            crop = out[cy0 : cy0 + chn, cx0 : cx0 + cwn]
            out = cv2.resize(crop, (self.OW, self.OH), interpolation=cv2.INTER_LINEAR)
        return out


# --------------------------------------------------------------------------- backgrounds


def _build_background(bg: GradientBg | str | None, w: int, h: int) -> np.ndarray:
    if isinstance(bg, GradientBg):
        return _gradient(bg.colors, bg.angle, w, h)
    if isinstance(bg, str):
        from pathlib import Path

        if not bg.startswith("#") and Path(bg).exists():
            return _image_cover(bg, w, h)
        return np.tile(np.array(_hex(bg), dtype=np.uint8), (h, w, 1))
    return np.tile(np.array((11, 11, 18), dtype=np.uint8), (h, w, 1))


def _gradient(colors: list[str], angle: float, w: int, h: int) -> np.ndarray:
    c0 = np.array(_hex(colors[0]), dtype=np.float32)
    c1 = np.array(_hex(colors[1]), dtype=np.float32)
    rad = math.radians(angle)
    dx, dy = math.cos(rad), math.sin(rad)
    xs = np.linspace(0.0, 1.0, w, dtype=np.float32)
    ys = np.linspace(0.0, 1.0, h, dtype=np.float32)
    gx, gy = np.meshgrid(xs, ys)
    proj = gx * dx + gy * dy
    proj = (proj - proj.min()) / (np.ptp(proj) + 1e-6)
    t = proj[:, :, None]
    return (c0 * (1 - t) + c1 * t).astype(np.uint8)


def _image_cover(path: str, w: int, h: int) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1))
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    return np.asarray(img.crop((left, top, left + w, top + h)))


def _hex(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _is_light(bg) -> bool:
    if isinstance(bg, GradientBg):
        cols = bg.colors
    elif isinstance(bg, str) and bg.startswith("#"):
        cols = [bg]
    else:
        return False  # image backdrops default to dark chrome
    # Average all gradient stops, not just the first — a light→dark gradient should pick
    # chrome that suits the whole frame, since the window sits centered over the blend.
    lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in (_hex(c) for c in cols)]
    return (sum(lum) / len(lum)) > 140


def _clean_url(url: str) -> str:
    url = url.split("?")[0]
    for pre in ("https://", "http://", "file://"):
        if url.startswith(pre):
            url = url[len(pre) :]
    if url.startswith("/private/") or url.startswith("/Users/") or url.count("/") > 4:
        # local file path — show something tidy instead of a long path
        return "localhost"
    return url.rstrip("/") or "localhost"
