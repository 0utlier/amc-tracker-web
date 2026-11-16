"""AMC search — ported from the Mac amc_tracker.py, plus real showtimes and parallel fetching."""
from __future__ import annotations

import math
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import requests

BASE = "https://api.amctheatres.com"

THEATRE_COLORS = [
    "#4f8ef7", "#a855f7", "#f97316", "#22c55e",
    "#ec4899", "#14b8a6", "#eab308", "#ef4444",
]

FORMAT_MAP = {
    "IMAX":    ["imax"],
    "Dolby":   ["dolby"],
    "ScreenX": ["screenx"],
    "4DX":     ["4dx"],
    "PLF":     ["plf"],
    "Laser":   ["laser"],
    "Prime":   ["prime at amc"],
    "Dine-In": ["dine-in", "fork"],
    "70mm":    ["70mm"],
}


class AmcError(Exception):
    pass


# ── Helpers ────────────────────────────────────────────────────────────────────
def detect_formats(st: dict) -> list[str]:
    pf = (st.get("premiumFormat") or "").lower()
    combined = pf + " " + " ".join(
        "{} {} {}".format(a.get("code", ""), a.get("name", ""), a.get("description", "")).lower()
        for a in st.get("attributes", []) or []
    )
    return sorted(f for f, kws in FORMAT_MAP.items() if any(k in combined for k in kws))


def haversine_miles(lat1, lon1, lat2, lon2):
    r = 3958.8
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def theatre_coords(t: dict):
    """Try every field layout AMC has used for theatre coordinates."""
    for lat_k, lon_k in (("latitude", "longitude"), ("lat", "lon"), ("Latitude", "Longitude")):
        if t.get(lat_k) is not None and t.get(lon_k) is not None:
            return float(t[lat_k]), float(t[lon_k])
    for key in ("location", "address", "geo", "coordinates"):
        sub = t.get(key) or {}
        if not isinstance(sub, dict):
            continue
        for lat_k, lon_k in (("latitude", "longitude"), ("lat", "lon"), ("lat", "lng")):
            if sub.get(lat_k) is not None and sub.get(lon_k) is not None:
                return float(sub[lat_k]), float(sub[lon_k])
    return None, None


def _fmt_time(st: dict) -> str:
    raw = st.get("showDateTimeLocal") or st.get("showDateTime") or ""
    try:
        return datetime.fromisoformat(raw[:19]).strftime("%-I:%M %p")
    except ValueError:
        return raw[11:16] if len(raw) >= 16 else raw


# ── Client ─────────────────────────────────────────────────────────────────────
class AmcClient:
    def __init__(self, vendor_key: str, workers: int = 4):
        self.headers = {"X-AMC-Vendor-Key": vendor_key}
        self.workers = workers

    def _get(self, path, params=None, quiet404=False):
        for attempt in range(3):
            try:
                r = requests.get(BASE + path, headers=self.headers, params=params, timeout=20)
            except requests.RequestException:
                time.sleep(1 + attempt)
                continue
            if quiet404 and r.status_code == 404:
                return None
            if r.status_code in (401, 403):
                raise AmcError("AMC rejected the API key (HTTP {}).".format(r.status_code))
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        raise AmcError("AMC didn't respond for {}".format(path))

    def all_theatres(self) -> list[dict]:
        out, page = [], 1
        while True:
            data = self._get("/v2/theatres", {"page-number": page, "page-size": 100})
            if not data:
                break
            out.extend(data.get("_embedded", {}).get("theatres", []))
            if "next" not in data.get("_links", {}):
                break
            page += 1
        return out

    def _showtimes(self, theatre_id, date_str) -> list[dict]:
        rows, page = [], 1
        while True:
            data = self._get(
                "/v2/theatres/{}/showtimes/{}".format(theatre_id, date_str),
                {"page-number": page, "page-size": 100},
                quiet404=True,
            )
            if not data:
                break
            rows.extend(data.get("_embedded", {}).get("showtimes", []))
            if "next" not in data.get("_links", {}):
                break
            page += 1
        return rows

    def scan(self, theatres: list[dict], days: int, progress=None) -> dict:
        """theatres: [{id, name, miles, color}]. Returns the run's results dict."""
        today = date.today()
        dates = [(today + timedelta(days=i)).isoformat() for i in range(days)]
        tasks = [(t, d) for d in dates for t in theatres]
        collected = []
        done = 0
        pool = ThreadPoolExecutor(max_workers=self.workers)
        try:
            futs = {pool.submit(self._showtimes, t["id"], d): (t, d) for t, d in tasks}
            for fut in as_completed(futs):
                t, d = futs[fut]
                collected.append((t, d, fut.result()))  # AmcError propagates
                done += 1
                if progress:
                    progress(done / len(tasks), "Checked {} of {} theatre-days".format(done, len(tasks)))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return build_results(theatres, dates, collected)


