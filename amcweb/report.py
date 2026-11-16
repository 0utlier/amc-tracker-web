"""
The original amc_tracker.py HTML report, ported to the website.

render_fragment() returns the report as a self-contained block that can sit
inside a Streamlit page (styles are scoped under .amcr so they don't leak).
render_page() wraps the same block in a full HTML file for download.
"""
from __future__ import annotations

import html
from datetime import datetime

from .datefmt import to_date

FMT_LABEL = {"IMAX": "IMAX", "Dolby": "DOLBY CINEMA", "ScreenX": "ScreenX", "4DX": "4DX",
             "PLF": "PLF", "Laser": "LASER", "Prime": "PRIME", "Dine-In": "DINE-IN", "70mm": "70MM"}
FMT_CSS = {"IMAX": "imax", "Dolby": "dolby", "ScreenX": "screenx", "4DX": "4dx", "PLF": "plf",
           "Laser": "laser", "Prime": "prime", "Dine-In": "dinein", "70mm": "70mm"}

CSS = """
<style>
.amcr{--bg:#0d0d12;--surface:#18182a;--card:#1e1e32;--accent:#e94560;--new:#00d4a8;
  --text:#e8e8f0;--muted:#6a6a88;--border:rgba(255,255,255,.07);
  color:var(--text);font-family:-apple-system,"Segoe UI",system-ui,sans-serif;line-height:1.4}
.amcr *{box-sizing:border-box}
.amcr a{color:inherit;text-decoration:none}
.amcr .r-h1{font-size:1.9rem;font-weight:700;color:var(--accent);letter-spacing:-.02em;margin:0}
.amcr .r-h1 span{font-weight:400;opacity:.7}
.amcr .r-sub{color:var(--muted);margin-top:6px;font-size:.9rem}
.amcr .stats{display:flex;flex-wrap:wrap;gap:14px;margin:24px 0}
.amcr .stat{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:14px 18px;text-align:center;flex:1;min-width:120px}
.amcr .stat .n{font-size:1.9rem;font-weight:700}
.amcr .stat .l{font-size:.78rem;color:var(--muted);margin-top:3px}
.amcr .filter-bar{margin:20px 0 8px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.amcr .filter-label{font-size:.75rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-right:4px}
.amcr .theatre-toggle{background:var(--surface);border:1px solid rgba(255,255,255,.1);border-radius:20px;
  padding:6px 14px;cursor:pointer;font-size:.8rem;color:var(--muted);display:flex;align-items:center;
  gap:6px;transition:all .15s;white-space:nowrap;font-family:inherit}
.amcr .theatre-toggle.active{color:var(--text);border-color:var(--tc);
  background:color-mix(in srgb,var(--tc) 12%,var(--surface))}
.amcr .theatre-toggle:hover{border-color:var(--tc);color:var(--text)}
.amcr .toggle-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;opacity:.4;transition:opacity .15s}
.amcr .theatre-toggle.active .toggle-dot{opacity:1}
.amcr .filter-reset{background:none;border:none;color:var(--muted);font-size:.75rem;cursor:pointer;
  padding:4px 8px;margin-left:4px;font-family:inherit}
.amcr .filter-reset:hover{color:var(--text)}
.amcr .r-section{margin-top:32px}
.amcr .r-h2{font-size:.8rem;font-weight:600;margin:0 0 16px;letter-spacing:.09em;text-transform:uppercase}
.amcr .r-h2.new{color:var(--new)} .amcr .r-h2.all{color:var(--muted)}
.amcr .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px}
.amcr .card{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;
  position:relative;transition:transform .12s,border-color .12s,opacity .2s;display:flex;flex-direction:column}
.amcr .card:hover{transform:translateY(-2px);border-color:rgba(255,255,255,.14)}
.amcr .card.isnew{border-color:rgba(0,212,168,.3)}
.amcr .card.dimmed{opacity:.25}
.amcr .poster{width:100%;aspect-ratio:2/3;object-fit:cover;display:block;background:var(--surface)}
.amcr .no-poster{width:100%;aspect-ratio:2/3;background:var(--surface);display:flex;align-items:center;
  justify-content:center;font-size:2rem;color:var(--muted)}
.amcr .badge{position:absolute;top:8px;right:8px;background:var(--new);color:#002e27;font-size:.6rem;
  font-weight:700;padding:3px 8px;border-radius:20px;letter-spacing:.05em}
.amcr .theatre-dots{position:absolute;top:8px;left:8px;display:flex;gap:4px}
.amcr .tdot{width:9px;height:9px;border-radius:50%;border:1.5px solid rgba(0,0,0,.4)}
.amcr .info{padding:10px 12px;flex:1;display:flex;flex-direction:column;gap:4px}
.amcr .info .title{font-weight:600;font-size:.88rem;line-height:1.35}
.amcr .info .meta{font-size:.72rem;color:var(--muted)}
.amcr .first-seen{font-size:.7rem;color:var(--muted);margin-top:2px}
.amcr .card-formats{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.amcr .dates-btn{margin-top:auto;background:none;border:none;border-top:1px solid var(--border);
  color:var(--muted);font-size:.72rem;cursor:pointer;text-align:left;width:100%;padding:8px 12px;
  transition:color .1s;font-family:inherit}
.amcr .dates-btn span{font-size:.65rem;opacity:.6}
.amcr .dates-btn:hover{color:var(--text)}
.amcr .fmt{display:inline-block;font-weight:700;border-radius:4px;letter-spacing:.06em;font-size:.58rem;padding:2px 5px}
.amcr .f-imax{background:#000;color:#fff;font-style:italic;letter-spacing:.12em}
.amcr .f-dolby{background:#000;color:#fff}
.amcr .f-screenx{background:#1a0550;color:#c8b8ff}
.amcr .f-4dx{background:#c0310a;color:#fff}
.amcr .f-plf{background:#0a3060;color:#afd4ff}
.amcr .f-laser{background:#0a3060;color:#00d4a8}
.amcr .f-prime{background:#1a2a1a;color:#7ec850}
.amcr .f-dinein{background:#2a1a0a;color:#d4a050}
.amcr .f-70mm{background:#2a1a00;color:#fbbf24}
.amcr-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:1000200;
  align-items:center;justify-content:center;padding:20px}
.amcr-overlay.open{display:flex}
.amcr .modal{background:#1e1e32;border:1px solid rgba(255,255,255,.12);border-radius:16px;padding:24px;
  max-width:500px;width:100%;max-height:80vh;overflow-y:auto;position:relative}
.amcr .modal-close{position:absolute;top:12px;right:14px;background:none;border:none;color:var(--muted);
  font-size:1.4rem;cursor:pointer;padding:4px 8px}
.amcr .modal-close:hover{color:var(--text)}
.amcr .modal-h{font-size:1rem;font-weight:600;margin:0 0 4px;padding-right:28px}
.amcr .modal-meta{font-size:.78rem;color:var(--muted);margin-bottom:16px}
.amcr .section-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:14px}
.amcr .card-foot{margin-top:auto;display:flex;align-items:stretch;border-top:1px solid var(--border)}
.amcr .card-foot .dates-btn{margin-top:0;border-top:none;flex:1;min-width:0}
.amcr .list-btn{flex:0 0 auto;width:34px;height:34px;margin:auto 10px auto 0;border-radius:50%;border:none;
  font-size:1.25rem;font-weight:700;line-height:1;cursor:pointer;display:flex;align-items:center;
  justify-content:center;font-family:inherit;transition:transform .1s,filter .1s;padding:0}
.amcr .list-btn:hover{filter:brightness(1.15)}
.amcr .list-btn:active{transform:scale(.92)}
.amcr .list-btn.add{background:#16a34a;color:#fff}
.amcr .list-btn.remove{background:#dc2626;color:#fff}
.amcr .list-btn[disabled]{opacity:.5;cursor:default}
.amcr .modal-theatre{margin-bottom:18px}
.amcr .modal-theatre:last-child{margin-bottom:0}
.amcr .modal-theatre-label{font-size:.78rem;font-weight:600;margin-bottom:8px;display:flex;align-items:center;gap:7px}
.amcr .modal-tdot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
.amcr .date-chips{display:flex;flex-wrap:wrap;gap:7px}
.amcr .date-chip{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:5px 10px;
  font-size:.76rem;display:flex;flex-direction:column;gap:3px}
.amcr .date-chip .d{display:flex;align-items:center;gap:6px}
.amcr .date-chip a.dlink{text-decoration:underline;text-decoration-color:rgba(255,255,255,.25);
  text-underline-offset:3px}
.amcr .date-chip a.dlink:hover{color:#fff;text-decoration-color:currentColor}
.amcr .date-chip .t{font-size:.66rem;color:var(--muted)}
.amcr .date-chip .t a{text-decoration:underline;text-decoration-color:rgba(255,255,255,.2)}
.amcr .date-chip .t a:hover{color:var(--text)}
.amcr .empty{color:var(--muted);font-size:.9rem;text-align:center;padding:24px;
  border:1px dashed var(--border);border-radius:10px}
@media (max-width:640px){
  .amcr .r-h1{font-size:1.45rem}
  .amcr .stats{gap:8px;margin:16px 0}
  .amcr .stat{padding:10px 8px;min-width:70px}
  .amcr .stat .n{font-size:1.4rem}
  .amcr .grid{grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
}
</style>
"""

