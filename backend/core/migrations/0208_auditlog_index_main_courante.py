from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # Index de la main courante (21/10/2026) : la table core_auditlog n'avait aucun index sur
    # date_action/environment/objet_id, chaque affichage de /admin/main-courante parcourait donc
    # les 2,5 M de lignes (523 Mo lus, ~1,2 s de réponse) et l'historique d'une fiche 550 ms.
    # Mesuré sur une copie de la table de production : 0,07 ms par page, 0 Mo lus.
    #
    # CONCURRENTLY (AddIndexConcurrently, atomic = False obligatoire) : un CREATE INDEX ordinaire
    # pose un verrou d'écriture le temps de la construction (~10 s ici) et ferait attendre toutes
    # les requêtes /api/, qui écrivent justement dans cette table via AuditTraceMiddleware. En
    # mode concurrent, la construction est plus lente mais ne bloque aucune écriture.
    # Rien d'autre que des index : aucune donnée touchée, aucune colonne modifiée.
    # Contrepartie du mode concurrent : une construction interrompue (redémarrage du conteneur
    # en pleine migration) laisse un index marqué INVALID, que Postgres n'utilise pas et qui
    # n'empêche rien d'autre. Le relancer après l'avoir supprimé :
    #   DROP INDEX IF EXISTS <nom> ;  puis rejouer la migration.
    # Prévoir environ une minute au total sur 2,5 M de lignes (5 index, ~560 Mo).
    atomic = False

    dependencies = [
        ("core", "0207_satellite_installation_automatique"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="auditlog",
            index=models.Index(fields=["environment", "-date_action"], name="auditlog_env_date_idx"),
        ),
        AddIndexConcurrently(
            model_name="auditlog",
            index=models.Index(fields=["environment", "action", "-date_action"], name="auditlog_env_action_idx"),
        ),
        AddIndexConcurrently(
            model_name="auditlog",
            index=models.Index(fields=["environment", "utilisateur", "-date_action"], name="auditlog_env_user_idx"),
        ),
        AddIndexConcurrently(
            model_name="auditlog",
            index=models.Index(fields=["environment", "institution", "-date_action"], name="auditlog_env_inst_idx"),
        ),
        AddIndexConcurrently(
            model_name="auditlog",
            index=models.Index(fields=["objet_type", "objet_id", "environment", "-date_action"], name="auditlog_objet_idx"),
        ),
    ]
