from django.urls import path

from . import views

urlpatterns = [
    path("api/saver/", views.saver_api, name="display_saver_api"),
    path("settings/", views.settings_page, name="display_settings"),
]
