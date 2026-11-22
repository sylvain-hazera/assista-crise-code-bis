"""Amorçage d'un département par une AASC sous convention départementale (21/11/2026).

Demande de Sylvain : « une division départementale crée son conseil départemental, récupère
ensuite les répertoires officiels intégraux de tous les EPCI / collectivités du département,
télécharge toutes les adresses ventilées par commune, la liste de tous les risques, les sites
sensibles… »

« Tout ce qui est récupération à l'avance doit l'être » (21/11/2026). Six étapes, chacune
relançable seule, chacune consignée dans `AmorcageDepartement.etapes` :

0. **referentiel** — le référentiel des communes du département (geo.api.gouv.fr, commande
   `import_communes`) : la table `Commune` n'est qu'un cache, l'amorçage ne doit oublier
   personne.
1. **annuaire** — l'Annuaire de l'administration (api-lannuaire.service-public.gouv.fr), commune
   par commune : il ne se filtre pas par département (vérifié le 21/11/2026, un joker sur le code
   INSEE ne rend rien). Chaque enregistrement porte `pivot.type_service_local`. La mairie et
   l'EPCI deviennent des institutions (créées ou complétées, jamais en double) ; les services
   utiles en crise rejoignent l'annuaire PCS du conseil départemental (dédoublonnés).
2. **adresses** — le fichier départemental de la Base Adresse Nationale, un seul téléchargement.
3. **risques** — pour chaque commune, `releve_georisques.relever_tout` : les rubriques de
   Géorisques, les zonages officiels, les plans de prévention, et leur périmètre et leur acte au
   Géoportail de l'urbanisme.
4. **sites** — les imports open data de sites sensibles, au périmètre du département, lancés en
   tâche de fond et suivis par leur propre trace (`ImportOpenData`).
5. **simulations** — le pré-calcul de la simulation d'inondation et de ruissellement de chaque
   commune (grille d'altitude IGN, paliers d'eau, accumulation, seuil par adresse), programmé une
   commune par minute ; chaque calcul consigne son état (`TacheSimulationInondation`) et la page
   de simulation le trouve déjà fait.

Seules des données publiques circulent : des codes de commune et de département.
"""
import json
import time
import urllib.parse
import urllib.request

from django.utils import timezone

URL_ANNUAIRE = "https://api-lannuaire.service-public.gouv.fr/api/records/1.0/search/"
ETAPES = ("referentiel", "annuaire", "adresses", "risques", "sites", "simulations")
ESPACEMENT_SIMULATIONS = 60  # secondes entre deux communes : l'IGN limite son débit
# Une commune demande ~18 appels à Géorisques, espacés de 5 s pour toute la plateforme
# (zonages_officiels.PAUSE_S) : ~90 s. Le 22/11/2026, la Gironde (534 communes) en une seule
# tâche aurait demandé ~13 h, au-delà de la limite de 4 h.
# Les communes s'enchaînent : chaque tâche traite une commune puis programme la suivante,
# après un court délai. Jamais des centaines de tâches programmées à des heures d'écart : avec
# Redis, une tâche dont le départ dépasse le délai de visibilité (1 h) est redistribuée, donc
# exécutée plusieurs fois.
ESPACEMENT_RISQUES = 10
#: Au-delà, un amorçage sans fin consignée est tenu pour interrompu (la tâche a été tuée).
DUREE_MAX_HEURES = 5

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
    """Une notification « Nouvelle institution » par mairie créée, c'était plusieurs centaines de
    courriels aux administrateurs pour un département (constaté le 22/11/2026 sur la Gironde) :
    elles sont suspendues, et un seul récapitulatif part à la fin. De même, chaque mairie créée
    programmait le chargement des adresses de sa commune, soit 448 téléchargements du fichier
    départemental (deux heures d'un des deux processus de tâches de fond) : l'étape « adresses »
    charge tout le département en une fois."""
    from .notifications_admin import notifications_institution_suspendues, notifier_administrateurs

    from .referentiel_adresses import chargement_auto_suspendu

    with notifications_institution_suspendues(), chargement_auto_suspendu():
        resultat = _etape_annuaire(cg, communes, interroger, pause)
    c = resultat["comptes"]
    if c["mairies_creees"] or c["epci_crees"]:
        notifier_administrateurs(
            f"Amorçage du département {cg.departement_code} : {c['mairies_creees']} mairie(s) et "
            f"{c['epci_crees']} intercommunalité(s) créées",
            f"L'amorçage de {cg.nom} a créé {c['mairies_creees']} mairie(s) et {c['epci_crees']} "
            f"intercommunalité(s) depuis l'Annuaire de l'administration, et versé "
            f"{c['annuaire_ajoutes']} service(s) de crise à l'annuaire du conseil départemental.")
    return resultat


def _etape_annuaire(cg, communes, interroger, pause) -> dict:
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
    """Programme le relevé de chaque commune (une tâche chacune, espacées) : l'avancement se lit
    ensuite en direct dans les relevés (voir avancement_risques)."""
    from .tasks import enchainer_amorcage_task
    if communes:
        enchainer_amorcage_task.delay("risques", list(communes), cg.environment)
    return {"comptes": {"communes_programmees": len(communes),
                        "duree_estimee_heures": round(len(communes) * 100 / 3600, 1)}}


