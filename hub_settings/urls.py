from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="hub_settings"),
    path("home/", views.home_layout, name="hub_settings_home"),
    path("apps/", views.apps_overview, name="hub_settings_apps"),
    path("app/<str:app_id>/", views.app_settings, name="hub_settings_app"),
]
