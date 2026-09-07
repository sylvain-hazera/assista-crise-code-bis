from django.db import migrations, models


def backfill_journal_crise(apps, schema_editor):
    """Rattache chaque entrée de journal existante (créée avant que `crise` existe, voir 0119)
    à la crise la plus plausible : celle sur laquelle l'institution était impliquée
    (ImplicationInstitution) au moment de l'entrée — implication déjà créée
    (date_creation <= entrée) et crise encore ouverte à ce moment (end_date NULL ou
    postérieure à l'entrée). Ambigu (plusieurs correspondances) ou aucune correspondance
    temporelle : repli sur la dernière implication connue de l'institution (log explicite
    dans les deux cas, imprimé pendant `manage.py migrate`). Cas résiduel (institution sans
    AUCUNE ImplicationInstitution) : laissé à None, à traiter manuellement avant la migration
    suivante (0121, qui rend `crise` NOT NULL et échoue explicitement s'il reste des lignes
    non résolues) — non atteignable en pratique au moment de cette migration (0 ligne
    JournalCollectivite en base de prod)."""
    JournalCollectivite = apps.get_model("core", "JournalCollectivite")
    ImplicationInstitution = apps.get_model("core", "ImplicationInstitution")

    entrees = JournalCollectivite.objects.filter(crise__isnull=True).select_related("institution")
    a_mettre_a_jour = []
    for entree in entrees:
        candidates = list(
            ImplicationInstitution.objects.filter(
                institution=entree.institution,
                date_creation__lte=entree.date_creation,
            ).filter(
                models.Q(crise__end_date__isnull=True) | models.Q(crise__end_date__gte=entree.date_creation)
            ).select_related("crise")
        )
        derniere_implication = (
            ImplicationInstitution.objects.filter(institution=entree.institution)
            .order_by("-date_creation").select_related("crise").first()
        )

        if len(candidates) == 1:
            entree.crise = candidates[0].crise
        elif len(candidates) > 1:
            print(
                f"[backfill_journal_crise] Ambigu pour l'entrée {entree.id} "
                f"(institution {entree.institution_id}) : {len(candidates)} implications "
                f"correspondantes — repli sur la dernière implication connue."
            )
            entree.crise = derniere_implication.crise if derniere_implication else None
        else:
            if derniere_implication:
                print(
                    f"[backfill_journal_crise] Aucune correspondance temporelle pour l'entrée "
                    f"{entree.id} (institution {entree.institution_id}) — repli sur la dernière "
                    f"implication connue (crise {derniere_implication.crise_id})."
                )
                entree.crise = derniere_implication.crise
            else:
                print(
                    f"[backfill_journal_crise] AUCUNE ImplicationInstitution pour l'institution "
                    f"{entree.institution_id} (entrée {entree.id}) — laissé sans crise, à "
                    f"rattacher manuellement avant la migration suivante (crise NOT NULL)."
                )

        if entree.crise_id:
            a_mettre_a_jour.append(entree)

    JournalCollectivite.objects.bulk_update(a_mettre_a_jour, ["crise"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0119_journalcollectivite_crise'),
    ]

    operations = [
        migrations.RunPython(backfill_journal_crise, migrations.RunPython.noop),
    ]
