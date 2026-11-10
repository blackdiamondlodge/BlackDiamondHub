from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('feedback', '0003_feedback_page_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='feedback',
            name='stay',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
    ]
