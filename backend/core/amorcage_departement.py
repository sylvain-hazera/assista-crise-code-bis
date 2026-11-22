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
ETAPES = ("referentiel", "annuaire", "repertoires", "adresses", "risques", "sites", "entreprises", "simulations")
ESPACEMENT_SIMULATIONS = 60  # secondes entre deux communes : l'IGN limite son débit
# Une commune demande ~18 appels à Géorisques, espacés de 5 s pour toute la plateforme
# (zonages_officiels.PAUSE_S) : ~90 s. Le 22/11/2026, la Gironde (534 communes) en une seule
# tâche aurait demandé ~13 h, au-delà de la limite de 4 h.
# Les communes s'enchaînent : chaque tâche traite une commune puis programme la suivante,
# après un court délai. Jamais des centaines de tâches programmées à des heures d'écart : avec
# Redis, une tâche dont le départ dépasse le délai de visibilité (1 h) est redistribuée, donc
# exécutée plusieurs fois.
ESPACEMENT_RISQUES = 10
#: Source importée commune par commune (voir etape_sites).
SOURCE_PAR_COMMUNE = "SIRENE"
ESPACEMENT_SIRENE = 30  # au long cours : l'annuaire des entreprises est un service partagé
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
        # Identifiant de la fiche à l'Annuaire : rend l'import rejouable sans doublon.
        "id": str(f.get("id") or (record or {}).get("recordid") or "")[:80],
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
    from .repertoires_departement import competence, rattacher_services

    # Fiches déjà là : par identifiant Annuaire, ou (anciens imports, sans identifiant) par nom et
    # type — le nom est chiffré, la comparaison se fait ici et non en base.
    par_cle = {i.cle_source: i for i in InterlocuteurAlertePCS.objects.filter(institutions=cg).exclude(cle_source="")}
    anciennes = {(i.nom, i.organisme): i for i in InterlocuteurAlertePCS.objects.filter(institutions=cg, cle_source="")}
    services = {}
    epci_par_commune = dict(Commune.objects.filter(code__in=communes).values_list("code", "epci_code"))
    comptes = {"communes": 0, "mairies_creees": 0, "mairies_completees": 0, "epci_crees": 0,
               "epci_completes": 0, "annuaire_ajoutes": 0, "rattachements": 0, "echecs": 0}
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
            if fiche["type"] in SERVICES_CRISE:
                contact = par_cle.get(fiche["id"]) if fiche["id"] else None
                if contact is None:
                    contact = anciennes.pop((fiche["nom"], fiche["type"]), None)
                    if contact is not None and fiche["id"]:
                        contact.cle_source = fiche["id"]
                        contact.save(update_fields=["cle_source"])
                if contact is None:
                    contact = InterlocuteurAlertePCS.objects.create(
                        nom=fiche["nom"], organisme=fiche["type"], categorie=SERVICES_CRISE[fiche["type"]],
                        email=fiche["email"], telephone=fiche["telephone"], departement_code=cg.departement_code,
                        notes=fiche["adresse"] or None, prevenir_ouverture_crise=False, environment=cg.environment,
                        cle_source=fiche["id"],
                    )
                    contact.institutions.add(cg)
                    comptes["annuaire_ajoutes"] += 1
                if fiche["id"]:
                    par_cle[fiche["id"]] = contact
                # Le même service revient pour chaque commune qu'il sert : on cumule.
                deja_vu = services.get(contact.id)
                servies = set(competence(record, fiche["type"])) | (set(deja_vu[3]) if deja_vu else set())
                services[contact.id] = (contact, fiche["type"], deja_vu[2] if deja_vu else code, sorted(servies))
        if pause:
            time.sleep(pause)
    # Redistribution : chaque service aussi aux mairies et EPCI qu'il sert (repertoires_departement).
    comptes["rattachements"] = rattacher_services(cg, list(services.values()))
    return {"comptes": comptes, "erreurs": echecs[:20]}


def etape_repertoires(cg, communes) -> dict:
    """Fiches des EPCI et des mairies dans les répertoires les uns des autres, et communes
    voisines (core/repertoires_departement.distribuer)."""
    from .repertoires_departement import distribuer
    resultat = distribuer(cg)
    erreurs = resultat.pop("erreurs", [])
    return {"comptes": resultat, "erreurs": erreurs}