JS = """
<script>
(function () {
  if (window.__amcrInit) return;
  window.__amcrInit = true;
  function closeAll() {
    document.querySelectorAll('.amcr-overlay.open').forEach(function (m) { m.classList.remove('open'); });
    document.body.style.overflow = '';
  }
  function applyFilter(root) {
    var active = [];
    root.querySelectorAll('.theatre-toggle.active').forEach(function (b) { active.push(b.dataset.amcrTid); });
    root.querySelectorAll('.card').forEach(function (card) {
      var tids = (card.dataset.theatres || '').split(',');
      card.classList.toggle('dimmed', !tids.some(function (t) { return active.indexOf(t) >= 0; }));
    });
  }
  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var opener = t.closest('[data-amcr-open]');
    if (opener) {
      var m = document.getElementById(opener.dataset.amcrOpen);
      if (m) { m.classList.add('open'); document.body.style.overflow = 'hidden'; }
      return;
    }
    if (t.closest('[data-amcr-close]') || t.classList.contains('amcr-overlay')) { closeAll(); return; }
    var tog = t.closest('[data-amcr-tid]');
    if (tog) {
      var root = tog.closest('.amcr');
      if (tog.classList.contains('active') && root.querySelectorAll('.theatre-toggle.active').length === 1) return;
      tog.classList.toggle('active');
      applyFilter(root);
      return;
    }
    var reset = t.closest('[data-amcr-reset]');
    if (reset) {
      var r = reset.closest('.amcr');
      r.querySelectorAll('.theatre-toggle').forEach(function (b) { b.classList.add('active'); });
      applyFilter(r);
    }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeAll(); });
})();
</script>
"""


