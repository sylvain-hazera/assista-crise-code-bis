"""Amorçage d'un département par une AASC sous convention départementale (21/11/2026).

Demande de Sylvain : « une division départementale crée son conseil départemental, récupère
ensuite les répertoires officiels intégraux de tous les EPCI / collectivités du département,
télécharge toutes les adresses ventilées par commune, la liste de tous les risques, les sites
sensibles… »

Quatre étapes, chacune relançable seule, chacune consignée dans `AmorcageDepartement.etapes` :

1. **annuaire** — l'Annuaire de l'administration (api-lannuaire.service-public.gouv.fr), commune
   par commune : il ne se filtre pas par département (vérifié le 21/11/2026, un joker sur le code
   INSEE ne rend rien). Chaque enregistrement porte `pivot.type_service_local`. La mairie et
   l'EPCI deviennent des institutions (créées ou complétées, jamais en double) ; les services
   utiles en crise rejoignent l'annuaire PCS du conseil départemental (dédoublonnés).
2. **adresses** — le fichier départemental de la Base Adresse Nationale, un seul téléchargement.
3. **risques** — Géorisques pour chaque commune (`releve_georisques.relever_tout`).
4. **sites** — les imports open data de sites sensibles, au périmètre du département, lancés en
   tâche de fond et suivis par leur propre trace (`ImportOpenData`).

Seules des données publiques circulent : des codes de commune et de département.
"""
import json
import time
import urllib.parse
import urllib.request

from django.utils import timezone

URL_ANNUAIRE = "https://api-lannuaire.service-public.gouv.fr/api/records/1.0/search/"
ETAPES = ("annuaire", "adresses", "risques", "sites")

# Type de service de l'Annuaire → catégorie de l'annuaire de crise. Ce qui n'est pas ici n'est
# pas versé : l'annuaire de crise n'est pas l'annuaire de l'administration.
SERVICES_CRISE = {
    "prefecture": "PREFECTURE",
    "sous_pref": "SOUS_PREFECTURE",
    "sdis": "SDIS",
    "samu": "SAMU",
    "gendarmerie": "GENDARMERIE_POLICE",
    "gendarmerie_departementale": "GENDARMERIE_POLICE",
    "commissariat_police": "GENDARMERIE_POLICE",
    "police_municipale": "GENDARMERIE_POLICE",
    "ccas": "ELU_PERSONNEL_COMMUNAL",
    "ddt": "SERVICES_ETAT",
    "ars_antenne": "ARS",
}

PAUSE_ENTRE_APPELS = 0.25  # secondes : l'Annuaire est un service public partagé


def _json(valeur):
    if isinstance(valeur, str) and valeur[:1] in "[{":
        try:
            return json.loads(valeur)
        except ValueError:
            return valeur
    return valeur


def _premier(valeur, cle="valeur"):
    valeur = _json(valeur)
    if isinstance(valeur, list):
        valeur = valeur[0] if valeur else None
    if isinstance(valeur, dict):
        return valeur.get(cle)
    return valeur


def lire_enregistrement(record: dict) -> dict:
    """Ce dont on a besoin d'un enregistrement de l'Annuaire, normalisé."""
    f = (record or {}).get("fields", record) or {}
    pivot = _json(f.get("pivot")) or []
    type_service = pivot[0].get("type_service_local") if isinstance(pivot, list) and pivot else None
    adresse = _json(f.get("adresse"))
    adresse = adresse[0] if isinstance(adresse, list) and adresse else (adresse if isinstance(adresse, dict) else {})
    ligne_adresse = " ".join(p for p in (adresse.get("numero_voie"), adresse.get("code_postal"),
                                         adresse.get("nom_commune")) if p)
    courriel = _premier(f.get("adresse_courriel"))
    return {
        "type": type_service,
        "nom": f.get("nom") or "",
        "email": courriel if isinstance(courriel, str) and "@" in courriel else None,
        "telephone": _premier(f.get("telephone")),
        "adresse": ligne_adresse,
        "site": _premier(f.get("site_internet")),
        "siret": f.get("siret"),
    }


def interroger_annuaire(commune_code: str) -> list:
    """Tous les services locaux rattachés à une commune (une centaine au plus pour une préfecture)."""
    params = {"dataset": "api-lannuaire-administration", "rows": "200", "refine.code_insee_commune": commune_code}
    requete = urllib.request.Request(f"{URL_ANNUAIRE}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": "assista-crise"})
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        return json.load(reponse).get("records") or []


def _completer(institution, fiche):
    """Reporte les coordonnées officielles là où l'institution n'en a pas : on n'écrase jamais
    ce que la collectivité ou l'AASC a saisi."""
    modifie = []
    for champ, valeur in (("email", fiche["email"]), ("telephone", fiche["telephone"]), ("adresse", fiche["adresse"])):
        if valeur and not getattr(institution, champ, None):
            setattr(institution, champ, valeur)
            modifie.append(champ)
    if modifie:
        institution.save(update_fields=modifie)
    return bool(modifie)


