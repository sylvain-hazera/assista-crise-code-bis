"""Identifiants d'envoi propres à une institution en marque blanche (email Brevo, SMS).

Lève la limite inscrite dans core/branding.py depuis l'origine : « compte SMTP unique
Assista-Crise en v1, reply_to est le seul levier de personnalisation de l'adresse ».

Modèle séparé d'`Institution` et non des champs de plus : le bloc de marque blanche sur
`Institution` porte en commentaire « en clair : informations publiques », et
`InstitutionSerializer` est servi largement. Un modèle à part garantit que la clé ne voyage
jamais par défaut — le projet a déjà payé cette leçon sur cinq endpoints de secrets mesh.

Les deux clés sont des EncryptedTextField : règle du projet, on ne stocke rien en clair.
Aucune reprise de données, la table naît vide.
"""

import core.crypto_fields
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0247_arborescence_coordination_et_salons_equipe'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfigurationEnvoiInstitution',
            fields=[
                ('environment', models.CharField(choices=[('PROD', 'Production'), ('DEMO', 'Démonstration')], default='PROD', max_length=4)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('brevo_actif', models.BooleanField(default=False, help_text="Faux = les emails de cette institution partent du SMTP Assista-Crise, avec le texte de l'institution (signature, Reply-To).")),
                ('brevo_cle_api', core.crypto_fields.EncryptedTextField(blank=True, help_text="Clé API Brevo (commence par « xkeysib- »). Jamais relue par l'API.")),
                ('brevo_expediteur_email', models.EmailField(blank=True, help_text="Adresse expéditrice. Doit être un « sender » VÉRIFIÉ dans le compte Brevo, sinon l'API refuse l'envoi.", max_length=254)),
                ('brevo_expediteur_nom', models.CharField(blank=True, help_text="Nom affiché de l'expéditeur. Vide = nom_affichage de l'institution. 70 caractères maximum (limite Brevo).", max_length=70)),
                ('fournisseur_sms', models.CharField(blank=True, help_text='Identifiant du fournisseur SMS (voir core/envoi_sms.py). Vide = aucun envoi de SMS pour cette institution.', max_length=30)),
                ('sms_cle_api', core.crypto_fields.EncryptedTextField(blank=True, help_text="Jamais relue par l'API.")),
                ('sms_expediteur', models.CharField(blank=True, help_text="Nom ou numéro d'expéditeur présenté au destinataire, selon ce que le fournisseur autorise.", max_length=30)),
                ('dernier_envoi_email_le', models.DateTimeField(blank=True, null=True)),
                ('derniere_erreur_email', models.TextField(blank=True)),
                ('dernier_envoi_sms_le', models.DateTimeField(blank=True, null=True)),
                ('derniere_erreur_sms', models.TextField(blank=True)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('date_modification', models.DateTimeField(auto_now=True)),
                ('institution', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='configuration_envoi', to='core.institution')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
