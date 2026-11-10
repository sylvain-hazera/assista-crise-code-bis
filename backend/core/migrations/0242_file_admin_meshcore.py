"""File des tâches d'administration MeshCore (voir TacheAdminMeshCore).

Table neuve, rien à reprendre. Elle rend vivante la réclamation de répéteur posée par 0241 :
c'est par elle que passe la vérification du mot de passe ou de l'ACL."""

import core.crypto_fields
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0241_reclamation_repeteur_meshcore'),
    ]

    operations = [
        migrations.CreateModel(
            name='TacheAdminMeshCore',
            fields=[
                ('environment', models.CharField(choices=[('PROD', 'Production'), ('DEMO', 'Démonstration')], default='PROD', max_length=4)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('pubkey_cible', models.CharField(help_text='Clé publique du répéteur visé. Jamais vide, contrairement à Meshtastic : le companion local se pilote par CommandeMeshCore, pas par cette file.', max_length=64)),
                ('type_tache', models.CharField(choices=[('VERIFIER_ACCES', "Vérifier qu'on peut administrer ce nœud"), ('LIRE_STATUT', 'Lire le statut du répéteur'), ('LIRE_VOISINS', 'Lire la liste des voisins entendus'), ('LIRE_REGIONS', 'Lire les portées déclarées'), ('LIRE_TELEMETRIE', 'Lire la télémétrie'), ('RADIO_TEMPORAIRE', 'Essayer des paramètres radio, avec retour automatique'), ('DEFINIR_REGLAGE', 'Modifier un réglage (set)'), ('ANNONCER', 'Déclencher une annonce (advert)'), ('REDEMARRER', 'Redémarrer le répéteur')], max_length=18)),
                ('parametres', models.JSONField(blank=True, null=True)),
                ('statut', models.CharField(choices=[('EN_ATTENTE', 'En attente'), ('EN_COURS', 'En cours'), ('TERMINEE', 'Terminée'), ('ECHEC', 'Échec')], default='EN_ATTENTE', help_text='Mêmes états que la file Meshtastic : en avoir deux jeux pour une mécanique identique ne ferait que créer des divergences.', max_length=12)),
                ('tentatives', models.PositiveSmallIntegerField(default=0)),
                ('reponse', core.crypto_fields.EncryptedTextField(blank=True, null=True)),
                ('erreur', models.TextField(blank=True, null=True)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('date_prise', models.DateTimeField(blank=True, null=True)),
                ('date_reponse', models.DateTimeField(blank=True, null=True)),
                ('compagnon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='taches_admin', to='core.compagnonmeshcore')),
                ('demande_par', models.ForeignKey(blank=True, help_text="Qui a demandé l'opération — une écriture sur un relais doit être imputable.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='taches_admin_meshcore', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [models.Index(fields=['statut', 'compagnon'], name='core_tachea_statut_f703da_idx'), models.Index(fields=['-date_creation'], name='core_tachea_date_cr_aead1e_idx'), models.Index(fields=['pubkey_cible'], name='core_tachea_pubkey__6a7d8f_idx')],
            },
        ),
    ]
