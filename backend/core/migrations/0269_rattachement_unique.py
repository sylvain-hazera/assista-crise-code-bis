"""Dédoublonne les rattachements. La contrainte est posée par 0271, et c'est OBLIGATOIRE.

**Pourquoi deux migrations et pas une.** La première version faisait le `RunPython` puis
l'`AddConstraint` dans la même migration, donc dans la même transaction. PostgreSQL a refusé :

    cannot ALTER TABLE "core_contactinstitution" because it has pending trigger events

Les `DELETE` du dédoublonnage laissent des événements de déclencheur en attente (contraintes de
clé étrangère différées), et un `ALTER TABLE` est interdit tant qu'ils ne sont pas vidés. Django
ouvrant une transaction par migration, séparer les deux suffit : les suppressions sont validées
avant que la contrainte ne soit ajoutée.

**Ce que les tests ne pouvaient pas voir** : la base de test ne contient aucun doublon, donc le
`RunPython` ne supprimait rien, donc aucun déclencheur en attente. La suite complète passait au
vert pendant que la production tombait. Toute migration qui modifie des données PUIS le schéma
d'une même table doit être scindée, sans attendre qu'un test le prouve.

Un même couple (personne, institution) pouvait exister plusieurs fois : rien ne l'interdisait,
et il y en avait 4 en production. Conséquences silencieuses — un effectif faux, une personne
listée deux fois dans un annuaire, et chaque lecture obligée de se protéger (voir
`institution_attachment._get_or_create_contact_institution`, écrit après un
MultipleObjectsReturned constaté le 02/10/2026).

**Ne touche pas à la multi-appartenance** : une personne à la fois dans une mairie et dans une
association a deux lignes, avec deux institutions différentes. Seule la répétition de la MÊME
paire est fusionnée.

La fusion conserve la ligne la plus ancienne (elle porte la date d'adhésion réelle) et lui
reporte ce que les autres avaient de plus : un rattachement actif l'emporte sur un inactif, le
bureau l'emporte sur le simple membre, et une fonction renseignée sur une fonction vide. Garder
la plus récente aurait fait perdre l'ancienneté ; supprimer sans reporter aurait pu retirer le
bureau à quelqu'un qui l'avait.
"""
from django.db import migrations, models


def fusionner_doublons(apps, schema_editor):
    ContactInstitution = apps.get_model("core", "ContactInstitution")

    cles = (ContactInstitution.objects
            .values("institution_id", "utilisateur_id", "environment")
            .annotate(nombre=models.Count("id"))
            .filter(nombre__gt=1))

    for cle in cles:
        lignes = list(ContactInstitution.objects.filter(
            institution_id=cle["institution_id"],
            utilisateur_id=cle["utilisateur_id"],
            environment=cle["environment"],
        ).order_by("date_creation", "id"))
        gardee, doublons = lignes[0], lignes[1:]

        champs = []
        if not gardee.actif and any(d.actif for d in doublons):
            gardee.actif = True
            champs.append("actif")
        if not gardee.membre_bureau and any(d.membre_bureau for d in doublons):
            gardee.membre_bureau = True
            champs.append("membre_bureau")
        if not gardee.contact_principal and any(d.contact_principal for d in doublons):
            gardee.contact_principal = True
            champs.append("contact_principal")
        if not (gardee.fonction or "").strip():
            fonction = next((d.fonction for d in doublons if (d.fonction or "").strip()), "")
            if fonction:
                gardee.fonction = fonction
                champs.append("fonction")
        if gardee.zone_id is None:
            zone = next((d.zone_id for d in doublons if d.zone_id), None)
            if zone:
                gardee.zone_id = zone
                champs.append("zone")
        if champs:
            gardee.save(update_fields=champs)

        ContactInstitution.objects.filter(id__in=[d.id for d in doublons]).delete()


def ne_rien_defaire(apps, schema_editor):
    """Irréversible, et c'est assumé : on ne recrée pas des doublons supprimés à dessein."""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0268_salon_annonces"),
    ]

    operations = [
        # Données SEULEMENT. La contrainte est dans 0271 : voir le docstring du module.
        migrations.RunPython(fusionner_doublons, ne_rien_defaire),
    ]