def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _badge(fmt):
    return '<span class="fmt f-{}">{}</span>'.format(FMT_CSS.get(fmt, "imax"), _e(FMT_LABEL.get(fmt, fmt)))


def _fmt_date(d):
    try:
        return to_date(d).strftime("%a %b %-d")
    except Exception:
        return _e(d)


def _list_button(m, tracked):
    """Green + (add me to the shared list) or red - (take me off). None = no button (downloaded file)."""
    if tracked is None or not m.get("amc_movie_id"):
        return ""
    state = tracked.get(m["amc_movie_id"])
    if state == "me":
        return ('<button class="list-btn remove" data-amcr-list="remove:{}" title="Remove from the shared list" '
                'aria-label="Remove from list">&minus;</button>').format(m["amc_movie_id"])
    tip = "Add to the shared list" + (" ({} has it)".format(_e(state)) if state else "")
    return ('<button class="list-btn add" data-amcr-list="add:{}" title="{}" '
            'aria-label="Add to list">+</button>').format(m["amc_movie_id"], tip)


def _card_and_modal(prefix, m, theatre_info, is_new, show_times=False, tracked=None):
    sid = "{}-{}".format(prefix, m.get("amc_movie_id") or abs(hash(m["title"])))
    title = _e(m["title"])
    url = m.get("movie_url") or ""
    theatres = m.get("theatres") or {}
    meta_parts = []
    if m.get("runtime"):
        meta_parts.append("{} min".format(m["runtime"]))
    if m.get("rating"):
        meta_parts.append(_e(m["rating"]))
    if m.get("genre"):
        meta_parts.append(_e(m["genre"]))
    meta = " · ".join(meta_parts)

    lo = '<a href="{}" target="_blank" rel="noopener">'.format(_e(url)) if url else ""
    lc = "</a>" if url else ""
    poster = m.get("poster") or ""
    img = ('<img class="poster" src="{}" alt="{}" loading="lazy">'.format(_e(poster), title)
           if poster else '<div class="no-poster">&#127916;</div>')

    dots = "".join(
        '<span class="tdot" style="background:{}" title="{}"></span>'.format(
            theatre_info.get(tid, {}).get("color", "#888"), _e(th["name"]))
        for tid, th in theatres.items())
    imax = '<div class="card-formats">{}</div>'.format(_badge("IMAX")) if m.get("is_imax") else ""
    total_dates = len(m.get("dates") or [])
    tc = len(theatres)
    first = to_date(m["dates"][0]).strftime("%Y-%m-%d") if m.get("dates") else ""

    sections = []
    for tid, th in sorted(theatres.items(), key=lambda x: x[1]["name"]):
        info = theatre_info.get(tid, {})
        color = info.get("color", "#888")
        miles = info.get("miles")
        dist = " · {:.1f} mi".format(miles) if miles is not None else ""
        chips = []
        for d, shows in sorted(th["dates"].items()):
            has_imax = any("IMAX" in (s.get("formats") or []) for s in shows)
            times = ", ".join(
                '<a href="{}" target="_blank" rel="noopener">{}</a>'.format(_e(s["url"]), _e(s["time"]))
                if s.get("url") else _e(s["time"]) for s in shows)
            label = _fmt_date(d)
            if info.get("url"):
                label = '<a class="dlink" href="{}/showtimes?date={}" target="_blank" rel="noopener">{}</a>'.format(
                    _e(info["url"]), _e(str(d)[:10]), label)
            chips.append('<div class="date-chip"><div class="d">{}{}</div>{}</div>'.format(
                label, " " + _badge("IMAX") if has_imax else "",
                '<div class="t">{}</div>'.format(times) if show_times else ""))
        sections.append(
            '<div class="modal-theatre"><div class="modal-theatre-label" style="color:{c}">'
            '<span class="modal-tdot" style="background:{c}"></span>{n}{d}</div>'
            '<div class="date-chips">{chips}</div></div>'.format(c=color, n=_e(th["name"]), d=dist,
                                                                  chips="".join(chips)))

    modal = (
        '<div class="amcr-overlay" id="{sid}"><div class="modal">'
        '<button class="modal-close" data-amcr-close="1" aria-label="Close">&times;</button>'
        '<div class="modal-h">{lo}{title}{lc}</div><div class="modal-meta">{meta}</div>'
        '<div class="section-label">{tc} theatre{tpl} &middot; {td} show date{dpl}</div>{sections}'
        '</div></div>'
    ).format(sid=sid, title=title, meta=meta, lo=lo, lc=lc, tc=tc, tpl="" if tc == 1 else "s",
             td=total_dates, dpl="" if total_dates == 1 else "s", sections="".join(sections))

    card = (
        '<div class="card{cls}" data-theatres="{tids}">{badge}{lo}{img}{lc}'
        '<div class="theatre-dots">{dots}</div>'
        '<div class="info"><div class="title">{lo}{title}{lc}</div><div class="meta">{meta}</div>'
        '{imax}<div class="first-seen">First showing: {first}</div></div>'
        '<div class="card-foot"><button class="dates-btn" data-amcr-open="{sid}">&#128197; {td} date{dpl} '
        '&middot; {tc} theatre{tpl}<br><span>tap to expand &rsaquo;</span></button>{listbtn}</div></div>'
    ).format(listbtn=_list_button(m, tracked),cls=" isnew" if is_new else "", tids=",".join(theatres.keys()),
             badge='<span class="badge">NEW</span>' if is_new else "", lo=lo, lc=lc, img=img,
             dots=dots, title=title, meta=meta, imax=imax, first=first, sid=sid,
             td=total_dates, dpl="" if total_dates == 1 else "s", tc=tc, tpl="" if tc == 1 else "s")
    return card, modal


