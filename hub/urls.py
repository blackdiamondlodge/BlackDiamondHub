from django.urls import path

from . import views

urlpatterns = [
    path("status/", views.home_status, name="hub_status"),
    path("shortcut/<slug:plugin>/<slug:shortcut>/", views.run_shortcut, name="hub_shortcut"),
    path("alerts/test/", views.alert_test, name="hub_alert_test"),
    path("alerts/sample/", views.alert_sample, name="hub_alert_sample"),
    path("events/hook/<slug:source>/<path:topic>", views.event_hook, name="hub_event_hook"),
]
