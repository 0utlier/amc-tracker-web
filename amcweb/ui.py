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
def get_store():
    # The code's timestamp is part of the cache key, so after an update the site
    # builds a fresh connection instead of reusing one made by the old code.
    from pathlib import Path
    stamp = max(Path(__file__).with_name(n).stat().st_mtime for n in ("store.py", "ui.py"))
    return _make_store(stamp)


@st.cache_resource(max_entries=1)
def _make_store(stamp):  # no leading underscore: Streamlit must include it in the cache key
    import importlib
    from . import store as store_mod
    importlib.reload(store_mod)  # always build from the newest code
    url, key = secret("SUPABASE_URL"), secret("SUPABASE_KEY")
    if url and key:
        return store_mod.SupabaseStore(url, key)
    return store_mod.LocalStore(secret("LOCAL_DATA_DIR", "local_data"))


@st.cache_data(max_entries=40, show_spinner=False)
def _cached_run(_store, run_id, kind):
    # Saved runs never change, so each one is fetched from the database only once.
    meta, movies = _store.get_run(run_id)
    return meta, movies, (_store.screenshot(meta.get("screenshot_path")) if meta else None)


# The run report is shown as its own page inside a frame, exactly like opening the
# .html file: the browser scrolls it on its own, separate from Streamlit's page, and
# it's created once and never reloaded. Taps on +/- and "Open shared list" come out
# through window.__amcrSend; who-has-what goes in through __amcrApply.
REPORT_JS = r"""
export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  window.__amcrSend = setTriggerValue;
  window.__amcrState = { tracked: data.tracked, me: data.me };
  let fr = parentElement.querySelector(':scope > iframe.amcr-frame');
  if (!fr) {
    fr = document.createElement('iframe');
    fr.className = 'amcr-frame';
    fr.title = 'Run report';
    fr.style.cssText = 'width:100%;border:0;display:block;border-radius:12px;background:#0d0d12;' +
                       'height:calc(100dvh - 90px);min-height:520px';
    parentElement.appendChild(fr);
  }
  if (fr.__html !== data.html) {
    fr.__html = data.html;
    fr.srcdoc = data.html;
  }
  try {
    if (fr.contentWindow && fr.contentWindow.__amcrApply) fr.contentWindow.__amcrApply(window.__amcrState);
  } catch (e) {}
}
"""
_report_component = st.components.v2.component("amc_run_report", js=REPORT_JS, isolate_styles=False)


@st.cache_data(max_entries=20, show_spinner=False)
def _report_html(user_name, run_id, show_times, when, _meta, _movies):
    # Built once per run (+ setting), so the page sends identical HTML and the browser keeps it.
    return report.render_frame_page(user_name, _meta, _movies, when, show_times)


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


def _names(names):
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " & " + names[-1]


def _blip(title, action, extra=""):
    """Toast text: movie title, then what happened, then who else (each on its own line)."""
    lines = ["**{}**".format(title.replace("*", "\\*")), action] + ([extra] if extra else [])
    return "  \n".join(lines)


def _go_to_tracker():
    st.session_state["section"] = "Tracker"


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
    meta, movies, png = _cached_run(store, run_id, store.kind)
    if not meta:
        _cached_run.clear()
        st.warning("That run is no longer saved.")
        return
    movies = sorted(movies, key=lambda m: (str(m["dates"][0]) if m["dates"] else "", m["title"].lower()))
    when = _when(meta["run_at"])
    show_times = bool(user.get("show_times"))

    if show_shot and png:
        with st.expander("📸 Screenshot from this run", expanded=False):
            st.image(png, width="stretch")

    dl = st.container(horizontal=True, vertical_alignment="center")
    dl.caption("Download:")
    d1 = d2 = d3 = dl
    stamp = str(meta["run_at"])[:16].replace(":", "").replace("T", "_")
    name = user["display_name"]
    dl.download_button("🌐 Report (.html)", lambda: report.render_page(name, meta, movies, when, show_times),
                       "amc_report_{}.html".format(stamp), "text/html", key="{}_html".format(key),
                       on_click="ignore")
    if png:
        d1.download_button("📸 Screenshot", png, "amc_run_{}.png".format(stamp), "image/png",
                           key="{}_png".format(key), on_click="ignore")
    d2.download_button("📊 Excel", lambda: exports.run_xlsx(name, meta, movies, png),
                       "amc_run_{}.xlsx".format(stamp), key="{}_xlsx".format(key), on_click="ignore")
    d3.download_button("📄 CSV", lambda: exports.run_csv(meta, movies), "amc_run_{}.csv".format(stamp),
                       "text/csv", key="{}_csv".format(key), on_click="ignore")

    tracked = {str(t["amc_movie_id"]): list(t["users"]) for t in store.list_tracker()}
    html = _report_html(user["display_name"], run_id, show_times, when, meta, movies)
    res = _report_component(key="report_{}".format(key),
                            data={"html": html, "tracked": tracked, "me": user["display_name"]},
                            on_toggle_change=lambda: None, on_goto_change=_go_to_tracker)
    if res and res.toggle:
        action, mid = res.toggle.split(":")[:2]
        m = next((x for x in movies if str(x.get("amc_movie_id")) == mid), None)
        if m and action == "add":
            others = [u for u in tracked.get(mid, []) if u != user["display_name"]]
            store.add_to_tracker(user["display_name"], {**m, "dates": [to_date(d) for d in m["dates"]]})
            st.toast(_blip(m["title"], "Added to the list",
                           "{} added it too!".format(_names(others)) if others else ""), icon="✅")
        elif m and action == "remove":
            others = [u for u in tracked.get(mid, []) if u != user["display_name"]]
            store.remove_from_tracker(user["display_name"], m["amc_movie_id"])
            st.toast(_blip(m["title"], "Removed from the list",
                           "{} still {} it".format(_names(others), "has" if len(others) == 1 else "have")
                           if others else ""), icon="➖")
        st.rerun()  # refresh the +/- state from the database


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
                                 default="Table",
                                 label_visibility="collapsed") or "Table"
    bar.button("🔄", help="Refresh to see everyone's latest changes")
    with bar.popover("⬇️ Export"):
        st.download_button("📊 Excel (.xlsx)", lambda: exports.tracker_xlsx(movies), "amc_tracker.xlsx",
                           width="stretch", on_click="ignore")
        st.download_button("📄 CSV (.csv)", lambda: exports.tracker_csv(movies), "amc_tracker.csv",
                           "text/csv", width="stretch", on_click="ignore")

    if not movies:
        st.info("The tracker is empty. Run a search on Home and add movies from the results.")
        undo = st.session_state.get("trk_undo")
        if undo:  # removed the last one: still offer Undo
            row = st.container(horizontal=True, vertical_alignment="center")
            row.button("↩️ Undo", key="trk_undo_btn", type="primary", on_click=_undo_remove, args=(store,))
            row.caption("Removed “{}”".format(undo["title"]))
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

    undo = st.session_state.get("trk_undo")
    with st.expander("🗑️ Remove a movie from the tracker", expanded=bool(undo)):
        options = {m["id"]: "{} ({})".format(m["title"], compact(m["dates"])) for m in movies}
        mid = st.selectbox("Movie", list(options), format_func=options.get, key="trk_del_pick")
        row = st.container(horizontal=True, vertical_alignment="center")
        if row.button("Remove it", key="trk_del_btn"):
            target = next(m for m in movies if m["id"] == mid)
            others = [u for u in target["users"] if u != user["display_name"]]
            if others or user["display_name"] not in target["users"]:
                _confirm_remove(store, user, target, others)
            else:
                _remove_row(store, target)
        if undo:
            row.button("↩️ Undo", key="trk_undo_btn", type="primary", on_click=_undo_remove, args=(store,))
            row.caption("Removed “{}”".format(undo["title"]))


