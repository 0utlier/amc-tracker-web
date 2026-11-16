"""Excel and CSV exports for the shared tracker and for saved runs."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from itertools import groupby

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill

from .datefmt import compact, month_label, to_date

TRACKER_HEADERS = ["DATE", "MOVIE", "USER", "A-List Available", "Jonathan Purchased",
                   "NEEDS REFUND", "NEEDS ALTERNATIVE", "NOTES"]
_HDR_FILL = PatternFill("solid", fgColor="1E1E32")
_MONTH_FILL = PatternFill("solid", fgColor="DDF7F1")


def _yn(v):
    return "Yes" if v else ""


def month_key(m):
    d = m["dates"][0] if m["dates"] else None
    return (d.year, d.month) if d else (9999, 12)


def sort_tracker(movies):
    return sorted(movies, key=lambda m: (m["dates"][0] if m["dates"] else to_date("9999-12-31"),
                                         m["title"].lower()))


def _tracker_row(m, header):
    return [compact(m["dates"], header) if m["dates"] else "", m["title"], ", ".join(m["users"]),
            _yn(m["alist_available"]), _yn(m["jonathan_purchased"]), _yn(m["needs_refund"]),
            _yn(m["needs_alternative"]), m.get("notes") or ""]


def _style_header(ws, row=1):
    for c in ws[row]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = _HDR_FILL
        c.alignment = Alignment(vertical="center")


def tracker_xlsx(movies) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Tracker"
    ws.append(TRACKER_HEADERS)
    _style_header(ws)
    for key, group in groupby(sort_tracker(movies), key=month_key):
        label = month_label(*key) if key[0] != 9999 else "No dates"
        ws.append([label])
        r = ws.max_row
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(TRACKER_HEADERS))
        ws.cell(r, 1).font = Font(bold=True, size=12)
        ws.cell(r, 1).fill = _MONTH_FILL
        for m in group:
            ws.append(_tracker_row(m, key))
        ws.append([])  # spacer between months
    for col, w in zip("ABCDEFGH", (18, 38, 22, 16, 18, 15, 19, 40)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    # Full-detail sheet: every individual date, nothing compressed
    ws2 = wb.create_sheet("All dates")
    ws2.append(["MOVIE", "DATE", "USER", "AMC link"])
    _style_header(ws2)
    for m in sort_tracker(movies):
        for d in m["dates"]:
            ws2.append([m["title"], d, ", ".join(m["users"]), m.get("movie_url") or ""])
    for col, w in zip("ABCD", (38, 14, 22, 50)):
        ws2.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def tracker_csv(movies) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["MONTH", *TRACKER_HEADERS, "ALL DATES", "AMC LINK"])
    for m in sort_tracker(movies):
        key = month_key(m)
        label = month_label(*key) if key[0] != 9999 else ""
        w.writerow([label, *_tracker_row(m, key),
                    " ".join(str(d) for d in m["dates"]), m.get("movie_url") or ""])
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens it cleanly


# ── Saved runs ────────────────────────────────────────────────────────────────
def _fmt_run_time(iso):
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %I:%M %p")
    except Exception:
        return str(iso)


def _showtime_rows(movies):
    for m in movies:
        for th in (m.get("theatres") or {}).values():
            for d, shows in sorted(th["dates"].items()):
                for s in shows:
                    yield [m["title"], th["name"], d, s["time"], ", ".join(s.get("formats") or []),
                           "Sold out" if s.get("sold_out") else "", s.get("url") or ""]


def run_xlsx(user_name, meta, movies, png: bytes | None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Search settings"
    for row in (["User", user_name], ["Run date & time", _fmt_run_time(meta["run_at"])],
                ["ZIP code", meta.get("zip") or "(none: default theaters)"], ["Theaters searched", meta.get("theatre_count")],
                ["Days searched", meta.get("days")], ["Movies found", len(movies)],
                ["Days with no showtimes yet", meta.get("empty_days", 0)], [], ["Theater", "Miles"]):
        ws.append(row)
    for t in meta.get("theatres") or []:
        ws.append([t["name"], t.get("miles")])
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 30
    for r in range(1, 8):
        ws.cell(r, 1).font = Font(bold=True)

    ws2 = wb.create_sheet("Movies")
    ws2.append(["MOVIE", "DATES", "THEATERS", "IMAX", "FORMATS", "ALL DATES", "AMC LINK"])
    _style_header(ws2)
    for m in movies:
        ws2.append([m["title"], compact(m["dates"]), m.get("theatre_count"), _yn(m.get("is_imax")),
                    ", ".join(m.get("formats") or []), " ".join(map(str, m["dates"])),
                    m.get("movie_url") or ""])
    for col, w in zip("ABCDEFG", (38, 26, 10, 7, 20, 40, 50)):
        ws2.column_dimensions[col].width = w

    ws3 = wb.create_sheet("Showtimes")
    ws3.append(["MOVIE", "THEATER", "DATE", "TIME", "FORMAT", "STATUS", "TICKET LINK"])
    _style_header(ws3)
    for row in _showtime_rows(movies):
        ws3.append(row)
    for col, w in zip("ABCDEFG", (38, 30, 12, 10, 14, 10, 50)):
        ws3.column_dimensions[col].width = w

    if png:
        ws4 = wb.create_sheet("Screenshot")
        img = XLImage(io.BytesIO(png))
        img.anchor = "A1"
        ws4.add_image(img)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def run_csv(meta, movies) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["# Run", _fmt_run_time(meta["run_at"]), "ZIP", meta.get("zip") or "",
                "Theaters", meta.get("theatre_count"), "Days", meta.get("days")])
    w.writerow(["MOVIE", "THEATER", "DATE", "TIME", "FORMAT", "STATUS", "TICKET LINK"])
    for row in _showtime_rows(movies):
        w.writerow(row)
    return buf.getvalue().encode("utf-8-sig")
