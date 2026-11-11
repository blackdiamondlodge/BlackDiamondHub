from django.contrib import admin

from .models import AppSetting


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ("app_id", "key", "value", "updated_at", "updated_by")
    list_filter = ("app_id",)
    readonly_fields = ("updated_at", "updated_by")
