"""Draws a run's results into a PNG — the saved 'screenshot' for search history."""
from __future__ import annotations

import io
from datetime import datetime
from itertools import groupby

from PIL import Image, ImageDraw, ImageFont

from .datefmt import compact, month_label, to_date

BG, SURFACE, TEXT, MUTED, ACCENT, NEW = "#0d0d12", "#1e1e32", "#e8e8f0", "#c5c5d4", "#e94560", "#00d4a8"
W, PAD, ROW = 1000, 36, 58


def _font(size, bold=False):
    names = (["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"] if bold
             else ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _fit(draw, text, font, max_w):
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def render(user_name: str, meta: dict, movies: list[dict], tz: str | None = None) -> bytes:
    f_h1, f_sub, f_month = _font(30, True), _font(17), _font(16, True)
    f_title, f_line, f_badge = _font(19, True), _font(15), _font(12, True)

    theatres = meta.get("theatres") or []
    groups = [(k, list(g)) for k, g in groupby(
        movies, key=lambda m: (to_date(m["dates"][0]).year, to_date(m["dates"][0]).month))]
    height = PAD * 2 + 110 + 26 * len(theatres) + 30 + sum(44 + ROW * len(g) for _, g in groups)
    if not movies:
        height += 60

    img = Image.new("RGB", (W, height), BG)
    d = ImageDraw.Draw(img)
    y = PAD

    d.text((PAD, y), "AMC Movie Tracker — {}".format(user_name), font=f_h1, fill=ACCENT)
    y += 44
    try:
        dt = datetime.fromisoformat(meta["run_at"])
        if tz:
            from zoneinfo import ZoneInfo
            dt = dt.astimezone(ZoneInfo(tz))
        when = dt.strftime("%b %-d, %Y %-I:%M %p")
    except Exception:
        when = str(meta.get("run_at", ""))[:16]
    where = "ZIP {}".format(meta["zip"]) if meta.get("zip") else "Default theaters"
    sub = "{} · {} theaters · {} days · {} movies · {}".format(
        where, len(theatres) or meta.get("theatre_count"), meta.get("days"), len(movies), when)
    d.text((PAD, y), sub, font=f_sub, fill=MUTED)
    y += 40

    for t in theatres:
        d.ellipse((PAD, y + 5, PAD + 11, y + 16), fill=t.get("color", "#8a8aa8"))
        miles = " · {:.1f} mi".format(t["miles"]) if t.get("miles") is not None else ""
        d.text((PAD + 20, y), "{}{}".format(t["name"], miles), font=f_line, fill=TEXT)
        y += 26
    y += 30

    if not movies:
        d.text((PAD, y), "No movies found for this search.", font=f_sub, fill=MUTED)

    for (yy, mm), group in groups:
        d.text((PAD, y), month_label(yy, mm).upper(), font=f_month, fill=NEW)
        y += 34
        for m in group:
            d.rounded_rectangle((PAD, y, W - PAD, y + ROW - 8), radius=10, fill=SURFACE)
            badge_w = 0
            if m.get("is_imax"):
                badge_w = 64
                d.rounded_rectangle((W - PAD - 76, y + 10, W - PAD - 12, y + 30), radius=4, fill="#000")
                d.text((W - PAD - 66, y + 13), "IMAX", font=f_badge, fill="#fff")
            d.text((PAD + 14, y + 7), _fit(d, m["title"], f_title, W - 2 * PAD - 40 - badge_w),
                   font=f_title, fill=TEXT)
            tc = m.get("theatre_count", 0)
            line = "{} · {} theater{}".format(compact(m["dates"], (yy, mm)), tc, "" if tc == 1 else "s")
            d.text((PAD + 14, y + 30), _fit(d, line, f_line, W - 2 * PAD - 30), font=f_line, fill=MUTED)
            y += ROW
        y += 10

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
