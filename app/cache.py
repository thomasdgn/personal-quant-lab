"""Caches indexés sur les fichiers de configuration et de données."""
from functools import wraps

import streamlit as st

from app.data import PROJECT_ROOT
from src.provenance import project_revision


def project_cache(**options):
    def decorate(function):
        @st.cache_data(**options)
        def cached(function_identity, revision, *args, **kwargs):
            return function(*args, **kwargs)

        @wraps(function)
        def wrapper(*args, **kwargs):
            return cached(f"{function.__module__}.{function.__qualname__}", project_revision(PROJECT_ROOT), *args, **kwargs)

        wrapper.clear = cached.clear
        return wrapper
    return decorate
