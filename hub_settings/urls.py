from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="hub_settings"),
    path("location/", views.location_settings, name="hub_settings_location"),
    path("location/search/", views.location_search, name="hub_settings_location_search"),
    path("home/", views.home_layout, name="hub_settings_home"),
    path("quick/", views.quick_actions, name="hub_settings_quick"),
    path("apps/", views.apps_overview, name="hub_settings_apps"),
    path("app/<str:app_id>/", views.app_settings, name="hub_settings_app"),
]
