"""All the screens: Home, Tracker, Settings, History, plus the run-results view."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from itertools import groupby

import pandas as pd
import streamlit as st

from . import amc, exports, report, snapshot
from .config import secret, truthy
from .datefmt import compact, month_label, parse, to_date
from .store import LocalStore, SupabaseStore

SECTIONS = ["Home", "Tracker", "Settings", "History"]
DEFAULT_SLUGS = ["amc-river-east-21", "amc-roosevelt-collection-16",
                 "amc-newcity-14", "amc-village-crossing-18"]


def default_slugs():
    raw = secret("DEFAULT_THEATRE_SLUGS", "")
    return [x.strip() for x in str(raw).split(",") if x.strip()] or DEFAULT_SLUGS
ICONS = {"Home": "🏠", "Tracker": "📋", "Settings": "⚙️", "History": "🕘"}
BOOL_COLS = {
    "A-List Available": "alist_available",
    "Jonathan Purchased": "jonathan_purchased",
    "NEEDS REFUND": "needs_refund",
    "NEEDS ALTERNATIVE": "needs_alternative",
}

CSS = """
<style>
[data-testid="stMainBlockContainer"], .block-container {
  padding-top: 4.5rem; padding-bottom: 4rem; max-width: 1320px; }
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"], .block-container {
    padding-left: .7rem; padding-right: .7rem; padding-top: 4rem; }
  h1 { font-size: 1.55rem !important; }
  h3 { font-size: 1.15rem !important; }
}
.month-h { font-size: .8rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  color: #00d4a8; margin: 1.6rem 0 .4rem; border-bottom: 1px solid rgba(255,255,255,.08);
  padding-bottom: .3rem; }