def render_fragment(user_name, meta, movies, prefix="r", when_text=None, show_times=False,
                    tracked=None) -> str:
    """tracked: {amc_movie_id: "me" | "<names>"} for movies already on the shared list."""
    """The report as an embeddable block (CSS + markup + JS)."""
    theatres = meta.get("theatres") or []
    theatre_info = {str(t["id"]): t for t in theatres}
    movies = sorted(movies, key=lambda m: (str(m["dates"][0]) if m.get("dates") else "", m["title"].lower()))
    new_movies = [m for m in movies if m.get("is_new")]

    cards, modals, new_cards = [], [], []
    for m in movies:
        card, modal = _card_and_modal(prefix, m, theatre_info, bool(m.get("is_new")), show_times, tracked)
        cards.append(card)
        modals.append(modal)
        if m.get("is_new"):
            new_cards.append(card)

    days = meta.get("days") or 0
    empty = meta.get("empty_days") or 0
    where = "near {}".format(_e(meta["zip"])) if meta.get("zip") else "(default theatres)"
    if when_text is None:
        try:
            when_text = datetime.fromisoformat(str(meta["run_at"])).strftime("%Y-%m-%d %H:%M")
        except Exception:
            when_text = str(meta.get("run_at", ""))[:16]
    subtitle = "{} theatre{} {} &middot; Scanned {} &middot; {}-day window".format(
        len(theatres), "" if len(theatres) == 1 else "s", where, _e(when_text), days)

    chips = "".join(
        '<button class="theatre-toggle active" data-amcr-tid="{tid}" style="--tc:{c}">'
        '<span class="toggle-dot" style="background:{c}"></span>{n}</button>'.format(
            tid=_e(t["id"]), c=t.get("color", "#888"), n=_e(t["name"]))
        for t in theatres)

    new_section = (
        '<div class="r-section"><div class="r-h2 new">&#10022; New this run ({})</div>'
        '<div class="grid">{}</div></div>'.format(len(new_cards), "".join(new_cards))
        if new_cards else
        '<div class="r-section"><div class="r-h2 new">New this run</div>'
        '<div class="empty">No new movies since your last run.</div></div>')
    all_section = (
        '<div class="r-section"><div class="r-h2 all">All upcoming movies ({})</div>'
        '<div class="grid">{}</div></div>'.format(len(movies), "".join(cards))
        if movies else '<div class="empty">No movies found.</div>')

    body = (
        '<div class="amcr">'
        '<div class="r-h1">&#127916; {user}’s AMC run</div><div class="r-sub">{sub}</div>'
        '<div class="stats">'
        '<div class="stat"><div class="n" style="color:var(--new)">{new}</div><div class="l">New this run</div></div>'
        '<div class="stat"><div class="n">{total}</div><div class="l">Unique movies</div></div>'
        '<div class="stat"><div class="n">{sched}</div><div class="l">Days with showtimes</div></div>'
        '<div class="stat"><div class="n" style="color:var(--muted)">{empty}</div><div class="l">Not yet scheduled</div></div>'
        '</div>'
        '<div class="filter-bar"><span class="filter-label">Filter</span>{chips}'
        '<button class="filter-reset" data-amcr-reset="1">Show all</button></div>'
        '{new_section}{all_section}{modals}</div>'
    ).format(user=_e(user_name), sub=subtitle, new=len(new_movies), total=len(movies),
             sched=max(days - empty, 0), empty=empty, chips=chips, new_section=new_section,
             all_section=all_section, modals="".join(modals))
    return CSS + body + JS


def render_page(user_name, meta, movies, when_text=None, show_times=False) -> str:
    """A standalone .html file, like the Mac script's amc_movies.html."""
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>AMC Tracker — {}</title></head>"
        "<body style='margin:0;background:#0d0d12;padding:28px 20px'>"
        "<div style='max-width:1200px;margin:0 auto'>{}</div></body></html>"
    ).format(_e(user_name), render_fragment(user_name, meta, movies, "p", when_text, show_times))
