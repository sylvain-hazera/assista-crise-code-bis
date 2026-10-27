"""Une fiche par établissement, partagée — et ce que chaque collectivité en fait à part.

Jusqu'ici chaque institution avait SA copie : si une mairie importait son collège, le conseil
départemental ne le voyait pas, et inversement. Deux inventaires du même territoire, chacun se
dégradant de son côté. Désormais `SiteSensible` est la fiche commune (nom, adresse, coordonnées,
attributs, corrections comprises) et `SuiviSiteSensible` porte ce qui appartient à une
collectivité : sa décision, son commentaire, sa convention, son point opérationnel.

L'ordre des opérations compte : la reprise des décisions existantes doit tourner APRÈS la
création du suivi et l'ajout d'`institution_origine`, mais AVANT la suppression des colonnes
qu'elle lit. La contrainte d'unicité nouvelle vient en dernier, après le dédoublonnage.

Irréversible par conception : revenir en arrière demanderait de choisir, pour chaque fiche
partagée, à quelle collectivité l'attribuer — une information qui n'existe plus."""

import core.file_crypto
import core.models
import core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


def reprendre_les_decisions(apps, schema_editor):
    """Transfère l'appartenance et les décisions vers le nouveau découpage."""
    SiteSensible = apps.get_model("core", "SiteSensible")
    SuiviSiteSensible = apps.get_model("core", "SuiviSiteSensible")

    # 1. L'institution devient une simple trace d'origine.
    SiteSensible.objects.update(institution_origine=models.F("institution"))

    # 2. Une ligne de suivi pour chaque fiche qui portait une décision ou un engagement. Rien
    #    pour les autres : l'absence de suivi EST l'état « à vérifier ».
    suivis = []
    for site in SiteSensible.objects.exclude(institution=None).iterator():
        porte_quelque_chose = (
            site.statut != "PROPOSE" or site.commentaire or site.valide_par_id
            or site.point_operationnel_id or site.convention_existe
            or site.convention_numero or site.convention_document
        )
        if not porte_quelque_chose:
            continue
        suivis.append(SuiviSiteSensible(
            site=site,
            institution_id=site.institution_id,
            environment=site.environment,
            statut=site.statut,
            commentaire=site.commentaire,
            valide_par_id=site.valide_par_id,
            convention_existe=site.convention_existe,
            convention_numero=site.convention_numero,
            convention_date_signature=site.convention_date_signature,
            convention_echeance=site.convention_echeance,
            convention_document=site.convention_document,
            point_operationnel_id=site.point_operationnel_id,
        ))
    SuiviSiteSensible.objects.bulk_create(suivis, batch_size=500)

    # 3. Dédoublonnage : la nouvelle contrainte d'unicité ne tolère plus qu'un établissement
    #    existe deux fois. Aucun doublon en production au moment d'écrire ceci, mais une base
    #    où deux collectivités auraient importé le même site doit migrer sans échouer : on garde
    #    la fiche la plus ancienne et on y rattache les suivis des autres.
    vus = {}
    for site in SiteSensible.objects.exclude(source_id="").order_by("date_import").iterator():
        cle = (site.source, site.source_id, site.environment)
        gardee = vus.get(cle)
        if gardee is None:
            vus[cle] = site.id
            continue
        SuiviSiteSensible.objects.filter(site_id=site.id).update(site_id=gardee)
        site.delete()


def irreversible(apps, schema_editor):
    raise IrreversibleError(
        "Migration irréversible par conception : une fiche partagée n'a plus d'institution "
        "propriétaire. Restaurer depuis la sauvegarde prise juste avant."
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0222_sites_sensibles_echelon_competence'),
    ]

    operations = [
        # ── 1. Le suivi, et ses clés ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='SuiviSiteSensible',
            fields=[
                ('environment', models.CharField(choices=[('PROD', 'Production'), ('DEMO', 'Démonstration')], default='PROD', max_length=4)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('statut', models.CharField(choices=[('PROPOSE', 'Proposé — à vérifier'), ('RETENU', 'Retenu au plan de sauvegarde'), ('ECARTE', 'Écarté')], default='PROPOSE', max_length=10)),
                ('commentaire', models.TextField(blank=True, null=True)),
                ('convention_existe', models.BooleanField(default=False)),
                ('convention_numero', models.CharField(blank=True, max_length=100, null=True)),
                ('convention_date_signature', models.DateField(blank=True, null=True)),
                ('convention_echeance', models.DateField(blank=True, null=True)),
                ('convention_document', models.FileField(blank=True, max_length=255, null=True, storage=core.file_crypto.get_encrypted_file_storage, upload_to=core.models.secure_document_path, validators=[core.validators.validate_convention_file])),
                ('modifie_le', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(
            model_name='suivisitesensible',
            name='institution',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='suivis_sites_sensibles', to='core.institution'),
        ),
        migrations.AddField(
            model_name='suivisitesensible',
            name='point_operationnel',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='suivis_sites_sensibles', to='core.pointoperationnel'),
        ),
        migrations.AddField(
            model_name='suivisitesensible',
            name='site',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='suivis', to='core.sitesensible'),
        ),
        migrations.AddField(
            model_name='suivisitesensible',
            name='valide_par',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sites_sensibles_valides', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddConstraint(
            model_name='suivisitesensible',
            constraint=models.UniqueConstraint(fields=('site', 'institution', 'environment'), name='uq_suivi_site_sensible_institution'),
        ),

        # ── 2. Les nouveaux champs de la fiche ──────────────────────────────────────────────
        migrations.AddField(
            model_name='sitesensible',
            name='corrige_le',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='sitesensible',
            name='corrige_par',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sites_sensibles_corriges', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='sitesensible',
            name='institution_origine',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sites_sensibles_importes', to='core.institution'),
        ),

        # ── 3. L'ancienne unicité tombe avant que `institution` disparaisse ─────────────────
        migrations.RemoveConstraint(
            model_name='sitesensible',
            name='uq_site_sensible_institution_source_id',
        ),

        # ── 4. Reprise des données, pendant que les deux formes coexistent ──────────────────
        migrations.RunPython(reprendre_les_decisions, irreversible),

        # ── 5. Ce qui a déménagé quitte la fiche ────────────────────────────────────────────
        migrations.RemoveField(model_name='sitesensible', name='commentaire'),
        migrations.RemoveField(model_name='sitesensible', name='convention_date_signature'),
        migrations.RemoveField(model_name='sitesensible', name='convention_document'),
        migrations.RemoveField(model_name='sitesensible', name='convention_echeance'),
        migrations.RemoveField(model_name='sitesensible', name='convention_existe'),
        migrations.RemoveField(model_name='sitesensible', name='convention_numero'),
        migrations.RemoveField(model_name='sitesensible', name='institution'),
        migrations.RemoveField(model_name='sitesensible', name='point_operationnel'),
        migrations.RemoveField(model_name='sitesensible', name='statut'),
        migrations.RemoveField(model_name='sitesensible', name='valide_par'),

        # ── 6. Une fiche par établissement, une fois le dédoublonnage fait ──────────────────
        migrations.AddConstraint(
            model_name='sitesensible',
            constraint=models.UniqueConstraint(condition=models.Q(('source_id', ''), _negated=True), fields=('source', 'source_id', 'environment'), name='uq_site_sensible_source_id'),
        ),
    ]
