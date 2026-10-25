"""Tartarus's overrides of CAPE's Django settings; settings.py imports this file last.

The backend uses CAPE's REST API (apiv2) and nothing else, so the process serves no UI, runs without
debug pages and answers only to the names it is reached by.
"""

import os

LOCAL_SETTINGS = True
from .settings import *  # noqa: E402, F403

DEBUG = False

ALLOWED_HOSTS = [
    host
    for host in ("cape", "cape-internal", "localhost", "127.0.0.1", os.environ.get("CAPE_INTERNAL_IP"))
    if host
]

ROOT_URLCONF = "web.tartarus_urls"

# CAPE's code tree is root-owned (F12); this directory is the one place its web process may write.
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "/var/lib/cape-web/siteauth.sqlite"}}
