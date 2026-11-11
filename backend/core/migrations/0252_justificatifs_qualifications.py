"""Justificatifs des qualifications : dépôt par le membre, vérification par l'encadrement.

Avant, une qualification se saisissait à la main par le bureau, sur la foi d'une attestation vue
ailleurs : rien ne restait dans l'application, et une qualification « vérifiée » ne l'était que
dans le souvenir de celui qui l'avait saisie.

**Le fichier est protégé exactement comme une pièce d'identité** (voir PieceIdentiteReserve) :
chiffré au repos par `get_encrypted_file_storage` (core/file_crypto.py), rangé sous le préfixe
`documents/` que proxy/nginx.conf bloque, et jamais servi comme URL /media/ — seule l'action
`QualificationMembreViewSet.justificatif` le rend, après contrôle des droits et avec une trace
en main courante.

`statut` vaut DECLAREE par défaut, et le mot compte : tant que l'encadrement ne s'est pas
prononcé, la qualification est une affirmation de son titulaire. Les lignes existantes prennent
donc ce défaut — aucune n'est présumée vérifiée, ce qui serait exactement l'erreur à éviter.
"""

import core.file_crypto
import core.models
import core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0251_fiche_benevole'),
    ]

    operations = [
        migrations.AddField(
            model_name='qualificationmembre',
            name='justificatif',
            field=models.FileField(blank=True, help_text='Attestation, diplôme ou permis. Chiffré au repos, jamais accessible par URL directe.', max_length=255, null=True, storage=core.file_crypto.get_encrypted_file_storage, upload_to=core.models.secure_document_path, validators=[core.validators.validate_identity_document_file]),
        ),
        migrations.AddField(
            model_name='qualificationmembre',
            name='justificatif_depose_le',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='qualificationmembre',
            name='justificatif_nom',
            field=models.CharField(blank=True, help_text="Nom du fichier tel que déposé. Le nom réel est un UUID : sans cela, l'écran afficherait « a3f2…pdf » au lieu de « PSC1-2024.pdf ».", max_length=255),
        ),
        migrations.AddField(
            model_name='qualificationmembre',
            name='motif_refus',
            field=models.TextField(blank=True, help_text='Obligatoire au refus : le membre doit savoir quoi corriger pour redéposer.'),
        ),
        migrations.AddField(
            model_name='qualificationmembre',
            name='statut',
            field=models.CharField(choices=[('DECLAREE', 'Déclarée par le membre'), ('VERIFIEE', "Vérifiée par l'encadrement"), ('REFUSEE', 'Refusée')], default='DECLAREE', help_text="DÉCLARÉE tant que l'encadrement ne s'est pas prononcé. Une qualification déclarée n'est PAS une qualification vérifiée.", max_length=12),
        ),
        migrations.AddField(
            model_name='qualificationmembre',
            name='verifie_le',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='qualificationmembre',
            name='verifie_par',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='qualifications_verifiees', to=settings.AUTH_USER_MODEL),
        ),
    ]
