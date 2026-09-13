import django.contrib.gis.db.models.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0147_relais_pubkey_unique'),
    ]

    operations = [
        migrations.AddField(
            model_name='compagnonmeshcore',
            name='location',
            field=django.contrib.gis.db.models.fields.PointField(blank=True, null=True, srid=4326),
        ),
    ]