def etape_adresses(cg, communes) -> dict:
    from .referentiel_adresses import charger_departement
    return {"comptes": charger_departement(cg.departement_code, communes)}


def etape_risques(cg, communes) -> dict:
    """Géorisques et Géoportail de l'urbanisme, commune par commune : l'enchaînement est lancé
    par `executer` (voir CHAINES), qui en tient l'avancement en base."""
    return {"comptes": {"communes_programmees": len(communes),
                        "duree_estimee_heures": round(len(communes) * 100 / 3600, 1)}}


def avancement_risques(amorcage) -> dict:
    """Communes du département dont les risques sont en base, quelle que soit la relance qui les
    a relevées (22/11/2026 : compter « depuis cette relance » affichait 3 / 534 alors que 78
    communes étaient déjà faites), et la date du dernier relevé."""
    from django.db.models import Max

    from .models import Commune, ReleveGeorisques
    cg = amorcage.delegation.collectivite
    total = Commune.objects.filter(departement_code=cg.departement_code).count()
    releves = ReleveGeorisques.objects.filter(commune_code__startswith=cg.departement_code, environment=cg.environment)
    faites = releves.values("commune_code").distinct().count()
    dernier = releves.aggregate(m=Max("releve_le"))["m"]
    # Géoportail de l'urbanisme, dans la même passe : ce qui en est déjà gardé (22/11/2026 :
    # « je vois Géorisques, scannes-tu le Géoportail aussi ? »).
    from .models import ServitudePPR, ZoneUrbanisme
    filtre = {"commune_code__startswith": cg.departement_code, "environment": cg.environment}
    servitudes = ServitudePPR.objects.filter(**filtre)
    zones = ZoneUrbanisme.objects.filter(**filtre)
    return {"faites": faites, "total": total, "dernier_releve": dernier.isoformat() if dernier else None,
            "geoportail": {"servitudes": servitudes.count(),
                           "communes_avec_servitudes": servitudes.values("commune_code").distinct().count(),
                           "zones_plu": zones.count(),
                           "communes_avec_plu": zones.values("commune_code").distinct().count()}}


def etape_sites(cg, communes) -> dict:
    from .opendata import CONNECTEURS
    from .sites_sensibles import lancer_import
    from .tasks import FILE_LOURDE
    lancees = []
    for source in CONNECTEURS:
        if str(source) == SOURCE_PAR_COMMUNE:
            continue  # étape « entreprises », à part, commune par commune
        lancer_import(cg, source, {"niveau": "departement", "code": cg.departement_code},
                      environment=cg.environment, file=FILE_LOURDE)
        lancees.append(str(source))
    return {"comptes": {"sources_lancees": len(lancees)}, "sources": lancees}


def etape_entreprises(cg, communes) -> dict:
    """Annuaire des entreprises (élevages, hébergements, transport, commerces…), commune par
    commune et au long cours : à l'échelle d'un département, l'annuaire plafonne ses réponses
    (1 500 établissements par thème, constaté le 22/11/2026 sur la Gironde) ; par commune, jamais.
    Enchaîné par `executer` (voir CHAINES)."""
    return {"comptes": {"faites": 0, "total": len(communes), "crees": 0,
                        "duree_estimee_heures": round(len(communes) * (ESPACEMENT_SIRENE + 20) / 3600, 1)}}


def etape_referentiel(cg, communes) -> dict:
    from django.core.management import call_command
    from .models import Commune
    avant = len(communes)
    call_command("import_communes", cg.departement_code)
    apres = Commune.objects.filter(departement_code=cg.departement_code).count()
    return {"comptes": {"communes_avant": avant, "communes_apres": apres}}


def etape_simulations(cg, communes) -> dict:
    """Les calculs de la page de simulation, commune par commune : enchaînés par `executer`."""
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


def sirene_commune(code, environment, institution):
    """Importe les entreprises d'une commune. Rend le nombre d'établissements créés."""
    from .sites_sensibles import executer_import
    resultat = executer_import(institution, SOURCE_PAR_COMMUNE, {"niveau": "commune", "code": code},
                               environment=environment) or {}
    return int(resultat.get("crees") or 0)


