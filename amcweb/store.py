"""
Data layer. Two interchangeable backends:

* SupabaseStore — the real shared database (used when SUPABASE_URL/KEY are set)
* LocalStore    — a JSON file on disk, for trying the site on your own computer

Both expose the same methods, so the UI never cares which one it's talking to.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from .datefmt import to_date

KEEP_RUNS = 5
DEFAULT_PREFS = {"zip": None, "theatre_count": 5, "days": 90}
DEFAULT_DISPLAY = {"show_times": False}
CARD_FIELDS = ("poster", "rating", "runtime", "genre")
BUCKET = "run-screenshots"
BOOL_FIELDS = ("alist_available", "jonathan_purchased", "needs_refund", "needs_alternative")
EDITABLE = {"title", "users", "notes", *BOOL_FIELDS}


def auto_note(is_imax: bool, theatre_count: int) -> str:
    parts = []
    if is_imax:
        parts.append("IMAX")
    if theatre_count == 1:
        parts.append("Only one theater")
    return "; ".join(parts)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
class SupabaseStore:
    kind = "supabase"

    def __init__(self, url: str, key: str):
        from supabase import create_client
        self.db = create_client(url, key)

    # users ───────────────────────────────────────────────────────────────────
    def list_users(self):
        return self.db.table("users").select("*").order("id").execute().data

    def get_user(self, slug):
        rows = self.db.table("users").select("*").eq("slug", slug).limit(1).execute().data
        return rows[0] if rows else None

    def save_prefs(self, slug, zip_code, theatre_count, days):
        self.db.table("users").update(
            {"zip": zip_code, "theatre_count": int(theatre_count), "days": int(days)}
        ).eq("slug", slug).execute()

    # tracker ─────────────────────────────────────────────────────────────────
    def list_tracker(self):
        rows = self.db.table("movies").select("*, movie_dates(show_date)").execute().data
        for r in rows:
            r["dates"] = sorted(to_date(d["show_date"]) for d in r.pop("movie_dates", []) or [])
            r["users"] = r.get("users") or []
        return rows

    def add_to_tracker(self, user_name, movie):
        self.db.rpc("add_movie_to_tracker", {
            "p_amc_movie_id": movie["amc_movie_id"],
            "p_title": movie["title"],
            "p_user": user_name,
            "p_dates": [str(d) for d in movie["dates"]],
            "p_is_imax": bool(movie.get("is_imax")),
            "p_theatre_count": int(movie.get("theatre_count") or 0),
            "p_movie_url": movie.get("movie_url") or None,
        }).execute()

    def update_movie(self, movie_id, fields):
        fields = dict(fields)
        dates = fields.pop("dates", None)
        row = {k: v for k, v in fields.items() if k in EDITABLE}
        if row:
            row["updated_at"] = _now_iso()
            self.db.table("movies").update(row).eq("id", movie_id).execute()
        if dates is not None:
            self.db.table("movie_dates").delete().eq("movie_id", movie_id).execute()
            if dates:
                self.db.table("movie_dates").insert(
                    [{"movie_id": movie_id, "show_date": str(d)} for d in sorted(set(dates))]
                ).execute()

    def delete_movie(self, movie_id):
        self.db.table("movies").delete().eq("id", movie_id).execute()

    # runs ────────────────────────────────────────────────────────────────────
    def save_run(self, slug, meta, movies, png: bytes | None):
        user = self.get_user(slug)
        run_id = str(uuid.uuid4())
        path = None
        if png:
            path = "{}/{}.png".format(slug, run_id)
            self.db.storage.from_(BUCKET).upload(
                path=path, file=png, file_options={"content-type": "image/png"})
        self.db.table("runs").insert({
            "id": run_id, "user_id": user["id"], "run_at": meta["run_at"],
            "zip": meta.get("zip"), "theatre_count": meta.get("theatre_count"),
            "days": meta.get("days"), "theatres": meta.get("theatres", []),
            "movie_count": len(movies), "empty_days": meta.get("empty_days", 0),
            "screenshot_path": path,
        }).execute()
        rows = [{
            "run_id": run_id, "amc_movie_id": m.get("amc_movie_id"), "title": m["title"],
            "movie_url": m.get("movie_url"), "is_imax": bool(m.get("is_imax")),
            "formats": m.get("formats", []), "theatre_count": m.get("theatre_count", 0),
            "dates": [str(d) for d in m["dates"]], "theatres": m.get("theatres", {}),
            "is_new": bool(m.get("is_new")),
            **{f: m.get(f) or None for f in CARD_FIELDS},
        } for m in movies]
        for i in range(0, len(rows), 200):
            self.db.table("run_results").insert(rows[i:i + 200]).execute()
        self._prune(user["id"])
        return run_id

    def _prune(self, user_id):
        runs = (self.db.table("runs").select("id, screenshot_path").eq("user_id", user_id)
                .order("run_at", desc=True).execute().data)
        old = runs[KEEP_RUNS:]
        if not old:
            return
        paths = [r["screenshot_path"] for r in old if r.get("screenshot_path")]
        if paths:
            try:
                self.db.storage.from_(BUCKET).remove(paths)
            except Exception:
                pass  # a leftover image is harmless; don't fail the run over it
        self.db.table("runs").delete().in_("id", [r["id"] for r in old]).execute()

    def flag_new(self, slug, movies):
        """Mark movies this person has never seen before (m['is_new']) and remember them."""
        user = self.get_user(slug)
        ids = [m["amc_movie_id"] for m in movies if m.get("amc_movie_id")]
        seen = set()
        for i in range(0, len(ids), 150):
            rows = (self.db.table("seen_movies").select("amc_movie_id").eq("user_id", user["id"])
                    .in_("amc_movie_id", ids[i:i + 150]).execute().data)
            seen.update(r["amc_movie_id"] for r in rows)
        fresh = []
        for m in movies:
            m["is_new"] = m.get("amc_movie_id") not in seen
            if m["is_new"]:
                fresh.append({"user_id": user["id"], "amc_movie_id": m["amc_movie_id"], "title": m["title"]})
        for i in range(0, len(fresh), 200):
            self.db.table("seen_movies").upsert(
                fresh[i:i + 200], on_conflict="user_id,amc_movie_id", ignore_duplicates=True).execute()
        return movies

    def reset_user(self, slug):
        """Delete this person's runs, screenshots and seen-history; settings back to defaults."""
        user = self.get_user(slug)
        runs = self.db.table("runs").select("id, screenshot_path").eq("user_id", user["id"]).execute().data
        paths = [r["screenshot_path"] for r in runs if r.get("screenshot_path")]
        if paths:
            try:
                self.db.storage.from_(BUCKET).remove(paths)
            except Exception:
                pass
        self.db.table("runs").delete().eq("user_id", user["id"]).execute()
        self.db.table("seen_movies").delete().eq("user_id", user["id"]).execute()
        self.db.table("users").update(DEFAULT_PREFS).eq("id", user["id"]).execute()
        try:
            self.db.table("users").update(DEFAULT_DISPLAY).eq("id", user["id"]).execute()
        except Exception:
            pass  # column added by update_3.sql; fine if not there yet

    def set_show_times(self, slug, on):
        self.db.table("users").update({"show_times": bool(on)}).eq("slug", slug).execute()

    def list_runs(self, slug):
        user = self.get_user(slug)
        if not user:
            return []
        return (self.db.table("runs").select("*").eq("user_id", user["id"])
                .order("run_at", desc=True).limit(KEEP_RUNS).execute().data)

    def get_run(self, run_id):
        meta = self.db.table("runs").select("*").eq("id", run_id).limit(1).execute().data
        if not meta:
            return None, []
        movies = (self.db.table("run_results").select("*").eq("run_id", run_id)
                  .order("id").execute().data)
        return meta[0], movies

    def screenshot(self, path):
        if not path:
            return None
        try:
            return self.db.storage.from_(BUCKET).download(path)
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════════════
class LocalStore:
    """Same API, stored in a JSON file. Good for trying it out; not shared."""
    kind = "local"
    _lock = threading.Lock()

    def __init__(self, folder: str | Path = "local_data"):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "screenshots").mkdir(exist_ok=True)
        self.file = self.folder / "db.json"
        if not self.file.exists():
            self._write({
                "users": [
                    {"id": 1, "slug": "jd", "display_name": "JD", "zip": None, "theatre_count": 5, "days": 90},
                    {"id": 2, "slug": "meagan", "display_name": "Meagan", "zip": None, "theatre_count": 5, "days": 90},
                    {"id": 3, "slug": "kevin", "display_name": "Kevin", "zip": None, "theatre_count": 5, "days": 90},
                ],
                "movies": [], "runs": [], "run_results": [], "seen": {}, "next_id": 1,
            })

    def _read(self):
        return json.loads(self.file.read_text())

    def _write(self, data):
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, default=str))
        tmp.replace(self.file)

    # users
    def list_users(self):
        return self._read()["users"]

    def get_user(self, slug):
        return next((u for u in self.list_users() if u["slug"] == slug), None)

    def save_prefs(self, slug, zip_code, theatre_count, days):
        with self._lock:
            data = self._read()
            for u in data["users"]:
                if u["slug"] == slug:
                    u.update(zip=zip_code, theatre_count=int(theatre_count), days=int(days))
            self._write(data)

    def set_show_times(self, slug, on):
        with self._lock:
            data = self._read()
            for u in data["users"]:
                if u["slug"] == slug:
                    u["show_times"] = bool(on)
            self._write(data)

    # tracker
    def list_tracker(self):
        rows = self._read()["movies"]
        for r in rows:
            r["dates"] = sorted(to_date(d) for d in r["dates"])
        return rows

    def add_to_tracker(self, user_name, movie):
        with self._lock:
            data = self._read()
            row = next((m for m in data["movies"] if m["amc_movie_id"] == movie["amc_movie_id"]), None)
            if row is None:
                row = {
                    "id": data["next_id"], "amc_movie_id": movie["amc_movie_id"],
                    "title": movie["title"], "users": [user_name],
                    **{f: False for f in BOOL_FIELDS},
                    "notes": auto_note(bool(movie.get("is_imax")), int(movie.get("theatre_count") or 0)),
                    "movie_url": movie.get("movie_url"), "dates": [],
                }
                data["next_id"] += 1
                data["movies"].append(row)
            elif user_name not in row["users"]:
                row["users"].append(user_name)
            row["dates"] = sorted({*map(str, row["dates"]), *map(str, movie["dates"])})
            self._write(data)

    def update_movie(self, movie_id, fields):
        with self._lock:
            data = self._read()
            for m in data["movies"]:
                if m["id"] == movie_id:
                    for k, v in fields.items():
                        if k == "dates":
                            m["dates"] = sorted({str(d) for d in v})
                        elif k in EDITABLE:
                            m[k] = v
            self._write(data)

    def delete_movie(self, movie_id):
        with self._lock:
            data = self._read()
            data["movies"] = [m for m in data["movies"] if m["id"] != movie_id]
            self._write(data)

    # runs
    def save_run(self, slug, meta, movies, png):
        with self._lock:
            data = self._read()
            user = next(u for u in data["users"] if u["slug"] == slug)
            run_id = str(uuid.uuid4())
            path = None
            if png:
                path = "{}_{}.png".format(slug, run_id)
                (self.folder / "screenshots" / path).write_bytes(png)
            data["runs"].append({
                "id": run_id, "user_id": user["id"], "run_at": meta["run_at"],
                "zip": meta.get("zip"), "theatre_count": meta.get("theatre_count"),
                "days": meta.get("days"), "theatres": meta.get("theatres", []),
                "movie_count": len(movies), "empty_days": meta.get("empty_days", 0),
                "screenshot_path": path,
            })
            for m in movies:
                data["run_results"].append({**m, "run_id": run_id,
                                            "dates": [str(d) for d in m["dates"]]})
            mine = sorted((r for r in data["runs"] if r["user_id"] == user["id"]),
                          key=lambda r: r["run_at"], reverse=True)
            drop = {r["id"] for r in mine[KEEP_RUNS:]}
            for r in mine[KEEP_RUNS:]:
                if r.get("screenshot_path"):
                    (self.folder / "screenshots" / r["screenshot_path"]).unlink(missing_ok=True)
            data["runs"] = [r for r in data["runs"] if r["id"] not in drop]
            data["run_results"] = [r for r in data["run_results"] if r["run_id"] not in drop]
            self._write(data)
            return run_id

    def flag_new(self, slug, movies):
        with self._lock:
            data = self._read()
            seen = set(data.setdefault("seen", {}).get(slug, []))
            for m in movies:
                m["is_new"] = m.get("amc_movie_id") not in seen
                seen.add(m.get("amc_movie_id"))
            data["seen"][slug] = sorted(x for x in seen if x is not None)
            self._write(data)
        return movies

    def reset_user(self, slug):
        with self._lock:
            data = self._read()
            user = next(u for u in data["users"] if u["slug"] == slug)
            user.update(DEFAULT_PREFS, **DEFAULT_DISPLAY)
            mine = {r["id"] for r in data["runs"] if r["user_id"] == user["id"]}
            for r in data["runs"]:
                if r["id"] in mine and r.get("screenshot_path"):
                    (self.folder / "screenshots" / r["screenshot_path"]).unlink(missing_ok=True)
            data["runs"] = [r for r in data["runs"] if r["id"] not in mine]
            data["run_results"] = [r for r in data["run_results"] if r["run_id"] not in mine]
            data.setdefault("seen", {}).pop(slug, None)
            self._write(data)

    def list_runs(self, slug):
        user = self.get_user(slug)
        if not user:
            return []
        runs = [r for r in self._read()["runs"] if r["user_id"] == user["id"]]
        return sorted(runs, key=lambda r: r["run_at"], reverse=True)[:KEEP_RUNS]

    def get_run(self, run_id):
        data = self._read()
        meta = next((r for r in data["runs"] if r["id"] == run_id), None)
        return meta, [r for r in data["run_results"] if r["run_id"] == run_id]

    def screenshot(self, path):
        p = self.folder / "screenshots" / (path or "")
        return p.read_bytes() if path and p.exists() else None
