import django.contrib.postgres.indexes
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # Index des filtres ajoutés à la main courante le 21/10/2026 (voir AuditLog.Meta.indexes) :
    # même principe que 0208 -- CONCURRENTLY pour ne bloquer aucune écriture pendant la
    # construction, atomic = False obligatoire. Même procédure de reprise qu'en 0208 si une
    # construction est interrompue (index INVALID : DROP INDEX puis rejouer).
    atomic = False

    dependencies = [
        ("core", "0209_auditlog_tracabilite_consultations"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="auditlog",
            index=django.contrib.postgres.indexes.GinIndex(fields=["objets_ids"], name="auditlog_objets_gin"),
        ),
        AddIndexConcurrently(
            model_name="auditlog",
            index=models.Index(fields=["objet_id"], name="auditlog_objet_id_idx"),
        ),
        AddIndexConcurrently(
            model_name="auditlog",
            index=models.Index(fields=["environment", "crise", "-date_action"], name="auditlog_env_crise_idx"),
        ),
        AddIndexConcurrently(
            model_name="auditlog",
            index=models.Index(fields=["environment", "perimetre", "-date_action"], name="auditlog_env_perim_idx"),
        ),
        AddIndexConcurrently(
            model_name="auditlog",
            index=models.Index(fields=["environment", "adresse_ip", "-date_action"], name="auditlog_env_ip_idx"),
        ),
        AddIndexConcurrently(
            model_name="auditlog",
            index=models.Index(fields=["environment", "-date_action"], name="auditlog_humains_idx",
                               condition=models.Q(compte_systeme=False)),
        ),
        AddIndexConcurrently(
            model_name="auditlog",
            index=models.Index(fields=["environment", "-date_action"], name="auditlog_recherche_idx",
                               condition=models.Q(recherche__isnull=False)),
        ),
    ]
