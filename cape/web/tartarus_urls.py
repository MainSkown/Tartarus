"""The routes Tartarus serves: CAPE's REST API. CAPE's own `web.urls` adds its UI, file downloads and admin."""

from apiv2 import urls as apiv2
from django.urls import include, re_path

urlpatterns = [re_path(r"^apiv2/", include(apiv2))]
