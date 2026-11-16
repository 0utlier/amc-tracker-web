"""Compact date display ("1-5, 7-9, 11, 12") and parsing it back."""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from itertools import groupby

_MONTH_LOOKUP = {}
for _i in range(1, 13):
    _MONTH_LOOKUP[calendar.month_abbr[_i].lower()] = _i
    _MONTH_LOOKUP[calendar.month_name[_i].lower()] = _i
_MONTH_LOOKUP["sept"] = 9


def to_date(d) -> date:
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


def _day_tokens(days: list[int]) -> list[str]:
    """Days in one month -> tokens. Runs of 3+ become ranges; others stay single."""
    tokens, run = [], [days[0]]
    for d in days[1:]:
        if d == run[-1] + 1:
            run.append(d)
            continue
        tokens.extend(_run_tokens(run))
        run = [d]
    tokens.extend(_run_tokens(run))
    return tokens


def _run_tokens(run: list[int]) -> list[str]:
    if len(run) >= 3:
        return ["{}-{}".format(run[0], run[-1])]
    return [str(d) for d in run]


def compact(dates, header: tuple[int, int] | None = None) -> str:
    """
    Format show dates compactly.

    header = (year, month) of the month section the row sits under; dates in
    that month show as bare day numbers, other months get a prefix ("Jan 1-3").
    Defaults to the month of the earliest date.
    """
    ds = sorted({to_date(d) for d in dates})
    if not ds:
        return ""
    if header is None:
        header = (ds[0].year, ds[0].month)

    tokens = []
    for (y, m), grp in groupby(ds, key=lambda d: (d.year, d.month)):
        toks = _day_tokens([d.day for d in grp])
        if (y, m) != header:
            toks[0] = "{} {}".format(calendar.month_abbr[m], toks[0])
        tokens.extend(toks)

    if len(ds) == 2:
        return " & ".join(tokens)
    return ", ".join(tokens)


def _resolve_month(name: str, header_year: int, header_month: int) -> tuple[int, int]:
    m = _MONTH_LOOKUP.get(name.lower().rstrip("."))
    if not m:
        raise ValueError("Unknown month '{}'".format(name))
    year = header_year if m >= header_month else header_year + 1
    return year, m


_TOKEN = re.compile(
    r"(?:(?P<m1>[A-Za-z]+)\.?\s*)?(?P<d1>\d{1,2})"
    r"(?:\s*-\s*(?:(?P<m2>[A-Za-z]+)\.?\s*)?(?P<d2>\d{1,2}))?"
)


def parse(text: str, header: tuple[int, int]) -> list[date]:
    """
    Parse what a person typed in the DATE cell back into dates.
    Accepts things like "1-5, 7 & 9", "28-31, Jan 1-3", "Dec 30 & Jan 2".
    """
    hy, hm = header
    y, m = hy, hm
    out: set[date] = set()
    for raw in re.split(r"\s*(?:,|&|\band\b)\s*", (text or "").strip()):
        tok = raw.strip()
        if not tok:
            continue
        mt = _TOKEN.fullmatch(tok)
        if not mt:
            raise ValueError("Couldn't read '{}'. Use days like 1-5, 7 & 9".format(tok))
        if mt["m1"]:
            y, m = _resolve_month(mt["m1"], hy, hm)
        start = date(y, m, int(mt["d1"]))
        if mt["d2"]:
            if mt["m2"]:
                y, m = _resolve_month(mt["m2"], hy, hm)
            end = date(y, m, int(mt["d2"]))
            if end < start:
                raise ValueError("Range '{}' goes backwards".format(tok))
            d = start
            while d <= end:
                out.add(d)
                d += timedelta(days=1)
        else:
            out.add(start)
    if not out:
        raise ValueError("Enter at least one date")
    return sorted(out)


def month_label(y: int, m: int) -> str:
    return "{} {}".format(calendar.month_name[m], y)
