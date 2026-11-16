"""Retire de la main courante les copies en clair des entrées du journal de bord.

Chaque écriture au journal de bord laissait une trace `JOURNAL_BORD` dont le commentaire
recopiait les 200 premiers caractères de l'entrée, dans un champ qui n'est pas chiffré. Le
journal lui-même est chiffré depuis 0302 ; ces copies ne doivent pas lui survivre. La main
courante relit désormais l'entrée entière dans le journal (serializers.commentaire_de_main_courante).

Rien n'est perdu : le texte reste dans le journal. Le retour arrière ne remet pas les copies --
ce serait remettre en clair ce qu'on vient d'en retirer.
"""
from django.db import migrations

SEPARATEUR = ") : "


def retirer(apps, schema_editor):
    AuditLog = apps.get_model("core", "AuditLog")
    traces = (AuditLog.objects.filter(action__code="JOURNAL_BORD", commentaire__contains=SEPARATEUR)
              .only("pk", "commentaire").iterator(chunk_size=500))
    for trace in traces:
        # « Journal de bord (Mairie de X) : texte… » -> « Journal de bord (Mairie de X) »
        entete = trace.commentaire.split(SEPARATEUR, 1)[0] + ")"
        AuditLog.objects.filter(pk=trace.pk).update(commentaire=entete)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0302_chiffrer_journal_de_bord"),
    ]

    operations = [
        migrations.RunPython(retirer, migrations.RunPython.noop),
    ]