def build_results(theatres, dates, collected) -> dict:
    """collected: [(theatre, date_str, [showtime dicts])] -> results dict."""
    movies: dict[str, dict] = {}
    busy_days = set()
    for t, d, showtimes in collected:
        tid = str(t["id"])
        for st in showtimes:
            mid = st.get("movieId")
            if not mid:
                continue
            busy_days.add(d)
            key = str(mid)
            fmts = detect_formats(st)
            m = movies.setdefault(key, {
                "amc_movie_id": int(mid),
                "title": st.get("movieName") or "Unknown",
                "movie_url": st.get("movieUrl") or "",
                "poster": (st.get("media") or {}).get("posterDynamic", ""),
                "rating": st.get("mpaaRating") or "",
                "runtime": st.get("runTime"),
                "genre": (st.get("genre") or "").title(),
                "formats": set(),
                "theatres": {},
            })
            m["formats"].update(fmts)
            th = m["theatres"].setdefault(tid, {"name": t["name"], "dates": {}})
            th["dates"].setdefault(d, []).append({
                "time": _fmt_time(st),
                "sort": st.get("showDateTimeLocal") or "",
                "formats": fmts,
                "url": st.get("purchaseUrl") or st.get("movieUrl") or "",
                "sold_out": bool(st.get("isSoldOut")),
            })

    out = []
    for m in movies.values():
        all_dates = set()
        for th in m["theatres"].values():
            for d, shows in th["dates"].items():
                shows.sort(key=lambda s: s["sort"])
                for s in shows:
                    s.pop("sort", None)
                all_dates.add(d)
        m["formats"] = sorted(m["formats"])
        m["is_imax"] = "IMAX" in m["formats"]
        m["dates"] = sorted(all_dates)
        m["theatre_count"] = len(m["theatres"])
        out.append(m)
    out.sort(key=lambda m: (m["dates"][0], m["title"].lower()))
    return {"movies": out, "empty_days": len([d for d in dates if d not in busy_days])}


# ── Geocoding ──────────────────────────────────────────────────────────────────
def geocode_zip(zip_code: str):
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"postalcode": zip_code, "country": "US", "format": "json", "limit": 1},
        headers={"User-Agent": "amc-tracker-web/1.0"},
        timeout=10,
    )
    r.raise_for_status()
    res = r.json()
    if not res:
        return None, None
    return float(res[0]["lat"]), float(res[0]["lon"])


def nearest(all_theatres: list[dict], lat, lon, count) -> list[dict]:
    scored = []
    for t in all_theatres:
        tlat, tlon = theatre_coords(t)
        if tlat is None:
            continue
        scored.append((haversine_miles(lat, lon, tlat, tlon), t))
    scored.sort(key=lambda x: x[0])
    return [
        {"id": t["id"], "name": t.get("longName") or t.get("name") or str(t["id"]),
         "slug": t.get("slug", ""), "miles": round(dist, 1),
         "color": THEATRE_COLORS[i % len(THEATRE_COLORS)]}
        for i, (dist, t) in enumerate(scored[:count])
    ]


# ── Demo data (used when no AMC key is configured, for trying the site) ───────
_DEMO_TITLES = [
    "Starlight Express", "The Long Harbor", "Paper Moons", "Cold Open",
    "Midnight Garden", "Iron Valley", "Sunday Drivers", "The Glass Orchard",
    "Echo Park Nights", "Northbound", "Kite Season", "Velvet Hour",
]


def demo_theatres(count: int) -> list[dict]:
    names = ["AMC River East 21", "AMC Roosevelt Collection 16", "AMC NewCity 14",
             "AMC Village Crossing 18", "AMC Block 37", "AMC Evanston 12",
             "AMC Yorktown 17", "AMC Oakbrook Center 12"]
    return [{"id": 1000 + i, "name": names[i % len(names)], "slug": "", "miles": round(1.2 + i * 2.3, 1),
             "color": THEATRE_COLORS[i % len(THEATRE_COLORS)]} for i in range(count)]


def demo_scan(theatres, days, progress=None) -> dict:
    rnd = random.Random(42)
    today = date.today()
    dates = [(today + timedelta(days=i)).isoformat() for i in range(days)]
    collected = []
    for i, d in enumerate(dates):
        for t in theatres:
            shows = []
            for n, title in enumerate(_DEMO_TITLES):
                start = (n * 9) % max(days, 1)
                if not (start <= i < start + 14) or rnd.random() < 0.25:
                    continue
                if n % 5 == 0 and t is not theatres[0]:
                    continue  # some movies only at one theatre
                imax = n % 4 == 0 and t is theatres[0]
                for hour in (13, 16, 19):
                    shows.append({
                        "movieId": 9000 + n, "movieName": title,
                        "movieUrl": "https://www.amctheatres.com/movies",
                        "showDateTimeLocal": "{}T{:02d}:15:00".format(d, hour),
                        "premiumFormat": "IMAX" if imax else "",
                        "purchaseUrl": "https://www.amctheatres.com/movies",
                    })
            collected.append((t, d, shows))
        if progress:
            progress((i + 1) / len(dates), "Demo day {} of {}".format(i + 1, len(dates)))
    return build_results(theatres, dates, collected)
