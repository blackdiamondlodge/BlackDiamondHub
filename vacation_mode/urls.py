from django.urls import path
from . import views

urlpatterns = [
    path('', views.vacation_mode_view, name='vacation_mode'),
    path('api/execute/', views.execute_view, name='vacation_mode_execute'),
    path('api/status/<str:run_id>/', views.status_view, name='vacation_mode_status'),
    path('api/state/', views.state_view, name='vacation_mode_state'),
    path('api/modes/status/', views.bdl_modes_status_view, name='bdl_modes_status'),
    path('api/modes/command/', views.bdl_modes_command_view, name='bdl_modes_command'),
]
