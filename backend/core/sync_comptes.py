"""Copie locale, sur un satellite FULL, des comptes de son institution (SatelliteViewSet.comptes)
pour que chacun se connecte à l'instance locale avec ses identifiants habituels sans internet.

- L'institution est recopiée telle quelle (QuerySet : pas d'Institution.save(), qui interroge
  des services géographiques en ligne) ; son type est retrouvé par code, créé s'il manque.
- Un compte est créé ou mis à jour par id, mot de passe = hash reçu (jamais de clair). Le
  compte admin local du satellite et les comptes locaux d'une autre institution ne sont jamais
  touchés.
- Un compte de l'institution qui n'est plus dans la liste du central (parti, désactivé) est
  désactivé localement, pas supprimé : ses écritures locales gardent leur auteur.
"""
from django.db import IntegrityError, transaction

from .models import Institution, InstitutionType, User

CHAMPS_INSTITUTION = (
    "nom", "commune_code", "commune_nom", "epci_code", "departement_code", "region_code",
    "secteur_niveau_effectif", "secteur_nom", "environment",
)
CHAMPS_COMPTE = ("username", "email", "first_name", "last_name", "type")


@transaction.atomic
def appliquer_comptes(donnees: dict) -> dict:
    infos = donnees["institution"]
    type_institution, _ = InstitutionType.objects.get_or_create(
        code=infos["type_code"], defaults={"libelle": infos.get("type_libelle") or infos["type_code"]},
    )
    champs = {k: infos.get(k) for k in CHAMPS_INSTITUTION}
    champs["type"] = type_institution
    if Institution.objects.filter(pk=infos["id"]).exists():
        Institution.objects.filter(pk=infos["id"]).update(**champs)
    else:
        Institution.objects.bulk_create([Institution(id=infos["id"], **champs)])

    compteurs = {"crees": 0, "mis_a_jour": 0, "desactives": 0}
    recus = set()
    compteurs["ignores"] = 0
    for compte in donnees.get("comptes", []):
        recus.add(compte["id"])
        utilisateur = User.objects.filter(pk=compte["id"]).first()
        nouveau = utilisateur is None
        if nouveau:
            utilisateur = User(id=compte["id"])
        elif utilisateur.is_superuser:
            compteurs["ignores"] += 1   # jamais l'admin local
            continue
        for champ in CHAMPS_COMPTE:
            setattr(utilisateur, champ, compte.get(champ) or "")
        utilisateur.password = compte["password"]
        utilisateur.institution_id = infos["id"]
        utilisateur.is_active = True
        utilisateur.enabled = True
        utilisateur.is_staff = False
        try:
            with transaction.atomic():   # un email déjà pris localement ne bloque pas les autres
                utilisateur.save()
        except IntegrityError:
            compteurs["ignores"] += 1
            continue
        compteurs["crees" if nouveau else "mis_a_jour"] += 1

    compteurs["desactives"] = (
        User.objects.filter(institution_id=infos["id"], is_active=True, is_superuser=False)
        .exclude(pk__in=recus).update(is_active=False)
    )
    return compteurs