.muted { color: #8a8aa8; font-size: .85rem; }
.pill { display: inline-block; font-size: .68rem; font-weight: 700; padding: 1px 7px;
  border-radius: 4px; background: #000; color: #fff; font-style: italic; letter-spacing: .1em; }
.stButton > button, .stDownloadButton > button { min-height: 2.8rem; }
[class*="st-key-reset_zone"] button { background: #b3261e !important; border-color: #b3261e !important;
  color: #fff !important; }
[class*="st-key-reset_zone"] button:hover { background: #d93025 !important; border-color: #d93025 !important; }
.summary { display: flex; gap: .6rem; margin: .4rem 0 1rem; }
.summary > div { flex: 1; background: #1e1e32; border: 1px solid rgba(255,255,255,.08);
  border-radius: 12px; padding: .7rem .5rem; text-align: center; }
.summary b { display: block; font-size: 1.45rem; }
.summary span { font-size: .75rem; color: #8a8aa8; }
</style>
"""


# ── Shared resources ──────────────────────────────────────────────────────────
@st.cache_resource
def get_store():
    url, key = secret("SUPABASE_URL"), secret("SUPABASE_KEY")
    if url and key:
        return SupabaseStore(url, key)
    return LocalStore(secret("LOCAL_DATA_DIR", "local_data"))


def demo_mode() -> bool:
    return truthy(secret("DEMO_MODE", "")) or not secret("AMC_VENDOR_KEY")


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _all_theatres(vendor_key):
    return amc.AmcClient(vendor_key).all_theatres()


@st.cache_data(ttl=30 * 24 * 3600, show_spinner=False)
def _geocode(zip_code):
    return amc.geocode_zip(zip_code)


def _is_phone() -> bool:
    try:
        ua = st.context.headers.get("User-Agent", "")
    except Exception:
        return False
    return any(k in ua for k in ("iPhone", "Android", "Mobile"))


def _when(iso) -> str:
    try:
        dt = datetime.fromisoformat(str(iso))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        tz = st.context.timezone
        if tz:
            from zoneinfo import ZoneInfo
            dt = dt.astimezone(ZoneInfo(tz))
        return dt.strftime("%a %b %-d · %-I:%M %p")
    except Exception:
        return str(iso)[:16]


def _go(section):
    st.session_state["section"] = section


# ── Landing page (the bare URL) ───────────────────────────────────────────────
def landing(user_pages):
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("🎬 AMC Movie Tracker")
    st.write("Who's this?")
    for page in user_pages:
        st.page_link(page, label=page.title, icon="🍿")
    st.caption("Tip: bookmark your own page, or add it to your iPhone Home Screen "
               "(Share → Add to Home Screen).")


# ── Per-user page ─────────────────────────────────────────────────────────────
def user_page(slug):
    st.markdown(CSS, unsafe_allow_html=True)
    store = get_store()
    user = store.get_user(slug)
    if not user:
        st.error("No user called '{}'.".format(slug))
        return

    if st.session_state.get("slug") != slug:  # one browser visiting a different person's page
        for k in [k for k in st.session_state if k.startswith(("set_", "run_", "trk_"))]:
            del st.session_state[k]
        st.session_state["slug"] = slug
        st.session_state["section"] = st.query_params.get("tab", "Home").title()
        st.session_state.pop("current_run", None)
    if st.session_state.get("section") not in SECTIONS:  # e.g. tapped the selected tab again
        st.session_state["section"] = st.session_state.get("section_last", "Home")
    st.session_state["section_last"] = st.session_state["section"]

    if store.kind == "local":
        st.info("Local test mode — data is saved on this computer only. Add Supabase keys to share it.",
                icon="💾")
    if demo_mode():
        st.warning("Demo mode — searches return sample movies, not real AMC data.", icon="🧪")

    st.segmented_control(
        "Section", SECTIONS, key="section", label_visibility="collapsed",
        format_func=(lambda s: s) if _is_phone() else (lambda s: "{} {}".format(ICONS[s], s)),
    )
    section = st.session_state.get("section") or "Home"
    st.query_params["tab"] = section.lower()

    {"Home": home, "Tracker": tracker, "Settings": settings,
     "History": history}[section](store, user)


# ── Home ──────────────────────────────────────────────────────────────────────
def home(store, user):
    st.title("Hi, {} 👋".format(user["display_name"]))
    st.markdown(
        '<div class="summary"><div><b>{}</b><span>ZIP code</span></div>'
        '<div><b>{}</b><span>Theaters</span></div><div><b>{}</b><span>Days ahead</span></div></div>'
        .format(user.get("zip") or "Default",
                user["theatre_count"] if user.get("zip") else len(default_slugs()),
                user["days"]), unsafe_allow_html=True)
    if not user.get("zip"):
        st.caption("No ZIP set, so searches use the default theaters: River East, Roosevelt Collection, "
                   "NewCity and Village Crossing.")

    if st.button("▶️  Run Using My Defaults", type="primary", width="stretch"):
        run_search(store, user, user.get("zip"), user["theatre_count"], user["days"])
    b1, b2 = st.columns(2)
    b1.button("⚙️  Change Search Settings", width="stretch", on_click=_go, args=("Settings",))
    b2.button("🕘  My Last 5 Runs", width="stretch", on_click=_go, args=("History",))

    if st.session_state.get("current_run"):
        st.divider()
        st.subheader("Results from this run")
        render_run(store, user, st.session_state["current_run"], key="home", show_shot=False)


def run_search(store, user, zip_code, count, days):
    """Runs the AMC search, saves it to history, and shows it on Home."""
    with st.status("Searching AMC…", expanded=True) as status:
        try:
            if demo_mode():
                theatres = amc.demo_theatres(count if zip_code else len(default_slugs()), not zip_code)
            elif not zip_code:
                st.write("🎬 Using the default theaters…")
                theatres = amc.by_slugs(_all_theatres(secret("AMC_VENDOR_KEY")), default_slugs())
                if not theatres:
                    status.update(label="Couldn't find the default theaters on AMC", state="error")
                    return
                count = len(theatres)
            else:
                st.write("📍 Finding theaters near {}…".format(zip_code))
                lat, lon = _geocode(zip_code)
                if lat is None:
                    status.update(label="Couldn't find ZIP {}".format(zip_code), state="error")
                    return
                theatres = amc.nearest(_all_theatres(secret("AMC_VENDOR_KEY")), lat, lon, count)
                if not theatres:
                    status.update(label="No AMC theaters found near {}".format(zip_code), state="error")
                    return
            for t in theatres:
                st.write("• {}{}".format(t["name"], "" if t.get("miles") is None
                                          else " — {:.1f} mi".format(t["miles"])))

            bar = st.progress(0.0, text="Checking showtimes…")
            prog = lambda frac, msg: bar.progress(min(frac, 1.0), text=msg)
            if demo_mode():
                results = amc.demo_scan(theatres, days, prog)
            else:
                results = amc.AmcClient(secret("AMC_VENDOR_KEY")).scan(theatres, days, prog)

            meta = {"run_at": datetime.now(timezone.utc).isoformat(), "zip": zip_code,
                    "theatre_count": count, "days": days, "theatres": theatres,
                    "empty_days": results["empty_days"]}
            store.flag_new(user["slug"], results["movies"])
            st.write("📸 Saving screenshot & history…")
            png = snapshot.render(user["display_name"], meta, results["movies"], st.context.timezone)
            run_id = store.save_run(user["slug"], meta, results["movies"], png)
            st.session_state["current_run"] = run_id
            status.update(label="Found {} movies".format(len(results["movies"])),
                          state="complete", expanded=False)
        except amc.AmcError as e:
            status.update(label="AMC error: {}".format(e), state="error")
        except Exception as e:  # keep the page alive and show what broke
            status.update(label="Something went wrong: {}".format(e), state="error")
            st.exception(e)


# ── Run results (used on Home and in History) ────────────────────────────────
def render_run(store, user, run_id, key, show_shot=True):
    meta, movies = store.get_run(run_id)
    if not meta:
        st.warning("That run is no longer saved.")
        return
    movies = sorted(movies, key=lambda m: (str(m["dates"][0]) if m["dates"] else "", m["title"].lower()))
    when = _when(meta["run_at"])
    st.html(report.render_fragment(user["display_name"], meta, movies, prefix=key, when_text=when),
            unsafe_allow_javascript=True)

    png = store.screenshot(meta.get("screenshot_path"))
    if show_shot and png:
        with st.expander("📸 Screenshot from this run", expanded=False):
            st.image(png, width="stretch")

    st.markdown("**Download this run**")
    dl = st.container(horizontal=True)
    d1 = d2 = d3 = dl
    stamp = str(meta["run_at"])[:16].replace(":", "").replace("T", "_")
    dl.download_button("🌐 Report (.html)", report.render_page(user["display_name"], meta, movies, when),
                       "amc_report_{}.html".format(stamp), "text/html", key="{}_html".format(key))
    if png:
        d1.download_button("📸 Screenshot", png, "amc_run_{}.png".format(stamp), "image/png",
                           key="{}_png".format(key))
    d2.download_button("📊 Excel", exports.run_xlsx(user["display_name"], meta, movies, png),
                       "amc_run_{}.xlsx".format(stamp), key="{}_xlsx".format(key))
    d3.download_button("📄 CSV", exports.run_csv(meta, movies), "amc_run_{}.csv".format(stamp),
                       "text/csv", key="{}_csv".format(key))

    if not movies:
        return
    with st.expander("➕ Add movies from this run to the shared tracker", expanded=False):
        _add_to_tracker(store, user, run_id, key, movies)


def _add_to_tracker(store, user, run_id, key, movies):
    tracked = {m["amc_movie_id"]: m for m in store.list_tracker()}
    rows = []
    for m in movies:
        t = tracked.get(m["amc_movie_id"])
        status = ""
        if t:
            status = "✓ You" if user["display_name"] in t["users"] else "✓ " + ", ".join(t["users"])
        rows.append({
            "Add": False, "MOVIE": m["title"], "DATES": compact(m["dates"]),
            "THEATERS": m.get("theatre_count", 0), "IMAX": "IMAX" if m.get("is_imax") else "",
            "IN TRACKER": status, "AMC": m.get("movie_url") or None,
        })
    ed_key = "run_{}_{}_{}".format(key, run_id, st.session_state.get("run_ver", 0))
    edited = st.data_editor(
        pd.DataFrame(rows), key=ed_key, hide_index=True, width="stretch",
        height=min(36 * (len(rows) + 1) + 4, 1200),
        disabled=["MOVIE", "DATES", "THEATERS", "IMAX", "IN TRACKER", "AMC"],
        column_config={
            "Add": st.column_config.CheckboxColumn("Add", width="small", pinned=True),
            "MOVIE": st.column_config.TextColumn("MOVIE", width="medium", pinned=True),
            "THEATERS": st.column_config.NumberColumn("THEATERS", width="small"),
            "IMAX": st.column_config.TextColumn("IMAX", width="small"),
            "AMC": st.column_config.LinkColumn("AMC", display_text="Open", width="small"),
        },
    )
    picked = [movies[i] for i, v in enumerate(edited["Add"]) if v]
    if st.button("➕ Add {} selected to tracker".format(len(picked)), type="primary",
                 disabled=not picked, width="stretch", key="{}_add".format(key)):
        for m in picked:
            store.add_to_tracker(user["display_name"], {**m, "dates": [to_date(d) for d in m["dates"]]})
        st.session_state["run_ver"] = st.session_state.get("run_ver", 0) + 1
        st.toast("Added {} to the shared tracker".format(len(picked)), icon="✅")
        st.rerun()


# ── Shared tracker ────────────────────────────────────────────────────────────
def _tracker_changed(store, ed_key, ids, header):
    changes = st.session_state[ed_key].get("edited_rows", {})
    saved = 0
    for idx, change in changes.items():
        movie_id = ids[int(idx)]
        fields = {}
        for col, val in change.items():
            if col == "DATE":
                try:
                    fields["dates"] = parse(val, header)
                except ValueError as e:
                    st.toast("Date not saved: {}".format(e), icon="⚠️")
            elif col == "MOVIE":
                if (val or "").strip():
                    fields["title"] = val.strip()
            elif col == "USER":
                fields["users"] = [u.strip() for u in (val or "").split(",") if u.strip()]
            elif col == "NOTES":
                fields["notes"] = val or ""
            elif col in BOOL_COLS:
                fields[BOOL_COLS[col]] = bool(val)
        if fields:
            store.update_movie(movie_id, fields)
            saved += 1
    st.session_state["trk_ver"] = st.session_state.get("trk_ver", 0) + 1
    if saved:
        st.toast("Saved", icon="✅")


def _card_changed(store, movie_id, field, wkey):
    store.update_movie(movie_id, {field: st.session_state[wkey]})
    st.toast("Saved", icon="✅")


def tracker(store, user):
    st.title("📋 Shared tracker")
    movies = exports.sort_tracker(store.list_tracker())

    bar = st.container(horizontal=True, vertical_alignment="center")
    view = bar.segmented_control("View", ["Table", "Cards"], key="trk_view",
                                 default="Cards" if _is_phone() else "Table",
                                 label_visibility="collapsed") or "Table"
    bar.button("🔄", help="Refresh to see everyone's latest changes")
    with bar.popover("⬇️ Export"):
        st.download_button("📊 Excel (.xlsx)", exports.tracker_xlsx(movies), "amc_tracker.xlsx",
                           width="stretch")
        st.download_button("📄 CSV (.csv)", exports.tracker_csv(movies), "amc_tracker.csv",
                           "text/csv", width="stretch")

    if not movies:
        st.info("The tracker is empty. Run a search on Home and add movies from the results.")
        return
    st.caption("Edits save automatically. In DATE, type days like 1-5, 7 & 9 "
               "(add a month for others: 28-31, Jan 1-3).")

    ver = st.session_state.get("trk_ver", 0)
    for key, group in groupby(movies, key=exports.month_key):
        group = list(group)
        label = month_label(*key) if key[0] != 9999 else "No dates"
        st.markdown('<div class="month-h">{}</div>'.format(label), unsafe_allow_html=True)
        if view == "Table":
            _month_table(store, key, group, ver)
        else:
            for m in group:
                _movie_card(store, key, m, ver)

    with st.expander("🗑️ Remove a movie from the tracker"):
        options = {m["id"]: "{} ({})".format(m["title"], compact(m["dates"])) for m in movies}
        mid = st.selectbox("Movie", list(options), format_func=options.get, key="trk_del_pick")
        if st.button("Remove it", key="trk_del_btn"):
            store.delete_movie(mid)
            st.session_state["trk_ver"] = ver + 1
            st.toast("Removed", icon="🗑️")
            st.rerun()


def _month_table(store, header, group, ver):
    df = pd.DataFrame([{
        "DATE": compact(m["dates"], header) if m["dates"] else "",
        "MOVIE": m["title"],
        "USER": ", ".join(m["users"]),
        **{col: bool(m[field]) for col, field in BOOL_COLS.items()},
        "NOTES": m.get("notes") or "",
    } for m in group])
    ed_key = "trk_{}_{}_{}".format(header[0], header[1], ver)
    st.data_editor(
        df, key=ed_key, hide_index=True, width="stretch", num_rows="fixed",
        height=36 * (len(df) + 1) + 4,
        on_change=_tracker_changed, args=(store, ed_key, [m["id"] for m in group], header),
        column_config={
            "DATE": st.column_config.TextColumn("DATE", width=140),
            "MOVIE": st.column_config.TextColumn("MOVIE", width=190),
            "USER": st.column_config.TextColumn("USER", width=110),
            **{c: st.column_config.CheckboxColumn(c, width=128) for c in BOOL_COLS},
            "NOTES": st.column_config.TextColumn("NOTES", width=210),
        },
    )


def _movie_card(store, header, m, ver):
    with st.container(border=True):
        title = "[{}]({})".format(m["title"], m["movie_url"]) if m.get("movie_url") else m["title"]
        st.markdown("**{}**".format(title))
        st.markdown('<div class="muted">📅 {} &nbsp;·&nbsp; 👤 {}</div>'.format(
            compact(m["dates"], header) or "—", ", ".join(m["users"]) or "—"), unsafe_allow_html=True)
        for label, field in BOOL_COLS.items():
            wkey = "trk_c_{}_{}_{}".format(m["id"], field, ver)
            st.checkbox(label, value=bool(m[field]), key=wkey,
                        on_change=_card_changed, args=(store, m["id"], field, wkey))
        nkey = "trk_c_{}_notes_{}".format(m["id"], ver)
        st.text_input("NOTES", value=m.get("notes") or "", key=nkey, placeholder="Notes",
                      label_visibility="collapsed",
                      on_change=_card_changed, args=(store, m["id"], "notes", nkey))


# ── Settings ──────────────────────────────────────────────────────────────────
def _load_saved(user):
    st.session_state["set_zip"] = user.get("zip") or ""
    st.session_state["set_count"] = int(user["theatre_count"])
    st.session_state["set_days"] = int(user["days"])


def _clear_zip():
    st.session_state["set_zip"] = ""


@st.dialog("Reset everything for this person?")
def _confirm_reset(store, user):
    st.write("This permanently deletes **{}**'s last 5 runs and screenshots, forgets which movies "
             "they've already seen (so everything shows as NEW again), and puts settings back to "
             "the defaults: no ZIP (the 4 default theaters), 5 theaters, 90 days.".format(user["display_name"]))
    st.caption("The shared tracker isn't touched.")
    with st.container(key="reset_zone_confirm"):
        if st.button("Yes, reset {}".format(user["display_name"]), width="stretch"):
            store.reset_user(user["slug"])
            for k in [k for k in st.session_state if k.startswith(("set_", "run_"))]:
                del st.session_state[k]
            st.session_state.pop("current_run", None)
            st.session_state["just_reset"] = True
            st.rerun()
    if st.button("Cancel", width="stretch"):
        st.rerun()


def settings(store, user):
    st.title("⚙️ Search settings")
    if st.session_state.pop("just_reset", False):
        st.success("Reset done. Everything is back to the defaults.")
    if "set_zip" not in st.session_state:
        _load_saved(user)

    z = st.session_state["set_zip"].strip()
    st.text_input("ZIP code", key="set_zip", max_chars=5,
                  placeholder="Leave blank for the 4 default theaters")
    if z:
        st.button("✖ Remove ZIP (use default theaters)", on_click=_clear_zip)
    else:
        st.caption("No ZIP: searches River East 21, Roosevelt Collection 16, NewCity 14 and "
                   "Village Crossing 18.")
    st.number_input("Number of theaters", min_value=1, max_value=12, step=1, key="set_count",
                    disabled=not z, help="Only used when a ZIP is set.")
    st.number_input("Days to search", min_value=1, max_value=120, step=1, key="set_days")
    st.caption("Saved defaults: {} · {} days".format(
        "ZIP {} · {} theaters".format(user["zip"], user["theatre_count"]) if user.get("zip")
        else "default 4 theaters", user["days"]))

    valid = (not z) or bool(re.fullmatch(r"\d{5}", z))
    if not valid:
        st.error("ZIP code should be 5 digits, or leave it blank.")

    c1, c2 = st.columns(2)
    if c1.button("💾 Save My Defaults", type="primary", width="stretch", disabled=not valid):
        store.save_prefs(user["slug"], z or None, st.session_state["set_count"], st.session_state["set_days"])
        st.toast("Defaults saved", icon="✅")
        st.rerun()
    c2.button("↩️ Restore My Defaults", width="stretch", on_click=_load_saved, args=(user,))

    st.divider()
    st.caption("Want a one-off search without changing your defaults?")
    if st.button("▶️ Run with these settings (don't save)", width="stretch", disabled=not valid):
        run_search(store, user, z or None, int(st.session_state["set_count"]),
                   int(st.session_state["set_days"]))
    if st.session_state.get("current_run"):
        st.button("See results on Home →", on_click=_go, args=("Home",))

    st.divider()
    st.markdown("**Reset**")
    st.caption("Deletes {}'s run history and puts every setting back to the defaults.".format(
        user["display_name"]))
    with st.container(key="reset_zone"):
        if st.button("🗑️ Reset {} to defaults".format(user["display_name"]), width="stretch"):
            _confirm_reset(store, user)


# ── History ───────────────────────────────────────────────────────────────────
def history(store, user):
    st.title("🕘 My last 5 runs")
    runs = store.list_runs(user["slug"])
    if not runs:
        st.info("No runs yet. Hit “Run Using My Defaults” on Home.")
        return
    labels = {r["id"]: "{}  ·  {} · {} theaters · {} days · {} movies".format(
        _when(r["run_at"]), ("ZIP " + r["zip"]) if r.get("zip") else "Default theaters", r.get("theatre_count"), r.get("days"),
        r.get("movie_count", 0)) for r in runs}
    run_id = st.radio("Run", list(labels), format_func=labels.get, key="run_hist_pick",
                      label_visibility="collapsed")
    st.divider()
    render_run(store, user, run_id, key="hist", show_shot=True)
