from django.db import migrations


def to_seconds(minutes):
    """A saved "Change every" in minutes, as seconds within the new 30 s - 10 min range."""
    try:
        seconds = int(minutes) * 60
    except (TypeError, ValueError):
        return None
    return min(600, max(30, seconds))


def forwards(apps, schema_editor):
    AppSetting = apps.get_model("hub_settings", "AppSetting")
    for row in AppSetting.objects.filter(app_id="display", key="rotate_minutes"):
        seconds = to_seconds(row.value)
        if seconds is not None:
            AppSetting.objects.update_or_create(app_id="display", key="rotate_seconds",
                                                defaults={"value": seconds})
        row.delete()


def backwards(apps, schema_editor):
    AppSetting = apps.get_model("hub_settings", "AppSetting")
    for row in AppSetting.objects.filter(app_id="display", key="rotate_seconds"):
        try:
            minutes = max(1, round(int(row.value) / 60))
        except (TypeError, ValueError):
            minutes = None
        if minutes is not None:
            AppSetting.objects.update_or_create(app_id="display", key="rotate_minutes",
                                                defaults={"value": minutes})
        row.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("display", "0002_saverphoto_taken_at"),
        ("hub_settings", "0002_app_state"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