def etape_annuaire(cg, communes, interroger=interroger_annuaire, pause=PAUSE_ENTRE_APPELS) -> dict:
    from .models import Commune, Institution, InstitutionType, InterlocuteurAlertePCS

    type_mairie = InstitutionType.objects.filter(code__iexact="mairie").first() or \
        InstitutionType.objects.create(code="mairie", libelle="Mairie")
    type_epci = InstitutionType.objects.filter(code__iexact="epci").first() or \
        InstitutionType.objects.create(code="epci", libelle="Communauté de communes / Métropole")
    deja = {(i.nom, i.organisme) for i in InterlocuteurAlertePCS.objects.filter(institutions=cg)}
    epci_par_commune = dict(Commune.objects.filter(code__in=communes).values_list("code", "epci_code"))
    comptes = {"communes": 0, "mairies_creees": 0, "mairies_completees": 0, "epci_crees": 0,
               "epci_completes": 0, "annuaire_ajoutes": 0, "echecs": 0}
    echecs = []
    for code in communes:
        try:
            records = interroger(code)
        except Exception as exc:
            comptes["echecs"] += 1
            echecs.append(f"{code} : {exc}"[:200])
            continue
        comptes["communes"] += 1
        for record in records:
            fiche = lire_enregistrement(record)
            if fiche["type"] == "mairie":
                mairie = (Institution.objects.filter(commune_code=code, type__code__iexact="mairie")
                          .order_by("date_creation").first())
                if mairie is None:
                    mairie = Institution.objects.create(nom=fiche["nom"] or f"Mairie {code}", type=type_mairie,
                                                        commune_code=code, email=fiche["email"],
                                                        telephone=fiche["telephone"], adresse=fiche["adresse"])
                    comptes["mairies_creees"] += 1
                elif _completer(mairie, fiche):
                    comptes["mairies_completees"] += 1
            elif fiche["type"] == "epci":
                epci_code = epci_par_commune.get(code)
                epci = (Institution.objects.filter(type__code__iexact="epci", epci_code=epci_code).first()
                        if epci_code else None)
                if epci is None:
                    epci = Institution.objects.create(nom=fiche["nom"], type=type_epci, commune_code=code,
                                                      epci_code=epci_code, email=fiche["email"],
                                                      telephone=fiche["telephone"], adresse=fiche["adresse"])
                    comptes["epci_crees"] += 1
                elif _completer(epci, fiche):
                    comptes["epci_completes"] += 1
            if fiche["type"] in SERVICES_CRISE and (fiche["nom"], fiche["type"]) not in deja:
                contact = InterlocuteurAlertePCS.objects.create(
                    nom=fiche["nom"], organisme=fiche["type"], categorie=SERVICES_CRISE[fiche["type"]],
                    email=fiche["email"], telephone=fiche["telephone"], departement_code=cg.departement_code,
                    notes=fiche["adresse"] or None, prevenir_ouverture_crise=False, environment=cg.environment,
                )
                contact.institutions.add(cg)
                deja.add((fiche["nom"], fiche["type"]))
                comptes["annuaire_ajoutes"] += 1
        if pause:
            time.sleep(pause)
    return {"comptes": comptes, "erreurs": echecs[:20]}


def etape_adresses(cg, communes) -> dict:
    from .referentiel_adresses import charger_departement
    return {"comptes": charger_departement(cg.departement_code, communes)}


def etape_risques(cg, communes) -> dict:
    from .releve_georisques import relever_tout
    comptes, erreurs = {"communes": 0, "echecs": 0}, []
    for code in communes:
        try:
            relever_tout(code, cg.environment)
            comptes["communes"] += 1
        except Exception as exc:
            comptes["echecs"] += 1
            erreurs.append(f"{code} : {exc}"[:200])
    return {"comptes": comptes, "erreurs": erreurs[:20]}


def etape_sites(cg, communes) -> dict:
    from .opendata import CONNECTEURS
    from .sites_sensibles import lancer_import
    lancees = []
    for source in CONNECTEURS:
        lancer_import(cg, source, {"niveau": "departement", "code": cg.departement_code},
                      environment=cg.environment)
        lancees.append(str(source))
    return {"comptes": {"sources_lancees": len(lancees)}, "sources": lancees}


FONCTIONS = {"annuaire": etape_annuaire, "adresses": etape_adresses, "risques": etape_risques, "sites": etape_sites}


def executer(amorcage, etapes=ETAPES) -> None:
    """Déroule les étapes demandées, en consignant chacune avant et après : l'écran doit
    pouvoir dire « en cours » et ce qui a échoué, même si la tâche s'interrompt."""
    from .models import Commune

    cg = amorcage.delegation.collectivite
    communes = sorted(Commune.objects.filter(departement_code=cg.departement_code).values_list("code", flat=True))
    for nom in etapes:
        amorcage.etapes[nom] = {"statut": "EN_COURS", "debut": timezone.now().isoformat()}
        amorcage.save(update_fields=["etapes"])
        try:
            resultat = FONCTIONS[nom](cg, communes)
            amorcage.etapes[nom] = {"statut": "TERMINEE", "fin": timezone.now().isoformat(), **resultat}
        except Exception as exc:
            amorcage.etapes[nom] = {"statut": "ECHEC", "fin": timezone.now().isoformat(), "erreur": str(exc)[:500]}
        amorcage.save(update_fields=["etapes"])
    amorcage.fin = timezone.now()
    amorcage.save(update_fields=["fin"])