def avancement_risques(amorcage) -> dict:
    """Communes du département relevées depuis le lancement de l'amorçage."""
    from .models import Commune, ReleveGeorisques
    cg = amorcage.delegation.collectivite
    total = Commune.objects.filter(departement_code=cg.departement_code).count()
    faites = (ReleveGeorisques.objects.filter(commune_code__startswith=cg.departement_code,
                                              releve_le__gte=amorcage.debut, environment=cg.environment)
              .values("commune_code").distinct().count())
    return {"faites": faites, "total": total}


def etape_sites(cg, communes) -> dict:
    from .opendata import CONNECTEURS
    from .sites_sensibles import lancer_import
    from .tasks import FILE_LOURDE
    lancees = []
    for source in CONNECTEURS:
        lancer_import(cg, source, {"niveau": "departement", "code": cg.departement_code},
                      environment=cg.environment, file=FILE_LOURDE)
        lancees.append(str(source))
    return {"comptes": {"sources_lancees": len(lancees)}, "sources": lancees}


def etape_referentiel(cg, communes) -> dict:
    from django.core.management import call_command
    from .models import Commune
    avant = len(communes)
    call_command("import_communes", cg.departement_code)
    apres = Commune.objects.filter(departement_code=cg.departement_code).count()
    return {"comptes": {"communes_avant": avant, "communes_apres": apres}}


def etape_simulations(cg, communes) -> dict:
    """Programme, commune par commune, les calculs de la page de simulation : ils tournent ensuite
    seuls, espacés, et chacun consigne son état."""
    from .tasks import enchainer_amorcage_task
    if communes:
        enchainer_amorcage_task.delay("simulations", list(communes), cg.environment)
    return {"comptes": {"communes_programmees": len(communes),
                        "duree_estimee_minutes": len(communes) * ESPACEMENT_SIMULATIONS // 60}}


def simulations_commune(code, environment):
    """Lance les trois calculs de la page de simulation pour une commune."""
    from .models import StatutTacheInondation, TacheSimulationInondation, TypeTacheInondation
    from .tasks import FILE_LOURDE, calculer_paliers_task, calculer_ruissellement_task, charger_adresses_task

    for type_tache, tache in ((TypeTacheInondation.PALIERS, calculer_paliers_task),
                              (TypeTacheInondation.RUISSELLEMENT, calculer_ruissellement_task),
                              (TypeTacheInondation.ADRESSES, charger_adresses_task)):
        TacheSimulationInondation.objects.update_or_create(
            commune_code=code, environment=environment, type_tache=type_tache,
            defaults={"statut": StatutTacheInondation.EN_COURS, "erreur": None})
        tache.apply_async(args=[code, environment, False], queue=FILE_LOURDE)


def enchainer(etape, communes, environment, suivante):
    """Traite la première commune, puis confie le reste à `suivante(reste, délai)`. Une erreur
    sur une commune n'arrête pas les autres."""
    import logging
    from .releve_georisques import relever_tout

    code, reste = communes[0], communes[1:]
    try:
        if etape == "risques":
            relever_tout(code, environment)
        else:
            simulations_commune(code, environment)
    except Exception:
        logging.getLogger(__name__).exception("Amorçage %s : échec pour %s", etape, code)
    if reste:
        suivante(reste, ESPACEMENT_RISQUES if etape == "risques" else ESPACEMENT_SIMULATIONS)


FONCTIONS = {"referentiel": etape_referentiel, "annuaire": etape_annuaire, "adresses": etape_adresses,
             "risques": etape_risques, "sites": etape_sites, "simulations": etape_simulations}


def executer(amorcage, etapes=ETAPES) -> None:
    """Déroule les étapes demandées, en consignant chacune avant et après : l'écran doit
    pouvoir dire « en cours » et ce qui a échoué, même si la tâche s'interrompt."""
    from .models import Commune

    cg = amorcage.delegation.collectivite

    def communes_du_departement():
        return sorted(Commune.objects.filter(departement_code=cg.departement_code).values_list("code", flat=True))

    communes = communes_du_departement()
    for nom in etapes:
        amorcage.etapes[nom] = {"statut": "EN_COURS", "debut": timezone.now().isoformat()}
        amorcage.save(update_fields=["etapes"])
        try:
            resultat = FONCTIONS[nom](cg, communes)
            statut = "PROGRAMMEE" if nom in ("risques", "simulations") else "TERMINEE"
            amorcage.etapes[nom] = {"statut": statut, "fin": timezone.now().isoformat(), **resultat}
        except Exception as exc:
            amorcage.etapes[nom] = {"statut": "ECHEC", "fin": timezone.now().isoformat(), "erreur": str(exc)[:500]}
        amorcage.save(update_fields=["etapes"])
        if nom == "referentiel":
            communes = communes_du_departement()  # le référentiel vient d'être complété
    amorcage.fin = timezone.now()
    amorcage.save(update_fields=["fin"])


def est_interrompu(amorcage) -> bool:
    """Sans fin consignée bien après la limite de la tâche : elle a été tuée."""
    import datetime
    return amorcage.fin is None and timezone.now() - amorcage.debut > datetime.timedelta(hours=DUREE_MAX_HEURES)
