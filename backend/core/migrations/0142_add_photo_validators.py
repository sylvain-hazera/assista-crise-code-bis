from django.db import migrations, models

import core.models
import core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0141_institutiontype_est_public'),
    ]

    operations = [
        migrations.AlterField(
            model_name='crisis',
            name='photo',
            field=models.ImageField(
                blank=True, max_length=255, null=True,
                upload_to=core.models.secure_crisis_photo_path,
                validators=[core.validators.validate_image_file],
            ),
        ),
        migrations.AlterField(
            model_name='recherchepersonne',
            name='photo',
            field=models.ImageField(
                blank=True, max_length=255, null=True,
                upload_to=core.models.secure_recherche_personne_photo_path,
                validators=[core.validators.validate_image_file],
            ),
        ),
    ]
