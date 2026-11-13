from django.db import migrations


def clamp(seconds):
    """A saved "Change every" pulled into the 15 - 90 s range."""
    try:
        return min(90, max(15, int(seconds)))
    except (TypeError, ValueError):
        return None


def forwards(apps, schema_editor):
    AppSetting = apps.get_model("hub_settings", "AppSetting")
    for row in AppSetting.objects.filter(app_id="display", key="rotate_seconds"):
        seconds = clamp(row.value)
        if seconds is None:
            row.delete()
        elif seconds != row.value:
            row.value = seconds
            row.save(update_fields=["value"])


class Migration(migrations.Migration):

    dependencies = [("display", "0003_rotate_seconds")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]