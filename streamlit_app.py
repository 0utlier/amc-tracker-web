"""
AMC Movie Tracker — shared website.

Each person has their own address: yoursite/jd, yoursite/meagan, yoursite/kevin.
Pages are built from the Users table on every load, so adding a row there adds
a new person — no code changes.
"""
import streamlit as st

st.set_page_config(page_title="AMC Tracker", page_icon="🎬", layout="wide",
                   initial_sidebar_state="collapsed")

from amcweb import ui  # noqa: E402  (set_page_config must run first)


def _make_page(user):
    slug = user["slug"]

    def page():
        ui.user_page(slug)

    page.__name__ = "user_{}".format(slug.replace("-", "_"))
    return st.Page(page, title=user["display_name"], icon="🍿", url_path=slug)


@st.cache_data(ttl=60, show_spinner=False)
def _user_list(kind):
    return [{"slug": u["slug"], "display_name": u["display_name"]} for u in ui.get_store().list_users()]


try:
    users = _user_list(ui.get_store().kind)
except Exception as e:
    st.error("Couldn't reach the database. Check SUPABASE_URL / SUPABASE_KEY in secrets.")
    st.exception(e)
    st.stop()

user_pages = [_make_page(u) for u in users]


def _landing():
    ui.landing(user_pages)


home = st.Page(_landing, title="AMC Tracker", icon="🎬", default=True)
st.navigation([home, *user_pages], position="hidden").run()
