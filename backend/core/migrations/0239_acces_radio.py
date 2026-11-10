"""Droit d'accès au domaine radio (voir core/acces_radio.py).

Aucune donnée à reprendre : le niveau se DÉDUIT du matériel déjà enregistré (nœud personnel
actif, passerelle de l'institution) et du rôle. Cette table ne porte que les droits accordés
nominativement, qui n'existaient pas avant."""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0238_reglages_noeuds'),
    ]

    operations = [
        migrations.CreateModel(
            name='DemandeAccesRadio',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('niveau_demande', models.CharField(choices=[('AUCUN', 'Aucun accès radio'), ('OPERATEUR', 'Opérateur radio (ses propres nœuds)'), ('ADMINISTRATEUR', 'Administration radio complète')], default='OPERATEUR', max_length=14)),
                ('motif', models.TextField(help_text="Ce que le demandeur détient ou exploite comme matériel radio, et pour quoi faire -- la seule pièce du dossier.")),
                ('statut', models.CharField(choices=[('EN_ATTENTE', "En attente d'instruction"), ('ACCORDEE', 'Accordée'), ('REFUSEE', 'Refusée'), ('RETIREE', 'Retirée')], default='EN_ATTENTE', max_length=12)),
                ('niveau_accorde', models.CharField(blank=True, choices=[('AUCUN', 'Aucun accès radio'), ('OPERATEUR', 'Opérateur radio (ses propres nœuds)'), ('ADMINISTRATEUR', 'Administration radio complète')], help_text="Renseigné à l'octroi. Peut être inférieur au niveau demandé : accorder OPERATEUR à qui demandait l'administration complète est une réponse légitime, pas un refus.", max_length=14, null=True)),
                ('commentaire_decision', models.TextField(blank=True)),
                ('date_demande', models.DateTimeField(auto_now_add=True)),
                ('date_decision', models.DateTimeField(blank=True, null=True)),
                ('instruite_par', models.ForeignKey(blank=True, help_text='SET_NULL et non PROTECT : le droit reste valide si le compte instructeur est supprimé, contrairement à une désignation nominative.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='demandes_acces_radio_instruites', to=settings.AUTH_USER_MODEL)),
                ('utilisateur', models.ForeignKey(help_text="Le demandeur. Pas forcément un compte institutionnel : un bénévole qui porte un nœud a besoin de le régler.", on_delete=django.db.models.deletion.CASCADE, related_name='demandes_acces_radio', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(
            model_name='demandeaccesradio',
            index=models.Index(fields=['utilisateur', 'statut'], name='core_demand_utilisa_fe43d7_idx'),
        ),
        migrations.AddIndex(
            model_name='demandeaccesradio',
            index=models.Index(fields=['-date_demande'], name='core_demand_date_de_ba5296_idx'),
        ),
    ]