# ── Les étapes longues, et leur reprise (22/11/2026) ──
#
# « Si on redéploie ou reboot pendant un amorçage quelconque, ça reprend ensuite là où ça en
# était. » L'avancement d'une étape longue vit EN BASE, sur l'amorçage : les communes qui
# restent, un battement (dernière activité), et un jeton. Le message Celery ne porte que
# l'étape, l'amorçage et le jeton :
#   - au démarrage du worker des travaux lourds (redéploiement, reboot), `reprendre` relance
#     chaque étape longue inachevée avec un NOUVEAU jeton ;
#   - un message d'avant (rendu plus tard par Redis, ou en attente d'un délai) porte l'ancien
#     jeton : il est ignoré. Aucune commune n'est traitée deux fois en parallèle.

#: Étape -> espacement entre deux communes (secondes).
CHAINES = {"risques": ESPACEMENT_RISQUES, "entreprises": ESPACEMENT_SIRENE, "simulations": ESPACEMENT_SIMULATIONS}
#: Sans battement depuis ce délai, une étape longue est tenue pour arrêtée (reprise à la lecture).
SILENCE_MINUTES = 30


def _nouveau_jeton():
    import uuid
    return uuid.uuid4().hex[:12]


def _lancer_chaine(amorcage_id, etape, environment, jeton, delai=5):
    from django.db import transaction
    from .tasks import enchainer_amorcage_task
    transaction.on_commit(lambda: enchainer_amorcage_task.apply_async(
        args=[etape, [], environment, str(amorcage_id), jeton], countdown=delai))


def enchainer(etape, amorcage_id, jeton, environment):
    """Traite la prochaine commune de l'étape, la retire des restantes, et programme la suivante.
    Ignore un message dont le jeton n'est plus le bon. Une erreur sur une commune n'arrête pas
    les autres."""
    import logging
    from django.db import transaction
    from .models import AmorcageDepartement
    from .releve_georisques import relever_tout

    a = AmorcageDepartement.objects.select_related("delegation__collectivite").filter(pk=amorcage_id).first()
    etat = (a.etapes or {}).get(etape) if a else None
    if not etat or etat.get("jeton") != jeton or not etat.get("restantes"):
        return
    code = etat["restantes"][0]
    crees, erreur = 0, None
    try:
        if etape == "risques":
            relever_tout(code, environment)
        elif etape == "entreprises":
            crees = sirene_commune(code, environment, a.delegation.collectivite)
        else:
            simulations_commune(code, environment)
    except Exception as exc:
        erreur = f"{code} : {exc}"[:200]
        logging.getLogger(__name__).exception("Amorçage %s : échec pour %s", etape, code)
    with transaction.atomic():
        a = AmorcageDepartement.objects.select_for_update().get(pk=amorcage_id)
        etat = a.etapes.get(etape) or {}
        if etat.get("jeton") != jeton:
            return
        restantes = [c for c in etat.get("restantes", []) if c != code]
        etat["restantes"] = restantes
        etat["battement"] = timezone.now().isoformat()
        comptes = etat.setdefault("comptes", {})
        if etape == "entreprises":
            comptes["faites"] = comptes.get("total", 0) - len(restantes)
            comptes["crees"] = comptes.get("crees", 0) + crees
        if erreur:
            etat["erreurs"] = (etat.get("erreurs") or [])[-19:] + [erreur]
        if not restantes:
            etat["statut"], etat["fin"] = "TERMINEE", timezone.now().isoformat()
        a.etapes[etape] = etat
        a.save(update_fields=["etapes"])
    if restantes:
        _lancer_chaine(amorcage_id, etape, environment, jeton, delai=CHAINES.get(etape, 10))


