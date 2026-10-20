from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0203_pagination_signalements_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='crisis',
            name='essai',
            field=models.BooleanField(default=False),
        ),
    ]
