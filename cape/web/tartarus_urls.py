"""The routes Tartarus serves: CAPE's REST API. CAPE's own `web.urls` adds its UI, file downloads and admin."""

from apiv2 import urls as apiv2
from django.urls import include, path, re_path
from django.views.generic import RedirectView

urlpatterns = [
    path("apiv2/", RedirectView.as_view(url="/apiv2/cuckoo/status/", permanent=False)),
    re_path(r"^apiv2/", include(apiv2)),
]
