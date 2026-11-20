from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0357_doppler_polarimetrie"),
    ]

    operations = [
        migrations.AddField(
            model_name="celluleorage",
            name="suivi",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
