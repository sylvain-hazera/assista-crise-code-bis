"""Reclassement « quoi + pour qui » (27/11/2026) : voir core/classement.py.

Données réelles, aucune lecture de champ chiffré : tout se fait par type et par champs en clair.
Comme 0139 : rien n'est semé sur une base vide. Chaque étape ne touche que ce qui existe déjà
(une base neuve reçoit ses types d'entrypoint.sh, qui passe après). Les anciens types et
besoins sont désactivés, jamais supprimés (clés étrangères en PROTECT). Le retour arrière passe
par la sauvegarde prise avant le déploiement : l'opération inverse ne fait rien.
"""
from django.db import migrations

P, A, B = "PERSONNES", "ANIMAUX", "BIENS"

CODES_DEMANDE = {
    "Transport": "EVAC", "Hébergement": "ABRI", "Soins médicaux": "SOIN", "Soins": "SOIN",
    "Nourriture et eau": "NOUR", "Soutien psychologique": "PSY", "Accompagnement administratif": "ADMIN",
    "Interprétariat / traduction": "LANG", "Nettoyage / déblaiement": "NETT", "Matériel": "MAT", "Autre": "AUTRE",
}
CODES_OFFRE = {
    "Transport": "EVAC", "Hébergement": "ABRI", "Soins médicaux et paramédicaux": "SOIN",
    "Nourriture et eau": "NOUR", "Soutien psychologique": "PSY", "Matériel": "MAT", "Autre": "AUTRE",
    "Accompagnement administratif": "ADMIN", "Interprétariat / traduction": "LANG", "Nettoyage / déblaiement": "NETT",
}
#: Mêmes listes que classement.FAMILLES (figées ici : une migration ne doit pas dépendre du code vivant).
ADMIS_DEMANDE = {"EVAC": [P, A, B], "ABRI": [P, A], "SOIN": [A], "NOUR": [P, A], "PSY": [P], "ADMIN": [P],
                 "LANG": [], "NETT": [B], "MAT": [], "AUTRE": [P, A, B]}
ADMIS_OFFRE = dict(ADMIS_DEMANDE, SOIN=[P, A])

#: (ancien type de demande, nouveau type, pour qui, besoin d'origine, besoin d'arrivée)
DEMANDES_DEPLACEES = [
    ("Assistance à évacuation", "Transport", P, "Assistance immédiate", "Transport"),
    ("Transport d'animaux", "Transport", A, "Transport d'animaux", "Transport"),
    ("Hébergement d'urgence pour animaux", "Hébergement", A, "Hébergement d'urgence pour animaux", "Hébergement"),
    ("Soutien aux animaux", "Nourriture et eau", A, "Soutien aux animaux", "Nourriture et eau"),
]
OFFRES_DEPLACEES = [("Assistance immédiate", "Soins médicaux et paramédicaux", P)]
OFFRES_TEST = ["Matériel test", "Matériel (verif ress)"]
NOUVELLES_OFFRES = ["Nettoyage / déblaiement", "Accompagnement administratif", "Interprétariat / traduction"]

BESOINS_ANIMAUX = ["Transport d'animaux", "Hébergement d'urgence pour animaux", "Soutien aux animaux"]
FAMILLES_ANIMAUX = ["Transport", "Hébergement", "Nourriture et eau", "Soins médicaux"]

GROUPE_ANIMAUX = "Soutien aux animaux"
NOUVELLES_COMPETENCES = ["Évacuation d'animaux", "Évacuation d'équidés", "Évacuation de bétail",
                         "Hébergement d'animaux", "Nourrissage d'animaux", "Soins vétérinaires"]
#: (besoin, pour qui, catégorie, compétence)
CASCADE = [
    ("Transport", A, None, "Évacuation d'animaux"),
    ("Transport", A, "EQUIDES", "Évacuation d'équidés"),
    ("Transport", A, "BETAIL", "Évacuation de bétail"),
    ("Transport", A, None, GROUPE_ANIMAUX),
    ("Hébergement", A, None, "Hébergement d'animaux"),
    ("Hébergement", A, None, GROUPE_ANIMAUX),
    ("Nourriture et eau", A, None, "Nourrissage d'animaux"),
    ("Nourriture et eau", A, None, GROUPE_ANIMAUX),
    ("Soins médicaux", A, None, "Soins vétérinaires"),
    ("Soins médicaux", A, None, GROUPE_ANIMAUX),
]

