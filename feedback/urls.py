# feedback/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('submit-feedback/', views.submit_feedback, name='submit_feedback'),
    path('', views.view_feedback, name='view_feedback'),
    path('list/', views.feedback_list, name='feedback_list'),
    path('bulk_action/', views.bulk_feedback_action, name='bulk_feedback_action'),
    path('get_unread_feedback_count/', views.get_unread_feedback_count, name='get_unread_feedback_count'),
]
