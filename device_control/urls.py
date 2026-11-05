from django.urls import path
from . import views

urlpatterns = [
    path('', views.device_control_view, name='device_control'),
    path('api/states/', views.device_control_states, name='device_control_states'),
    path('api/action/', views.device_control_action, name='device_control_action'),
    path('api/fireplace/states/', views.device_control_fireplace_states, name='device_control_fireplace_states'),
    path('api/fireplace/action/', views.device_control_fireplace_action, name='device_control_fireplace_action'),
    path('api/fireplace/card.js', views.device_control_fireplace_card, name='device_control_fireplace_card'),
    path('api/gemstone/states/', views.device_control_gemstone_states, name='device_control_gemstone_states'),
    path('api/gemstone/action/', views.device_control_gemstone_action, name='device_control_gemstone_action'),
]