NOUVEAUX_SIGNALEMENTS = [
    ("Départ de feu", "Fumée ou flammes : appelez d'abord le 18 ou le 112."),
    ("Inondation / montée des eaux", "Eau qui monte, rue ou maison inondée."),
]


def _defaut(admis):
    if not admis:
        return None
    if len(admis) == 1:
        return admis[0]
    return P if P in admis else admis[0]


def reclasser(apps, schema_editor):
    RequestType = apps.get_model("core", "RequestType")
    OfferType = apps.get_model("core", "OfferType")
    InformationType = apps.get_model("core", "InformationType")
    Request = apps.get_model("core", "Request")
    Offer = apps.get_model("core", "Offer")
    Besoin = apps.get_model("core", "Besoin")
    Competence = apps.get_model("core", "Competence")
    BesoinCompetence = apps.get_model("core", "BesoinCompetence")
    RequestTypeBesoin = apps.get_model("core", "RequestTypeBesoin")
    OfferTypeBesoin = apps.get_model("core", "OfferTypeBesoin")
    InformationTypeBesoin = apps.get_model("core", "InformationTypeBesoin")
    Dossier = apps.get_model("core", "Dossier")
    ImplicationInstitution = apps.get_model("core", "ImplicationInstitution")

    besoin = lambda nom: Besoin.objects.filter(nom=nom).first()

    # 1. Soins : la demande revient, pour les animaux seulement (une urgence médicale pour une
    #    personne reste le 15, décision du 01/09/2026).
    soins = RequestType.objects.filter(type="Soins").first() or RequestType.objects.filter(type="Soins médicaux").first()
    if soins is not None:
        soins.type = "Soins"
        soins.description = "Soins pour des animaux blessés ou malades. Pour une personne, appelez le 15."
        soins.actif = True
        soins.save()
        b = besoin("Soins médicaux")
        if b is not None and not RequestTypeBesoin.objects.filter(request_type=soins).exists():
            RequestTypeBesoin.objects.create(request_type=soins, besoin=b)

    # 2. (rien à créer : voir l'en-tête)

    # 3. Codes des familles.
    for libelle, code in CODES_DEMANDE.items():
        RequestType.objects.filter(type=libelle, parent__isnull=True).update(code=code)
    for libelle, code in CODES_OFFRE.items():
        OfferType.objects.filter(type=libelle).update(code=code)

    # 4. Les familles absentes côté offre.
    for libelle in NOUVELLES_OFFRES:
        type_demande = RequestType.objects.filter(type=libelle, parent__isnull=True).first()
        if type_demande is None:
            continue
        offre, _ = OfferType.objects.get_or_create(type=libelle, defaults={"actif": True, "code": CODES_OFFRE[libelle]})
        for pont in RequestTypeBesoin.objects.filter(request_type=type_demande):
            OfferTypeBesoin.objects.get_or_create(offer_type=offre, besoin_id=pont.besoin_id)

    # 5. Demandes : les types « animaux » et « Assistance à évacuation » rejoignent leur famille.
    for ancien, nouveau, pour_qui, besoin_avant, besoin_apres in DEMANDES_DEPLACEES:
        t_ancien = RequestType.objects.filter(type=ancien).first()
        t_nouveau = RequestType.objects.filter(type=nouveau, parent__isnull=True).first()
        if t_ancien is None or t_nouveau is None:
            continue
        ids = list(Request.objects.filter(request_type=t_ancien).values_list("id", flat=True))
        Request.objects.filter(id__in=ids).update(request_type=t_nouveau, beneficiaire=pour_qui)
        b_avant, b_apres = besoin(besoin_avant), besoin(besoin_apres)
        if b_avant is not None and b_apres is not None:
            Dossier.objects.filter(demande_id__in=ids, besoin=b_avant).update(besoin=b_apres)
        t_ancien.actif = False
        t_ancien.save(update_fields=["actif"])

    # 6. Pour qui par défaut des autres demandes, selon leur famille.
    for t in RequestType.objects.all():
        code = t.code or (RequestType.objects.filter(pk=t.parent_id).values_list("code", flat=True).first() if t.parent_id else None)
        defaut = _defaut(ADMIS_DEMANDE.get(code or "", []))
        if defaut:
            Request.objects.filter(request_type=t, beneficiaire__isnull=True).update(beneficiaire=defaut)

    # 7. Offres.
    for ancien, nouveau, pour_qui in OFFRES_DEPLACEES:
        t_ancien = OfferType.objects.filter(type=ancien).first()
        t_nouveau = OfferType.objects.filter(type=nouveau).first()
        if t_ancien is None or t_nouveau is None:
            continue
        Offer.objects.filter(offer_type=t_ancien).update(offer_type=t_nouveau, beneficiaire=pour_qui)
        t_ancien.actif = False
        t_ancien.save(update_fields=["actif"])
    for transport, pour_qui in (("PERSONNES", P), ("ANIMAUX", A), ("MATERIEL", B)):
        Offer.objects.filter(offer_type__code="EVAC", transport_type=transport, beneficiaire__isnull=True).update(beneficiaire=pour_qui)
    for t in OfferType.objects.exclude(code__isnull=True):
        defaut = _defaut(ADMIS_OFFRE.get(t.code, []))
        if defaut:
            Offer.objects.filter(offer_type=t, beneficiaire__isnull=True).update(beneficiaire=defaut)
    for libelle in OFFRES_TEST:
        t = OfferType.objects.filter(type=libelle).first()
        if t is not None and not Offer.objects.filter(offer_type=t).exists():
            t.actif = False
            t.save(update_fields=["actif"])

    # 8. Compétences spécialisées « animaux » et cascade de rapprochement.
    #    Seulement là où le groupe « Soutien aux animaux » existe déjà (la production).
    groupe = Competence.objects.filter(nom=GROUPE_ANIMAUX).first()
    for nom in (NOUVELLES_COMPETENCES if groupe is not None else []):
        c, cree = Competence.objects.get_or_create(nom=nom, defaults={"active": True, "parent": groupe})
        if not cree and c.parent_id is None and c.id != groupe.id:
            c.parent = groupe
            c.save(update_fields=["parent"])
    for nom_besoin, pour_qui, categorie, nom_competence in (CASCADE if groupe is not None else []):
        b, c = besoin(nom_besoin), Competence.objects.filter(nom=nom_competence).first()
        if b is None or c is None:
            continue
        BesoinCompetence.objects.get_or_create(besoin=b, competence=c, beneficiaire=pour_qui, categorie_animaux=categorie)
    # Soins : une correspondance générale si le besoin n'en a aucune.
    b_soins, secourisme = besoin("Soins médicaux"), Competence.objects.filter(nom="Secourisme").first()
    if b_soins is not None and secourisme is not None and not BesoinCompetence.objects.filter(
            besoin=b_soins, beneficiaire__isnull=True).exists():
        BesoinCompetence.objects.create(besoin=b_soins, competence=secourisme)

    # 9. Thèmes à l'écoute : les besoins « animaux » laissent place aux familles. Une institution
    #    qui n'écoutait QUE les animaux garde exactement cela : les familles, pour les animaux.
    anciens = list(Besoin.objects.filter(nom__in=BESOINS_ANIMAUX))
    familles = list(Besoin.objects.filter(nom__in=FAMILLES_ANIMAUX))
    if anciens:
        for implication in ImplicationInstitution.objects.filter(themes__in=anciens).distinct():
            autres = implication.themes.exclude(id__in=[b.id for b in anciens]).exists()
            implication.themes.remove(*anciens)
            implication.themes.add(*familles)
            if not autres and not implication.beneficiaires_ecoutes:
                implication.beneficiaires_ecoutes = [A]
                implication.save(update_fields=["beneficiaires_ecoutes"])
        Besoin.objects.filter(id__in=[b.id for b in anciens]).update(actif=False)

    # 10. Signalements : feu et inondation, écoutés comme un danger.
    danger = besoin("Danger imminent")
    for libelle, description in (NOUVEAUX_SIGNALEMENTS if InformationType.objects.exists() else []):
        t, _ = InformationType.objects.get_or_create(type=libelle, defaults={"description": description})
        if danger is not None:
            InformationTypeBesoin.objects.get_or_create(information_type=t, besoin=danger)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0399_classement_quoi_pour_qui"),
    ]

    operations = [
        migrations.RunPython(reclasser, migrations.RunPython.noop),
    ]
