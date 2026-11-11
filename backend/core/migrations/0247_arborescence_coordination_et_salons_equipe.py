"""Arborescence de coordination territoriale, et deux salons Matrix par équipe.

**Échelon et territoire sur `Team`** : conçus et validés le 28/10/2026, écrits ici. `Team`
avait déjà `equipe_parente` (arbre de profondeur libre) mais aucun territoire, donc rien ne
permettait de trier les équipes département → région → zone → national. Vides par défaut : la
grande majorité des équipes n'appartiennent à aucune hiérarchie, et leur poser un échelon les
rangerait de force.

**`membres_encadrement`** : l'encadrement est par ÉQUIPE et non par personne — la même personne
peut encadrer son département et n'être qu'intervenante ailleurs. Ni `leader` ni `regulateur`
(une seule personne chacun) ni `AffectationRoleOperationnel` (par institution) ne pouvaient le
porter.

**`SalonMatrixEquipe` passe de OneToOne à ForeignKey + type.** Le point délicat de cette
migration, et il est traité par l'ordre des opérations : `type` est ajouté AVANT que la
contrainte d'unicité sur `equipe` seule ne tombe, avec le défaut `INTERVENANTS`. Les salons
existants deviennent donc tous le salon « Intervenants » de leur équipe — le seul choix qui ne
détruise rien, puisque l'unique salon d'une équipe était déjà celui de l'équipe entière. Il
garde son `room_id`, son historique Synapse et ses membres ; aucun salon Matrix n'est recréé,
aucune conversation n'est perdue.

Le second salon (« Encadrement ») n'est PAS créé ici : un salon se provisionne quand l'équipe a
des membres (`TeamViewSet.provisionner_salon_matrix`, idempotent). Créer d'office le salon
d'encadrement de chaque équipe existante en poserait des dizaines de vides dans Element.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0246_prenom_demandeur_rattachement'),
    ]

    operations = [
        migrations.AddField(
            model_name='salonmatrixequipe',
            name='type',
            field=models.CharField(choices=[('INTERVENANTS', 'Intervenants'), ('ENCADREMENT', 'Encadrement')], default='INTERVENANTS', max_length=12),
        ),
        migrations.AddField(
            model_name='team',
            name='echelon',
            field=models.CharField(blank=True, choices=[('NATIONAL', 'Coordination nationale'), ('ZONE_DEFENSE', 'Coordination de zone de défense'), ('REGIONAL', 'Coordination régionale'), ('DEPARTEMENTAL', 'Coordination départementale'), ('COMMUNAL', 'Échelon communal')], default='', help_text="Vide pour une équipe opérationnelle ordinaire, qui n'appartient à aucune hiérarchie territoriale.", max_length=15),
        ),
        migrations.AddField(
            model_name='team',
            name='membres_encadrement',
            field=models.ManyToManyField(blank=True, help_text="Membres de cette équipe qui en forment l'encadrement. Un encadrant doit aussi être membre : l'encadrement est une qualité au sein de l'équipe, pas une appartenance de plus.", related_name='teams_encadrees', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='team',
            name='territoire_code',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='team',
            name='territoire_libelle',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AlterField(
            model_name='salonmatrixequipe',
            name='equipe',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='salons_matrix', to='core.team'),
        ),
        migrations.AddConstraint(
            model_name='salonmatrixequipe',
            constraint=models.UniqueConstraint(fields=('equipe', 'type'), name='unique_salon_matrix_equipe_type'),
        ),
    ]
