"""Relecture avant envoi, et textes de messages réécrits par une institution.

`BrouillonEnvoi` retient un message au lieu de l'expédier, quand un membre d'une institution
écrit à un TIERS et que l'institution a activé la relecture. Aucun des 48 points d'envoi n'a
changé : la capture se fait dans `send_branded_mail` et la décision se déduit de la requête
(voir core/brouillons_envoi.py).

Le champ qui mérite attention : `liens_masques`. Le corps stocké porte `[LIEN_1]`, `[LIEN_2]`…
et ce champ chiffré garde la correspondance vers les vraies URL, jamais servie par l'API. Un
lien magique est un porteur d'identité, et le relecteur n'est pas forcément le titulaire du
compte concerné — un administrateur qui déclenche une réinitialisation de mot de passe pour
quelqu'un d'autre en est le cas réel.

`ModeleMessage` n'a pas de ligne par défaut : absente, le texte du catalogue s'applique. C'est
ce qui fait que rien ne change pour une institution qui ne personnalise pas, et qu'ajouter un
message au catalogue n'oblige personne à le réécrire.

Les deux tables naissent vides ; aucune reprise de données.
"""

import core.crypto_fields
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0248_configuration_envoi_institution'),
    ]

    operations = [
        migrations.AddField(
            model_name='configurationenvoiinstitution',
            name='relecture_avant_envoi',
            field=models.BooleanField(default=False, help_text="Ouvre une fenêtre de relecture quand un membre écrit à un tiers au nom de l'institution. L'action, elle, a déjà eu lieu : un brouillon jamais relu part automatiquement au bout de 24 h."),
        ),
        migrations.CreateModel(
            name='BrouillonEnvoi',
            fields=[
                ('environment', models.CharField(choices=[('PROD', 'Production'), ('DEMO', 'Démonstration')], default='PROD', max_length=4)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('canal', models.CharField(choices=[('EMAIL', 'Email'), ('SMS', 'SMS')], default='EMAIL', max_length=6)),
                ('statut', models.CharField(choices=[('A_RELIRE', 'À relire'), ('ENVOYE', 'Envoyé'), ('ABANDONNE', 'Abandonné'), ('EXPEDIE_AUTO', 'Expédié sans relecture (délai dépassé)')], default='A_RELIRE', max_length=14)),
                ('sujet', core.crypto_fields.EncryptedTextField(blank=True)),
                ('corps', core.crypto_fields.EncryptedTextField()),
                ('destinataires', core.crypto_fields.EncryptedJSONField(default=list)),
                ('reply_to', core.crypto_fields.EncryptedTextField(blank=True)),
                ('liens_masques', core.crypto_fields.EncryptedTextField(blank=True)),
                ('modifie_par_relecteur', models.BooleanField(default=False)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('date_traitement', models.DateTimeField(blank=True, null=True)),
                ('erreur', models.TextField(blank=True)),
                ('cree_par', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='brouillons_envoi_crees', to=settings.AUTH_USER_MODEL)),
                ('institution', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='brouillons_envoi', to='core.institution')),
                ('traite_par', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='brouillons_envoi_traites', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-date_creation'],
                'indexes': [models.Index(fields=['statut', 'date_creation'], name='core_brouil_statut_b01b85_idx')],
            },
        ),
        migrations.CreateModel(
            name='ModeleMessage',
            fields=[
                ('environment', models.CharField(choices=[('PROD', 'Production'), ('DEMO', 'Démonstration')], default='PROD', max_length=4)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('cle', models.CharField(max_length=60)),
                ('sujet', models.TextField(blank=True)),
                ('corps', models.TextField(blank=True)),
                ('actif', models.BooleanField(default=True, help_text='Faux = revenir au texte par défaut sans perdre la version réécrite.')),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('date_modification', models.DateTimeField(auto_now=True)),
                ('institution', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='modeles_messages', to='core.institution')),
                ('modifie_par', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='modeles_messages_modifies', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('institution', 'cle'), name='unique_modele_message_institution_cle')],
            },
        ),
    ]
