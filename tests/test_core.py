from datetime import date

import pytest

from amcweb import amc, exports, snapshot
from amcweb.datefmt import compact, parse
from amcweb.store import LocalStore

D = lambda *days: [date(2026, 12, d) for d in days]


@pytest.mark.parametrize("days, expected", [
    ((1, 2), "1 & 2"),
    ((1, 2, 3), "1-3"),
    ((1, 3, 4), "1, 3, 4"),
    ((1, 2, 3, 4, 5, 7, 8, 9, 11, 12), "1-5, 7-9, 11, 12"),
    ((5,), "5"),
    ((1, 9), "1 & 9"),
])
def test_compact_spec_examples(days, expected):
    assert compact(D(*days)) == expected


def test_compact_across_months():
    ds = D(29, 30, 31) + [date(2027, 1, 1), date(2027, 1, 2)]
    assert compact(ds) == "29-31, Jan 1, 2"
    assert compact([date(2026, 12, 31), date(2027, 1, 1)]) == "31 & Jan 1"


@pytest.mark.parametrize("days", [(1, 2), (1, 2, 3), (1, 3, 4), (1, 2, 3, 4, 5, 7, 8, 9, 11, 12)])
def test_parse_round_trip(days):
    assert parse(compact(D(*days)), (2026, 12)) == D(*days)


def test_parse_cross_month_and_errors():
    assert parse("30-31, Jan 1-2", (2026, 12)) == D(30, 31) + [date(2027, 1, 1), date(2027, 1, 2)]
    with pytest.raises(ValueError):
        parse("hello", (2026, 12))
    with pytest.raises(ValueError):
        parse("5-2", (2026, 12))


def _movie(mid, title, dates, imax=False, tc=2):
    return {"amc_movie_id": mid, "title": title, "dates": dates, "is_imax": imax,
            "theatre_count": tc, "movie_url": "https://www.amctheatres.com/movies/x"}


def test_duplicate_consolidation(tmp_path):
    s = LocalStore(tmp_path)
    s.add_to_tracker("JD", _movie(1, "Dune", D(1, 2), imax=True, tc=1))
    row = s.list_tracker()[0]
    assert row["notes"] == "IMAX; Only one theater"
    s.update_movie(row["id"], {"jonathan_purchased": True, "notes": "IMAX; seats G7-8"})
    s.add_to_tracker("Kevin", _movie(1, "Dune", D(2, 3)))
    s.add_to_tracker("Kevin", _movie(1, "Dune", D(3)))
    rows = s.list_tracker()
    assert len(rows) == 1
    r = rows[0]
    assert r["users"] == ["JD", "Kevin"]
    assert r["dates"] == D(1, 2, 3)
    assert r["jonathan_purchased"] is True and r["notes"] == "IMAX; seats G7-8"


def test_auto_notes(tmp_path):
    s = LocalStore(tmp_path)
    s.add_to_tracker("JD", _movie(1, "A", D(1), imax=True, tc=3))
    s.add_to_tracker("JD", _movie(2, "B", D(1), tc=1))
    s.add_to_tracker("JD", _movie(3, "C", D(1), tc=4))
    notes = {r["title"]: r["notes"] for r in s.list_tracker()}
    assert notes == {"A": "IMAX", "B": "Only one theater", "C": ""}


def test_history_keeps_five_per_user(tmp_path):
    s = LocalStore(tmp_path)
    theatres = amc.demo_theatres(2)
    res = amc.demo_scan(theatres, 10)
    ids = []
    for i in range(7):
        meta = {"run_at": "2026-11-{:02d}T12:00:00+00:00".format(i + 1), "zip": "60614",
                "theatre_count": 2, "days": 10, "theatres": theatres, "empty_days": 0}
        ids.append(s.save_run("jd", meta, res["movies"], snapshot.render("JD", meta, res["movies"])))
    s.save_run("kevin", {**meta, "run_at": "2026-11-20T00:00:00+00:00"}, res["movies"], None)
    jd = s.list_runs("jd")
    assert [r["id"] for r in jd] == ids[::-1][:5]
    assert len(s.list_runs("kevin")) == 1
    assert len(list((tmp_path / "screenshots").iterdir())) == 5
    meta0, movies0 = s.get_run(ids[-1])
    assert movies0 and movies0[0]["theatres"]  # frozen showtimes kept
    assert exports.run_xlsx("JD", meta0, movies0, s.screenshot(meta0["screenshot_path"]))[:2] == b"PK"
    assert b"MOVIE,THEATER" in exports.run_csv(meta0, movies0)


def test_tracker_exports(tmp_path):
    s = LocalStore(tmp_path)
    s.add_to_tracker("JD", _movie(1, "A", D(1, 2, 3)))
    s.add_to_tracker("Meagan", _movie(2, "B", [date(2027, 1, 4)]))
    rows = s.list_tracker()
    assert exports.tracker_xlsx(rows)[:2] == b"PK"
    csv_text = exports.tracker_csv(rows).decode("utf-8-sig")
    assert "December 2026,1-3,A,JD" in csv_text and "January 2027,4,B,Meagan" in csv_text


def test_build_results_from_api_shapes():
    t = [{"id": 1, "name": "AMC One"}, {"id": 2, "name": "AMC Two"}]
    st = lambda mid, name, when, pf="": {"movieId": mid, "movieName": name,
                                          "showDateTimeLocal": when, "premiumFormat": pf}
    res = amc.build_results(t, ["2026-12-01", "2026-12-02"], [
        (t[0], "2026-12-01", [st(5, "X", "2026-12-01T19:30:00", "IMAX"), st(5, "X", "2026-12-01T13:00:00")]),
        (t[1], "2026-12-01", [st(5, "X", "2026-12-01T20:00:00")]),
        (t[0], "2026-12-02", []), (t[1], "2026-12-02", []),
    ])
    m = res["movies"][0]
    assert res["empty_days"] == 1 and m["is_imax"] and m["theatre_count"] == 2
    assert [s["time"] for s in m["theatres"]["1"]["dates"]["2026-12-01"]] == ["1:00 PM", "7:30 PM"]
