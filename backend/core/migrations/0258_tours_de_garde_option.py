"""Les tours de garde deviennent une option explicite de la campagne.

Demande de Sylvain du 12/11/2026 : « dans la campagne de recrutement, tour de garde est une
option activable ».

La première version s'en remettait à `effectif_cible = 0` pour dire « pas de tours de garde » :
une décision d'organisation portée par un nombre laissé à zéro, que personne ne lit comme
telle dans un formulaire. Beaucoup de campagnes ne veulent d'ailleurs que recueillir des
disponibilités — « qui peut venir la semaine prochaine ? » n'appelle aucun tour de garde.

`default=False` : une campagne existante ou créée sans y penser **ne** génère pas de tours. Le
défaut va vers le moins d'effet, ce qui est le bon sens pour une option qui propose d'affecter
des gens.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0257_seed_audit_action_envoi_masse'),
    ]

    operations = [
        migrations.AddField(
            model_name='campagnedisponibilite',
            name='tours_de_garde',
            field=models.BooleanField(
                default=False,
                help_text='Active le découpage de la période en tours de garde et la '
                          "proposition d'affectations. Sans elle, la campagne recueille "
                          'seulement des disponibilités.',
            ),
        ),
        migrations.AlterField(
            model_name='campagnedisponibilite',
            name='effectif_cible',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Combien de personnes par créneau et par rotation. N'a de sens "
                          "qu'avec `tours_de_garde`.",
            ),
        ),
    ]
