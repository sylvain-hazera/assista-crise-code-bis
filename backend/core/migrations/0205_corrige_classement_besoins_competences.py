from django.db import migrations

# Corrections de classement relevées le 20/10/2026 (validées avec l'utilisateur), même esprit
# que 0139_organise_besoins_competences : données réelles, par nom, sans effet si l'élément
# n'existe pas ou a déjà été corrigé.
#   - compétence « Pompage » rangée sous « Élagage / bûcheronnage » -> « Technique » ;
#   - compétence « Conducteur tracteur » rangée sous « Secours & sécurité » -> « Technique » ;
#   - besoin « Accompagnement administratif » classé matériel -> compétence (aide humaine,
#     comme le posait déjà 0139 avant une modification manuelle) ;
#   - catégorie de besoins « Hébergement & alimentation » -> « Accueil & alimentation » : trop
#     proche de son élément « Hébergement » (nom qui, lui, ne doit pas changer : il est
#     référencé par le code, ex. tableau de bord et notifications Hébergement).

COMPETENCE_PARENTS = [
    # (compétence, ancien parent, nouveau parent)
    ("Pompage", "Élagage / bûcheronnage", "Technique"),
    ("Conducteur tracteur", "Secours & sécurité", "Technique"),
]
BESOIN_NATURE = ("Accompagnement administratif", "MATERIEL", "COMPETENCE")
BESOIN_RENOMMAGE = ("Hébergement & alimentation", "Accueil & alimentation")


def _reparenter(Competence, nom, de, vers):
    competence = Competence.objects.filter(nom=nom, parent__nom=de).first()
    parent = Competence.objects.filter(nom=vers).first()
    if competence and parent:
        competence.parent = parent
        competence.save(update_fields=["parent"])


def _renommer(Besoin, de, vers):
    if not Besoin.objects.filter(nom=vers).exists():
        Besoin.objects.filter(nom=de).update(nom=vers)


def corriger(apps, schema_editor):
    Competence = apps.get_model("core", "Competence")
    Besoin = apps.get_model("core", "Besoin")
    for nom, de, vers in COMPETENCE_PARENTS:
        _reparenter(Competence, nom, de, vers)
    nom, de, vers = BESOIN_NATURE
    Besoin.objects.filter(nom=nom, nature=de).update(nature=vers)
    _renommer(Besoin, *BESOIN_RENOMMAGE)


def annuler(apps, schema_editor):
    Competence = apps.get_model("core", "Competence")
    Besoin = apps.get_model("core", "Besoin")
    for nom, de, vers in COMPETENCE_PARENTS:
        _reparenter(Competence, nom, vers, de)
    nom, de, vers = BESOIN_NATURE
    Besoin.objects.filter(nom=nom, nature=vers).update(nature=de)
    _renommer(Besoin, BESOIN_RENOMMAGE[1], BESOIN_RENOMMAGE[0])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0204_crisis_essai"),
    ]

    operations = [
        migrations.RunPython(corriger, annuler),
    ]
