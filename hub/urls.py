from django.urls import path

from . import views

urlpatterns = [
    path("status/", views.home_status, name="hub_status"),
    path("shortcut/<slug:plugin>/<slug:shortcut>/", views.run_shortcut, name="hub_shortcut"),
]
