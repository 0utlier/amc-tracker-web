"""Reads settings from Streamlit secrets (on the host) or environment variables."""
from __future__ import annotations

import os

import streamlit as st


def secret(name: str, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass  # no secrets.toml — fine when running locally
    return os.environ.get(name, default)


def truthy(v) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on"}
