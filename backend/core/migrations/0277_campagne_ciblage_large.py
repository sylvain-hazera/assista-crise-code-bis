from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0276_application_mobile_notifications"),
    ]

    operations = [
        migrations.AddField(
            model_name="campagnedisponibilite",
            name="ciblage_large",
            field=models.BooleanField(
                default=False,
                help_text="Inclut aussi les membres dont le dossier n'est pas à jour dans l'outil : "
                          "les critères n'écartent alors que ceux dont on sait qu'ils n'y répondent "
                          "pas.",
            ),
        ),
    ]