def _remove_row(store, target):
    store.delete_movie(target["id"])
    st.session_state["trk_undo"] = dict(target)  # full copy: names, dates, checkboxes, notes
    st.session_state["trk_ver"] = st.session_state.get("trk_ver", 0) + 1
    st.toast(_blip(target["title"], "Removed from the list", "Tap Undo to put it back"), icon="🗑️")
    st.rerun()


def _undo_remove(store):
    snap = st.session_state.pop("trk_undo", None)
    if snap:
        store.restore_movie(snap)
        st.session_state["trk_ver"] = st.session_state.get("trk_ver", 0) + 1
        st.toast(_blip(snap["title"], "Put back on the list"), icon="↩️")


@st.dialog("Remove this movie?")
def _confirm_remove(store, user, target, others):
    st.write("**{}**".format(target["title"]))
    if others:
        st.warning("{} {} added this movie. Removing it takes it off the list for everyone.".format(
            _names(others), "has" if len(others) == 1 else "have"), icon="👥")
    if user["display_name"] not in target["users"]:
        st.caption("You haven't added this one yourself.")
    with st.container(key="reset_zone_remove"):
        if st.button("Yes, remove it", width="stretch"):
            _remove_row(store, target)
    if st.button("Cancel", width="stretch"):
        st.rerun()


def _month_table(store, header, group, ver):
    df = pd.DataFrame([{
        "DATE": compact(m["dates"], header) if m["dates"] else "",
        "MOVIE": "{}#{}".format(m.get("movie_url") or "https://www.amctheatres.com/movies", m["title"]),
        "USER": ", ".join(m["users"]),
        **{col: bool(m[field]) for col, field in BOOL_COLS.items()},
        "NOTES": m.get("notes") or "",
    } for m in group])
    ed_key = "trk_{}_{}_{}".format(header[0], header[1], ver)
    st.data_editor(
        df, key=ed_key, hide_index=True, width="stretch", num_rows="fixed", disabled=["MOVIE"],
        height=36 * (len(df) + 1) + 4,
        on_change=_tracker_changed, args=(store, ed_key, [m["id"] for m in group], header),
        column_config={
            "DATE": st.column_config.TextColumn("DATE", width=140),
            "MOVIE": st.column_config.LinkColumn("MOVIE", width=190, display_text=r"#(.*)$",
                                                 help="Opens the movie on AMC"),
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


def _save_show_times(store, user):
    try:
        store.set_show_times(user["slug"], bool(st.session_state["set_show_times"]))
        st.toast("Saved", icon="✅")
    except Exception:
        st.toast("Couldn't save. Has update_3.sql been run in Supabase?", icon="⚠️")


def _clear_zip():
    st.session_state["set_zip"] = ""


@st.dialog("Reset everything for this person?")
def _confirm_reset(store, user):
    st.write("This permanently deletes **{}**'s last 5 runs and screenshots, forgets which movies "
             "they've already seen (so everything shows as NEW again), and puts settings back to "
             "the defaults: no ZIP (the 4 default theaters), 5 theaters, 90 days, showtimes hidden.".format(user["display_name"]))
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
    st.markdown("**Display**")
    st.toggle("Show showtimes in the date pop-up", value=bool(user.get("show_times")),
              key="set_show_times", on_change=_save_show_times, args=(store, user),
              help="Off: each date shows just the date, like the original report. "
                   "On: each date also lists its times, which link to AMC tickets.")

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
