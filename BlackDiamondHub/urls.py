"""
URL configuration for BlackDiamondHub project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.contrib.auth import views as auth_views
from django.views.static import serve as serve_media

from . import views
from hub import views as hub_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', views.landing_page, name='landing_page'),
    path('og-image.png', hub_views.og_image, name='og_image'),
    path('hub/api/', include('hub.urls')),
    path('auth/', include('social_django.urls', namespace='social')),
]

# Hub apps are mounted from their PluginSpec (see settings.HUB_PLUGINS).
urlpatterns += [
    path(spec.prefix, include(spec.urls))
    for spec in settings.HUB_PLUGINS
    if spec.urls
]

# Uploaded files (inventory photos). Served by Django in production too:
# there is no separate web server in front of the app.
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve_media, {'document_root': settings.MEDIA_ROOT}),
]