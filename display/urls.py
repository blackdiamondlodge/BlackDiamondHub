from django.urls import path

from . import views

urlpatterns = [
    path("api/saver/", views.saver_api, name="display_saver_api"),
    path("api/schedule/", views.schedule_api, name="display_schedule_api"),
    path("api/heartbeat/", views.heartbeat, name="display_heartbeat"),
    path("api/heartbeats/", views.heartbeats_api, name="display_heartbeats"),
    path("settings/", views.settings_page, name="display_settings"),
    path("settings/photos/", views.photo_list, name="display_photos"),
    path("settings/photos/add/", views.photo_add, name="display_photo_add"),
    path("settings/photos/link/", views.link_create, name="display_upload_link"),
    path("settings/photos/<int:photo_id>/", views.photo_update, name="display_photo_update"),
    path("settings/photos/<int:photo_id>/delete/", views.photo_delete, name="display_photo_delete"),
    path("upload/<str:key>/", views.upload_page, name="display_upload"),
    path("upload/<str:key>/photo/", views.upload_photo, name="display_upload_photo"),
]
