"""Un seul moteur de disponibilité : `FicheBenevole.disponibilite` devient
`frequence_engagement`.

Demande de Sylvain du 11/11/2026 : « tu as généré un nouveau modèle de disponibilité alors que
j'ai celui des personnes ressources. Peux tu utiliser qu'un seul moteur ? Celui des personnes
ressources, c'est celui qui est appelé quand on constitue une équipe. »

Il a raison, et le défaut était plus qu'un doublon de vocabulaire : deux notions se
ressemblaient sans jamais se parler. La seule source de disponibilité est
`DisponibiliteOperationnelle`, que lit la grille de mobilisation.

**Un renommage (`RenameField`) et non une suppression**, parce que la valeur n'est pas du
bruit : elle vient du formulaire d'adhésion du partenaire et dit un volume annuel (« environ
10 jours par an »). La supprimer jetterait une information collectée auprès de plusieurs
centaines de personnes et impossible à reconstituer. Elle ne peut pas non plus être convertie
en déclarations datées : « 10 jours par an » ne dit rien du 5 novembre, et en déduire des dates
serait inventer des disponibilités.

`RenameField` préserve les données en base — PostgreSQL fait un `ALTER TABLE ... RENAME
COLUMN`, sans recopie ni perte, et réversible.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0253_lots_de_relecture'),
    ]

    operations = [
        migrations.RenameField(
            model_name='fichebenevole',
            old_name='disponibilite',
            new_name='frequence_engagement',
        ),
        migrations.AlterField(
            model_name='fichebenevole',
            name='frequence_engagement',
            field=models.CharField(
                blank=True, max_length=20,
                choices=[
                    ('OCCASIONNELLE', 'Occasionnelle (moins de 5 jours par an)'),
                    ('REGULIERE', 'Régulière (environ 10 jours par an)'),
                    ('FREQUENTE', 'Fréquente (plus de 10 jours par an)'),
                ],
                help_text="Volume d'engagement annoncé à l'adhésion. N'est pas une "
                          "disponibilité : les disponibilités datées vivent dans "
                          "DisponibiliteOperationnelle.",
            ),
        ),
    ]