def reprendre(silence_minutes=SILENCE_MINUTES, amorcage=None) -> int:
    """Relance ce qui s'est arrêté : les étapes longues inachevées sans battement depuis
    `silence_minutes` (0 au démarrage du worker : rien ne peut tourner), et un amorçage dont la
    tâche principale a été coupée en route. Rend le nombre d'étapes relancées."""
    import datetime
    from django.db import transaction
    from django.utils.dateparse import parse_datetime
    from .models import AmorcageDepartement
    from .tasks import amorcer_departement_task

    limite = timezone.now() - datetime.timedelta(minutes=silence_minutes)
    candidats = [amorcage] if amorcage is not None else AmorcageDepartement.objects.filter(
        debut__gte=timezone.now() - datetime.timedelta(days=14)).select_related("delegation__collectivite")
    relancees = 0
    for a in candidats:
        with transaction.atomic():
            a = AmorcageDepartement.objects.select_for_update().select_related("delegation__collectivite").get(pk=a.pk)
            env = a.delegation.collectivite.environment
            modifie = False
            for etape in CHAINES:
                etat = (a.etapes or {}).get(etape)
                if not etat or etat.get("statut") not in ("PROGRAMMEE", "EN_COURS") or not etat.get("restantes"):
                    continue
                battement = parse_datetime(etat.get("battement") or "") if etat.get("battement") else None
                if battement is not None and battement > limite:
                    continue
                etat["jeton"], etat["battement"] = _nouveau_jeton(), timezone.now().isoformat()
                etat["reprises"] = int(etat.get("reprises") or 0) + 1
                a.etapes[etape] = etat
                _lancer_chaine(a.pk, etape, env, etat["jeton"])
                modifie, relancees = True, relancees + 1
            # La tâche principale (étapes courtes, puis lancement des longues) coupée en route.
            if a.fin is None:
                principal = (a.etapes or {}).get("_principal") or {}
                battement = parse_datetime(principal.get("battement") or "") if principal.get("battement") else None
                restent = [e for e in ETAPES if (a.etapes.get(e) or {}).get("statut") in ("EN_ATTENTE", "EN_COURS")]
                if restent and (battement is None or battement <= limite):
                    jeton = _nouveau_jeton()
                    a.etapes["_principal"] = {"jeton": jeton, "battement": timezone.now().isoformat()}
                    transaction.on_commit(lambda ident=str(a.pk), r=restent, j=jeton:
                                          amorcer_departement_task.apply_async(args=[ident, r, j], countdown=5))
                    modifie, relancees = True, relancees + 1
            if modifie:
                a.save(update_fields=["etapes"])
    return relancees


FONCTIONS = {"referentiel": etape_referentiel, "annuaire": etape_annuaire, "repertoires": etape_repertoires,
             "adresses": etape_adresses,
             "risques": etape_risques, "sites": etape_sites, "entreprises": etape_entreprises,
             "simulations": etape_simulations}


def executer(amorcage, etapes=ETAPES) -> None:
    """Déroule les étapes demandées, en consignant chacune avant et après : l'écran doit
    pouvoir dire « en cours » et ce qui a échoué, même si la tâche s'interrompt."""
    from .models import Commune

    cg = amorcage.delegation.collectivite

    def communes_du_departement():
        return sorted(Commune.objects.filter(departement_code=cg.departement_code).values_list("code", flat=True))

    communes = communes_du_departement()
    for nom in etapes:
        principal = amorcage.etapes.get("_principal") or {}
        amorcage.etapes["_principal"] = {**principal, "battement": timezone.now().isoformat()}
        amorcage.etapes[nom] = {"statut": "EN_COURS", "debut": timezone.now().isoformat()}
        amorcage.save(update_fields=["etapes"])
        try:
            resultat = FONCTIONS[nom](cg, communes)
            if nom in CHAINES:
                # L'avancement vit en base (communes restantes, jeton) : c'est ce qui permet de
                # reprendre après un redéploiement ou un redémarrage.
                jeton = _nouveau_jeton()
                amorcage.etapes[nom] = {"statut": "PROGRAMMEE", "fin": timezone.now().isoformat(), **resultat,
                                        "restantes": list(communes), "jeton": jeton,
                                        "battement": timezone.now().isoformat()}
                if communes:
                    _lancer_chaine(amorcage.pk, nom, cg.environment, jeton)
                else:
                    amorcage.etapes[nom]["statut"] = "TERMINEE"
            else:
                amorcage.etapes[nom] = {"statut": "TERMINEE", "fin": timezone.now().isoformat(), **resultat}
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
