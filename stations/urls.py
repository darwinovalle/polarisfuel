from django.urls import path

from .views import stations_home, optimize_route, places_suggest

urlpatterns = [
    path("", stations_home, name="stations-home"),
    path("optimize/", optimize_route, name="stations-optimize"),
    path("suggest/", places_suggest, name="stations-suggest"),
]