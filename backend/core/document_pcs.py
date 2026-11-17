"""Le document du plan communal de sauvegarde, construit à la demande depuis les données vivantes.

**Rien n'est rédigé ici qui existe déjà ailleurs.** Le plan d'une commune est déjà dans
l'application, par morceaux : les risques qu'elle a déclarés (avec l'état des lieux et les enjeux
qu'elle a écrits), les sites sensibles qu'elle a retenus, ses dispositifs activables et leurs
missions types, son annuaire de crise, ses équipes, ses points d'accueil et leur matériel. Ce
module les RASSEMBLE et les met en page dans l'ordre de la trame de l'État ; les textes de la
commune sont repris tels quels. Seuls l'arrêté, le lieu du poste de commandement et les
modalités d'activation n'avaient pas de place : ils vivent dans `DossierPCS`.

Deux conséquences voulues :

- le document n'est **jamais stocké** : il sort à l'instant, avec l'annuaire du jour. Un plan
  imprimé il y a deux ans dit qui appeler il y a deux ans ;
- chaque partie vide est dite vide, avec l'écran où la remplir (`manques`). Un plan qui
  passerait sous silence l'absence de centre d'accueil serait pire que pas de plan.

**Les personnes vulnérables n'y figurent pas.** La trame demande leur liste nominative ; elle
s'édite à part, depuis le registre, par les seules personnes désignées par le maire
(core/registre_vulnerables_pdf.py). Ce document-ci circule trop pour la porter.

Ordre des parties : trame simplifiée du plan communal de sauvegarde (identification des risques,
organisation de la réponse, recensement des moyens, annexes).
"""
import datetime
import io
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import (
    CategorieInterlocuteurPCS,
    Commune,
    ContactInstitution,
    DossierPCS,
    Environment,
    MaterielPoint,
    Plan,
    RisqueCommunal,
    StatutSiteSensible,
    SuiviSiteSensible,
    Team,
)
from .registre_vulnerables_pdf import FILET, FOND_AVERTISSEMENT, FOND_ENTETE, GRIS, SOMBRE, _CanevasNumerote

#: Ordre de l'organigramme : celui de la trame.
_ORDRE_FONCTIONS = ("DOS", "COORDINATION", "ALERTE", "SOUTIEN", "LOGISTIQUE", "SECRETARIAT", "AUTRE")

#: Nom de la zone créée d'office pour chaque collectivité (voir models._assurer_zone_mon_territoire).
ZONE_AUTOMATIQUE = "Mon territoire"

#: Au-delà, le plan est signalé « à revoir ». Cinq ans est l'usage des trames préfectorales.
ANS_AVANT_REVISION = 5

#: Sans eux, l'annuaire de crise ne permet pas de prévenir ceux qui doivent l'être en premier.
CATEGORIES_ATTENDUES = (
    CategorieInterlocuteurPCS.PREFECTURE,
    CategorieInterlocuteurPCS.SDIS,
    CategorieInterlocuteurPCS.GENDARMERIE_POLICE,
)


def dossier_de(institution, environment) -> DossierPCS:
    dossier, _cree = DossierPCS.objects.get_or_create(institution=institution, environment=environment)
    return dossier


def _texte(valeur) -> str:
    return (valeur or "").strip()


def personnes_de_la_fonction(fonction, nommer, zone_reelle: bool) -> dict:
    """Qui tient une fonction du poste de commandement : ce qui a été saisi, sinon ce que dit
    l'équipe qui la tient (son responsable, puis le premier membre de son encadrement).

    C'est ce qui évite de nommer deux fois les mêmes personnes. Le téléphone d'un membre est une
    coordonnée personnelle : il ne sort qu'en zone réelle, comme partout ailleurs."""
    equipe = fonction.equipe if fonction.equipe_id else None
    responsable = equipe.leader if equipe and equipe.leader_id else None
    encadrant = None
    if equipe:
        encadrant = next((m for m in equipe.membres_encadrement.all() if m.id != getattr(responsable, "id", None)), None)

    def telephone(utilisateur):
        return _texte(utilisateur.phone_number) if utilisateur and zone_reelle else ""

    return {
        "equipe": equipe.name if equipe else "",
        "titulaire": _texte(fonction.titulaire) or (nommer(responsable) if responsable else ""),
        "titulaire_telephone": _texte(fonction.titulaire_telephone) or (telephone(responsable) if not _texte(fonction.titulaire) else ""),
        "suppleant": _texte(fonction.suppleant) or (nommer(encadrant) if encadrant else ""),
        "suppleant_telephone": _texte(fonction.suppleant_telephone) or (telephone(encadrant) if not _texte(fonction.suppleant) else ""),
    }


def composer_depuis_le_plan(equipe_de_crise, institution, environment, code_type_point) -> bool:
    """Donne à l'équipe créée pour une crise le responsable, l'encadrement et les membres de
    l'équipe permanente que l'organigramme désigne pour ce type de point. Vrai si elle l'a fait.

    Sert à la CELLULE DE CRISE, qui est une équipe neuve à chaque crise parce qu'elle porte le
    salon de la crise (un salon par crise) : on y copie les personnes, jamais le salon. Les
    autres équipes permanentes, elles, se réutilisent telles quelles d'une crise à l'autre --
    c'est le but d'une équipe prête à l'avance (voir `equipes_par_point`)."""
    from .models import Team

    identifiant = equipes_par_point(institution, environment).get(code_type_point or "")
    source = Team.objects.filter(pk=identifiant).first() if identifiant else None
    if source is None or source.pk == equipe_de_crise.pk:
        return False
    if source.leader_id and not equipe_de_crise.leader_id:
        equipe_de_crise.leader_id = source.leader_id
        equipe_de_crise.save(update_fields=["leader"])
    equipe_de_crise.membres_encadrement.add(*source.membres_encadrement.all())
    equipe_de_crise.members.add(*source.members.all())
    return True


def equipes_par_point(institution, environment) -> dict:
    """L'équipe permanente que l'organigramme désigne pour chacun des points proposés au
    démarrage d'une crise : `{code du type de point: identifiant d'équipe}`. Vide si rien n'est
    relié. Centre d'accueil et regroupement des moyens la RÉUTILISENT ; la cellule de crise en
    reprend les personnes dans une équipe propre à la crise (voir `composer_depuis_le_plan`)."""
    from .pcs_fiches import FONCTIONS_PAR_POINT

    tenues = {}
    for f in dossier_de(institution, environment).fonctions.filter(equipe__isnull=False, equipe__actif=True):
        tenues.setdefault(f.fonction, f.equipe_id)
    resultat = {}
    for point, fonctions in FONCTIONS_PAR_POINT.items():
        equipe = next((tenues[code] for code in fonctions if code in tenues), None)
        if equipe:
            resultat[point] = str(equipe)
    return resultat


def rassembler(institution, environment, nommer=None) -> dict:
    """Tout ce que le plan de `institution` contient aujourd'hui, et ce qui lui manque.

    `nommer(utilisateur)` rend le nom à imprimer : c'est la vue qui le fournit, parce que le nom
    d'une personne réelle ne s'affiche pas en zone de démonstration et que seule la requête sait
    où l'on est. Pour la même raison, les téléphones personnels des membres ne sortent qu'en
    zone réelle."""
    nommer = nommer or (lambda utilisateur: getattr(utilisateur, "username", "") if utilisateur else "")
    zone_reelle = environment == Environment.PROD
    dossier = dossier_de(institution, environment)
    commune = Commune.objects.filter(code=institution.commune_code).first() if institution.commune_code else None

    risques = [
        {"nom": r.risque_type.nom, "generalites": _texte(r.risque_type.generalites),
         "etat_des_lieux": _texte(r.etat_des_lieux), "enjeux": _texte(r.enjeux)}
        for r in RisqueCommunal.objects.filter(institution=institution, environment=environment, actif=True)
        .select_related("risque_type").order_by("risque_type__nom")
    ]

    enjeux, ressources = {}, {}
    suivis = (SuiviSiteSensible.objects
              .filter(institution=institution, environment=environment, statut=StatutSiteSensible.RETENU)
              .select_related("site").order_by("site__categorie", "site__nom"))
    for suivi in suivis:
        site = suivi.site
        fiche = {"nom": site.nom, "adresse": _texte(site.adresse), "telephone": _texte(site.telephone),
                 "effectif": site.effectif_estime, "observation": _texte(suivi.commentaire)}
        if site.est_ressource:
            ressources.setdefault(site.get_categorie_display(), []).append(fiche)
        if site.est_enjeu or not site.est_ressource:
            enjeux.setdefault(site.get_categorie_display(), []).append(fiche)

    plans = (Plan.objects.filter(institution=institution, environment=environment, actif=True)
             .prefetch_related("zones", "equipes", "points__type", "risques__risque_type",
                               "missions_modeles__equipe", "missions_modeles__referent"))
    dispositifs, points_vus = [], {}
    for plan in plans:
        for point in plan.points.all():
            points_vus[point.id] = point
        dispositifs.append({
            "nom": plan.nom, "description": _texte(plan.description),
            "risques": [r.risque_type.nom for r in plan.risques.all()],
            "zones": [z.nom for z in plan.zones.all()],
            "equipes": [e.name for e in plan.equipes.all()],
            "points": [p.nom for p in plan.points.all()],
            "missions": [
                {"equipe": m.equipe.name, "titre": m.titre, "description": _texte(m.description),
                 "referent": nommer(m.referent) if m.referent_id else "", "priorite": m.get_priorite_display()}
                for m in sorted(plan.missions_modeles.all(), key=lambda m: (m.equipe.name.casefold(), m.titre.casefold()))
            ],
        })

    organisation = [
        {"nom": nommer(c.utilisateur), "fonction": _texte(c.fonction), "principal": c.contact_principal,
         "telephone": _texte(c.utilisateur.phone_number) if zone_reelle else ""}
        for c in ContactInstitution.objects.filter(institution=institution, environment=environment, actif=True)
        .select_related("utilisateur").order_by("-contact_principal", "fonction")
        if c.utilisateur_id
    ]

    annuaire = {}
    interlocuteurs = institution.interlocuteurs_alerte_pcs.filter(environment=environment, actif=True)
    categories_presentes = set()
    for i in interlocuteurs.order_by("categorie", "ordre"):
        categories_presentes.add(i.categorie)
        annuaire.setdefault(i.get_categorie_display(), []).append({
            "nom": _texte(i.nom), "organisme": _texte(i.organisme), "telephone": _texte(i.telephone),
            "email": _texte(i.email), "mode": i.get_mode_alerte_display(),
        })

    equipes = [
        {"nom": e.name, "description": _texte(e.description), "rcsc": e.est_equipe_rcsc,
         "responsable": nommer(e.leader) if e.leader_id else "", "effectif": e.members.count(),
         "competences": sorted(c.nom for c in e.competences.all())}
        for e in Team.objects.filter(institution=institution, environment=environment, actif=True)
        .select_related("leader").prefetch_related("competences", "members").order_by("name")
    ]

    materiels = {}
    for m in (MaterielPoint.objects.filter(point_id__in=list(points_vus)).select_related("item").order_by("nom")):
        libelle = _texte(m.nom) or (m.item.nom if m.item_id else "")
        quantite = f"{m.quantite} {_texte(m.unite)}".strip() if m.quantite is not None else m.get_niveau_stock_display()
        materiels.setdefault(m.point_id, []).append(f"{libelle} : {quantite}" if quantite else libelle)
    points = [
        {"nom": p.nom, "type": p.type.libelle if p.type_id else "", "adresse": _texte(p.adresse),
         "capacite": p.capacite_accueil, "animaux": p.accepte_animaux, "description": _texte(p.description),
         "materiels": materiels.get(p.id, [])}
        for p in sorted(points_vus.values(), key=lambda p: p.nom.casefold())
    ]

    revisions = [
        {"date": r.date, "objet": r.objet, "auteur": nommer(r.auteur) if r.auteur_id else ""}
        for r in dossier.revisions.select_related("auteur")
    ]

    from .pcs_fiches import fiche_type
    fonctions = [
        {"code": f.fonction, "fonction": f.libelle or f.get_fonction_display(),
         **personnes_de_la_fonction(f, nommer, zone_reelle),
         # La fiche de la commune si elle en a écrit une, sinon celle de la trame de l'État.
         "consignes": _texte(f.consignes) or fiche_type(f.fonction), "fiche_propre": bool(_texte(f.consignes))}
        for f in sorted(dossier.fonctions.select_related("equipe__leader").prefetch_related("equipe__membres_encadrement"),
                        key=lambda f: (_ORDRE_FONCTIONS.index(f.fonction) if f.fonction in _ORDRE_FONCTIONS else 99))
    ]
    moyens_alerte = [
        {"type": m.get_type_display(), "description": _texte(m.description), "zone": m.zone.nom if m.zone_id else "",
         "personne": _texte(m.personne), "telephone": _texte(m.personne_telephone)}
        for m in dossier.moyens_alerte.select_related("zone")
    ]
    exercices = [
        {"date": e.date, "theme": e.theme, "deroulement": _texte(e.deroulement),
         "enseignements": _texte(e.enseignements), "actions": _texte(e.actions)}
        for e in dossier.exercices.all()
    ]

    from .models import Zone
    # Les quartiers que la commune a elle-même découpés. La zone « Mon territoire » est créée
    # d'office pour toute collectivité (models._assurer_zone_mon_territoire) : c'est elle qui
    # permet de travailler sans découpage, et elle ne compte donc pas comme un découpage.
    zones = list(Zone.objects.filter(institution=institution, environment=environment, actif=True)
                 .exclude(nom=ZONE_AUTOMATIQUE).values_list("nom", flat=True))

    contenu = {
        "zones": zones,
        "nombre_materiels": sum(len(liste) for liste in materiels.values()),
        "institution": institution.nom,
        "commune": {"nom": (commune.nom if commune else "") or institution.nom,
                    "code": institution.commune_code or "",
                    "population": commune.population if commune else None},
        "risques_recenses": [_texte(r.get("libelle_risque_long")) for r in (commune.risques_territoire if commune else [])
                             if isinstance(r, dict) and r.get("libelle_risque_long")],
        "dossier": {"arrete_numero": dossier.arrete_numero, "arrete_date": dossier.arrete_date,
                    "lieu_pcc": dossier.lieu_pcc, "lieu_pcc_repli": dossier.lieu_pcc_repli,
                    "modalites_activation": _texte(dossier.modalites_activation)},
        "fonctions": fonctions, "moyens_alerte": moyens_alerte, "exercices": exercices,
        "revisions": revisions, "risques": risques, "enjeux": enjeux, "ressources": ressources,
        "dispositifs": dispositifs, "organisation": organisation, "annuaire": annuaire,
        "equipes": equipes, "points": points,
    }
    from .enjeux_exposes import exposes
    contenu["exposition"] = exposes(institution, environment)
    # Les planches ne servent qu'au document : `rassembler` est aussi appelé à chaque
    # affichage de l'écran du plan, qui n'a pas à payer leur préparation.
    contenu["cartes"] = None
    contenu["manques"] = _manques(contenu, categories_presentes)
    return contenu


#: Écran de l'application où se complète chaque partie (voir frontend, admin.routes.ts).
_ROUTES = (
    ("Mon plan de sauvegarde", "/admin/plans"),
    ("Risques de la commune", "/admin/pcs-risques"),
    ("Annuaire de crise", "/admin/pcs-annuaire"),
    ("Zones", "/admin/zones"),
    ("Simulation inondation", "/admin/simulation-inondation"),
    ("Poste de commandement", "/admin/pcs-organisation"),
    ("Alerte de la population", "/admin/pcs-alerte"),
    ("Exercices", "/admin/pcs-exercices"),
    ("Vue Ma Collectivité", "/admin/vue-mairie"),
    ("Sites sensibles", "/admin/sites-sensibles"),
    ("Équipes", "/admin/equipes"),
)

#: Les paragraphes du plan, dans l'ordre du document. Chacun a SON écran (`route`) et dit à quoi
#: il sert une fois la crise ouverte (`reutilise`) : un paragraphe qui ne servirait qu'à remplir
#: un classeur n'aurait pas sa place ici. `compte` est la clé de `contenu` qui dit s'il est
#: renseigné ; `None` quand cela ne se compte pas d'ici (le registre a ses propres droits).
PARAGRAPHES = (
    ("1.1", "Risques de la commune", "/admin/pcs-risques", "risques",
     "Rattachés aux dispositifs qu'ils déclenchent ; repris dans le document et l'information des habitants."),
    ("1.2", "Sites sensibles", "/admin/sites-sensibles", "sites_sensibles",
     "Les enjeux à protéger et les sites ressources, vérifiés par la commune avant d'entrer au plan."),
    ("1.3", "Enjeux exposés à l'inondation", "/admin/pcs-enjeux-exposes", "enjeux_exposes",
     "Dit, pour chaque niveau d'eau, quels sites sensibles et quels lieux d'accueil seraient atteints : à savoir avant d'y envoyer du monde."),
    ("1.2", "Personnes vulnérables", "/admin/personnes-vulnerables", None,
     "Le registre, rangé par quartier, s'édite sur place par les personnes désignées par le maire."),
    ("2.1", "Arrêté, poste de commandement, activation", "/admin/plans", "administratif",
     "Ouvre le document du plan : qui déclenche, où se réunit la cellule de crise."),
    ("2.2", "Poste de commandement et fiches réflexes", "/admin/pcs-organisation", "fonctions",
     "Qui dirige, qui coordonne, qui alerte, avec leurs suppléants : ce qu'on cherche à la première minute, imprimable."),
    ("2.2", "Zones et quartiers", "/admin/zones", "zones",
     "Servent à répartir équipes, points et dispositifs par quartier. Facultatif : sans découpage, tout se fait sur la zone « Mon territoire », créée d'office."),
    ("2.3", "Dispositifs et missions types", "/admin/plans", "dispositifs",
     "Activés en un geste à l'ouverture d'une crise : les équipes reçoivent leurs missions et leurs dossiers."),
    ("2.4", "Annuaire de crise", "/admin/pcs-annuaire", "interlocuteurs",
     "Proposés à l'ouverture d'une crise pour être prévenus ; les envois et les accusés de réception sont suivis."),
    ("2.4", "Alerte de la population", "/admin/pcs-alerte", "moyens_alerte",
     "Les moyens à déclencher et les personnes relais à appeler, quartier par quartier."),
    ("2.5", "Lieux d'accueil et points", "/admin/centres", "points",
     "Ouverts pendant la crise, avec leur capacité et le matériel sur place."),
    ("3.1", "Équipes", "/admin/equipes", "equipes",
     "Reçoivent les missions, ont leur messagerie, alimentent le journal de bord."),
    ("3.2", "Matériel", "/admin/materiel", "materiels",
     "Stocks suivis par point pendant la crise."),
    ("4.5", "Exercices", "/admin/pcs-exercices", "exercices",
     "Ce que chaque exercice a appris, et ce qui doit changer dans le plan."),
)


def paragraphes(compte: dict) -> list[dict]:
    """La table des matières du plan, avec l'état de chaque paragraphe."""
    return [
        {"numero": numero, "titre": titre, "route": route, "reutilise": reutilise,
         "nombre": compte.get(cle) if cle else None,
         "etat": "A_PART" if cle is None else ("RENSEIGNE" if compte.get(cle) else "VIDE")}
        for numero, titre, route, cle, reutilise in PARAGRAPHES
    ]


def _manques(c: dict, categories_presentes: set) -> list[dict]:
    """Ce que le plan ne dit pas encore, avec l'écran où le dire. L'ordre est celui du document."""
    manques = []

    def manque(partie, message, ou):
        # `ou` : le nom de l'écran, pour le document imprimé. `route` : son adresse, pour que
        # l'application y mène d'un geste -- un manque qu'on ne sait pas où combler reste.
        manques.append({"partie": partie, "message": message, "ou": ou,
                        "route": next((route for debut, route in _ROUTES if ou.startswith(debut)), "")})

    dossier = c["dossier"]
    if not (dossier["arrete_numero"] and dossier["arrete_date"]):
        manque("Arrêté", "Le numéro et la date de l'arrêté du maire approuvant le plan ne sont pas renseignés.",
               "Mon plan de sauvegarde")
    dates = [r["date"] for r in c["revisions"]] + ([dossier["arrete_date"]] if dossier["arrete_date"] else [])
    if dates and max(dates) < timezone.localdate() - datetime.timedelta(days=365 * ANS_AVANT_REVISION):
        manque("Mises à jour", f"La dernière mise à jour du plan a plus de {ANS_AVANT_REVISION} ans : il est à revoir.",
               "Mon plan de sauvegarde")
    if not c["risques"]:
        manque("Risques", "Aucun risque n'est déclaré pour la commune.", "Risques de la commune")
    elif any(not (r["etat_des_lieux"] or r["enjeux"]) for r in c["risques"]):
        manque("Risques", "Certains risques déclarés n'ont ni état des lieux ni enjeux rédigés.",
               "Risques de la commune")
    if not c["enjeux"]:
        manque("Enjeux", "Aucun site sensible n'est retenu au plan (écoles, établissements de santé, sites industriels…).",
               "Sites sensibles")
    exposition = c.get("exposition") or {}
    if exposition.get("enjeux") and not exposition.get("simulation_disponible"):
        manque("Enjeux exposés", "La simulation d'inondation n'a pas été lancée pour la commune : on ne sait pas "
               "quels sites et quels lieux d'accueil l'eau atteindrait.", "Simulation inondation")
    if not dossier["modalites_activation"]:
        manque("Activation", "Les modalités d'activation du plan ne sont pas rédigées (qui déclenche, sur quels signaux).",
               "Mon plan de sauvegarde")
    if not dossier["lieu_pcc"]:
        manque("Organisation", "Le lieu du poste de commandement communal n'est pas indiqué.", "Mon plan de sauvegarde")
    if not c.get("zones"):
        manque("Zones", "La commune n'est pas découpée en quartiers. Rien n'en dépend pour ouvrir une crise : "
               f"équipes et dispositifs agissent alors sur la zone « {ZONE_AUTOMATIQUE} », créée d'office.", "Zones")
    from .pcs_fiches import FONCTIONS_ATTENDUES
    tenues = {f["code"] for f in c.get("fonctions", []) if f["titulaire"]}
    if not c.get("fonctions"):
        manque("Poste de commandement", "L'organigramme du poste de commandement communal est vide : on ne sait pas "
               "qui dirige, qui coordonne, qui alerte.", "Poste de commandement")
    elif any(code not in tenues for code in FONCTIONS_ATTENDUES):
        manque("Poste de commandement", "Le maire (directeur des opérations de secours) ou le coordinateur n'a pas "
               "de titulaire nommé.", "Poste de commandement")
    elif any(not f["suppleant"] for f in c["fonctions"]):
        manque("Poste de commandement", "Certaines fonctions n'ont pas de suppléant : une crise dure plus longtemps "
               "qu'une personne.", "Poste de commandement")
    if not c.get("moyens_alerte"):
        manque("Alerte de la population", "Aucun moyen d'alerter la population n'est recensé (sirène, véhicule, "
               "personnes relais…).", "Alerte de la population")
    dernier = max((e["date"] for e in c.get("exercices", [])), default=None)
    if dernier is None:
        manque("Exercices", "Aucun exercice du plan n'est consigné.", "Exercices")
    elif dernier < timezone.localdate() - datetime.timedelta(days=365 * ANS_AVANT_REVISION):
        manque("Exercices", f"Le dernier exercice a plus de {ANS_AVANT_REVISION} ans.", "Exercices")
    if not c["organisation"]:
        manque("Organisation", "Aucun membre de la collectivité n'est déclaré : l'équipe municipale de crise est vide.",
               "Vue Ma Collectivité, membres")
    if not c["dispositifs"]:
        manque("Dispositifs", "Aucun dispositif n'est préparé (zones, équipes et points à activer).", "Mon plan de sauvegarde")
    elif not any(d["missions"] for d in c["dispositifs"]):
        manque("Missions", "Aucun dispositif ne porte de mission type : les équipes n'ont pas de fiche de mission.",
               "Mon plan de sauvegarde")
    absentes = [CategorieInterlocuteurPCS(code).label for code in CATEGORIES_ATTENDUES if code not in categories_presentes]
    if not c["annuaire"]:
        manque("Annuaire de crise", "L'annuaire de crise est vide.", "Annuaire de crise")
    elif absentes:
        manque("Annuaire de crise", "L'annuaire ne contient pas : " + ", ".join(absentes) + ".",
               "Annuaire de crise")
    if not any(p["capacite"] for p in c["points"]):
        manque("Soutien de la population", "Aucun lieu d'accueil avec une capacité n'est rattaché à un dispositif.",
               "Mon plan de sauvegarde, points")
    if not c["equipes"]:
        manque("Moyens humains", "Aucune équipe n'est déclarée.", "Équipes")
    return manques


# ─────────────────────────────── mise en page ───────────────────────────────

_TITRE = ParagraphStyle("pcs_titre", fontName="Helvetica-Bold", fontSize=24, textColor=SOMBRE, leading=30, alignment=1)
_SOUS_TITRE = ParagraphStyle("pcs_sous_titre", fontName="Helvetica", fontSize=13, textColor=GRIS, leading=18, alignment=1)
_H1 = ParagraphStyle("pcs_h1", fontName="Helvetica-Bold", fontSize=15, textColor=SOMBRE, leading=19,
                     spaceBefore=4 * mm, spaceAfter=3 * mm)
_H2 = ParagraphStyle("pcs_h2", fontName="Helvetica-Bold", fontSize=11.5, textColor=SOMBRE, leading=15,
                     spaceBefore=4 * mm, spaceAfter=1.5 * mm)
_H3 = ParagraphStyle("pcs_h3", fontName="Helvetica-Bold", fontSize=9.5, textColor=SOMBRE, leading=13,
                     spaceBefore=2.5 * mm, spaceAfter=1 * mm)
_CORPS = ParagraphStyle("pcs_corps", fontName="Helvetica", fontSize=9.5, textColor=SOMBRE, leading=13, spaceAfter=1.5 * mm)
_NOTE = ParagraphStyle("pcs_note", fontName="Helvetica-Oblique", fontSize=8.5, textColor=GRIS, leading=11.5, spaceAfter=1.5 * mm)
_VIDE = ParagraphStyle("pcs_vide", fontName="Helvetica-Oblique", fontSize=9.5, textColor=colors.HexColor("#b45309"),
                       leading=13, spaceAfter=1.5 * mm)
_ENCART = ParagraphStyle("pcs_encart", fontName="Helvetica", fontSize=9, textColor=SOMBRE, leading=12.5,
                         backColor=FOND_AVERTISSEMENT, borderPadding=(5, 6, 5, 6), spaceBefore=2 * mm, spaceAfter=3 * mm)
_CELLULE = ParagraphStyle("pcs_cellule", fontName="Helvetica", fontSize=8.5, textColor=SOMBRE, leading=10.5)
_ENTETE = ParagraphStyle("pcs_entete", fontName="Helvetica-Bold", fontSize=8, textColor=SOMBRE, leading=10)

_LARGEUR_UTILE = 180 * mm


def _p(texte, style=_CORPS) -> Paragraph:
    """Texte saisi par la commune : repris tel quel, retours à la ligne compris. Échappé, parce
    qu'un « < » dans un état des lieux ferait échouer toute l'édition."""
    return Paragraph(escape(_texte(str(texte))).replace("\n", "<br/>"), style)


def _vide(message, ou) -> Paragraph:
    return Paragraph(f"{escape(message)} <font size=8>À compléter dans : {escape(ou)}.</font>", _VIDE)


def _tableau(entetes, lignes, largeurs) -> Table:
    total = float(sum(largeurs))
    tableau = Table(
        [[Paragraph(e, _ENTETE) for e in entetes]] + [[_p(v, _CELLULE) for v in ligne] for ligne in lignes],
        colWidths=[_LARGEUR_UTILE * l / total for l in largeurs], repeatRows=1,
    )
    tableau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), FOND_ENTETE), ("GRID", (0, 0), (-1, -1), 0.5, FILET),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tableau


def _date(valeur) -> str:
    return valeur.strftime("%d/%m/%Y") if valeur else ""


def _garde(c, horodatage, edite_par):
    commune = c["commune"]
    population = f" — {commune['population']:,} habitants".replace(",", " ") if commune["population"] else ""
    arrete = c["dossier"]
    approbation = (f"Approuvé par arrêté du maire n° {arrete['arrete_numero']} du {_date(arrete['arrete_date'])}"
                   if arrete["arrete_numero"] and arrete["arrete_date"] else "Arrêté d'approbation : non renseigné")
    return [
        Spacer(1, 55 * mm),
        _p("Plan communal de sauvegarde", _TITRE),
        Spacer(1, 6 * mm),
        _p(f"{commune['nom']}{population}", _SOUS_TITRE),
        _p(c["institution"], _SOUS_TITRE),
        Spacer(1, 14 * mm),
        _p(approbation, _SOUS_TITRE),
        Spacer(1, 40 * mm),
        Paragraph(
            "<b>Diffusion restreinte.</b> Ce document contient des coordonnées personnelles et la "
            "liste des enjeux de la commune : il se remet aux membres du dispositif communal et au "
            "préfet, pas au public. L'information des habitants sur les risques relève du DICRIM. "
            "La liste nominative des personnes vulnérables n'y figure pas : elle s'édite à part, "
            "depuis le registre, par les personnes désignées par le maire.", _ENCART),
        _p(f"État des données au {horodatage}, édité par {edite_par}. Ce document est produit à la demande "
           "depuis Assista-Crise : seule l'édition du jour est à jour.", _NOTE),
        PageBreak(),
    ]


def _partie_manques(c):
    blocs = [_p("Ce qui reste à compléter", _H1)]
    if not c["manques"]:
        return blocs + [_p("Toutes les parties du plan sont renseignées.")]
    blocs.append(_p("Ces points sont relevés automatiquement à chaque édition. Tant qu'ils figurent ici, le plan "
                    "ne permet pas de faire ce que la partie concernée annonce.", _NOTE))
    blocs.append(_tableau(("Partie", "Ce qui manque", "Où le compléter"),
                          [(m["partie"], m["message"], m["ou"]) for m in c["manques"]], (28, 100, 52)))
    return blocs


def _partie_revisions(c):
    blocs = [_p("Mises à jour du plan", _H1)]
    if not c["revisions"]:
        return blocs + [_vide("Aucune mise à jour n'est enregistrée.", "Mon plan de sauvegarde")]
    return blocs + [_tableau(("Date", "Objet de la mise à jour", "Par"),
                             [(_date(r["date"]), r["objet"], r["auteur"]) for r in c["revisions"]], (22, 118, 40))]


def _fiches(groupes, vide, ou):
    if not groupes:
        return [_vide(vide, ou)]
    blocs = []
    for categorie, fiches in groupes.items():
        blocs.append(_p(f"{categorie} ({len(fiches)})", _H3))
        blocs.append(_tableau(
            ("Désignation", "Adresse", "Téléphone", "Effectif", "Observations"),
            [(f["nom"], f["adresse"], f["telephone"], f["effectif"] or "", f["observation"]) for f in fiches],
            (48, 58, 26, 14, 34)))
    return blocs


def _niveau(metres) -> str:
    return f"{metres:g} m".replace(".", ",")


def _partie_exposition(c):
    """1.3 — ce que l'eau atteint, d'après la simulation (core/enjeux_exposes.py)."""
    e = c.get("exposition") or {}
    blocs = [_p("1.3 — Enjeux exposés à l'inondation (simulation)", _H2)]
    if not e.get("enjeux"):
        return blocs + [_p("Aucun site sensible ni lieu d'accueil n'est encore au plan : rien à croiser avec la simulation.", _NOTE)]
    if not e.get("simulation_disponible"):
        return blocs + [_vide("La simulation d'inondation n'a pas été lancée pour la commune.", "Simulation inondation")]
    blocs.append(_p(
        f"Hypothèses, pas prévisions : la simulation étend un niveau d'eau sur le relief (jusqu'à {_niveau(e['niveau_max_m'])}) ; "
        "elle ne tient compte ni des digues, ni des réseaux, ni du courant. Elle dit où aller vérifier sur place.", _NOTE))
    lignes = []
    for enjeu in e["enjeux"]:
        if not enjeu["situe"]:
            seuil = "non situé"
        elif enjeu["seuil_m"] is None:
            seuil = f"au sec jusqu'à {_niveau(e['niveau_max_m'])}"
        else:
            seuil = f"atteint à partir de {_niveau(enjeu['seuil_m'])}"
        lignes.append((enjeu["nom"], enjeu["nature"], enjeu["categorie"], enjeu["effectif"] or "", seuil,
                       enjeu.get("zone_officielle") or ""))
    blocs.append(_tableau(("Désignation", "Nature", "Catégorie", "Effectif ou capacité", "Niveau d'eau (simulation)",
                           "Zone inondable officielle"), lignes, (44, 26, 30, 20, 30, 30)))
    officiel = e.get("zonages_officiels") or {}
    if not officiel.get("releve"):
        blocs.append(_p("Les zones inondables officielles de l'État (Géorisques) n'ont pas été relevées pour la commune : "
                        "la dernière colonne est vide.", _NOTE))
    elif not any(couche["presente"] for couche in officiel["couches"]):
        blocs.append(_p("Géorisques ne publie pas de zone inondable cartographiée pour cette commune (hors territoire à "
                        "risque important d'inondation) : cela ne veut pas dire qu'il n'y a pas de risque.", _NOTE))
    return blocs


def _partie_risques(c):
    blocs = [_p("1 — Identification des risques sur la commune", _H1), _p("1.1 — Aléas", _H2)]
    if c["risques_recenses"]:
        blocs.append(_p("Risques recensés par l'État pour la commune (Géorisques) : " + ", ".join(c["risques_recenses"]) + "."))
    if not c["risques"]:
        blocs.append(_vide("Aucun risque n'est déclaré par la commune.", "Risques de la commune"))
    for risque in c["risques"]:
        blocs.append(_p(risque["nom"], _H3))
        if risque["generalites"]:
            blocs.append(_p(risque["generalites"]))
        if risque["etat_des_lieux"]:
            blocs += [_p("État des lieux sur la commune", _ENTETE), _p(risque["etat_des_lieux"])]
        if risque["enjeux"]:
            blocs += [_p("Enjeux", _ENTETE), _p(risque["enjeux"])]
    blocs.append(_p("1.2 — Vulnérabilités et enjeux", _H2))
    blocs += _fiches(c["enjeux"], "Aucun site sensible n'est retenu au plan.", "Sites sensibles")
    blocs += _partie_exposition(c)
    blocs.append(_p("Populations nécessitant une attention particulière", _H3))
    blocs.append(_p("Elles figurent au registre communal des personnes vulnérables. Leur liste nominative s'édite "
                    "séparément, depuis l'écran « Personnes vulnérables », par les seules personnes désignées par le "
                    "maire et engagées au secret professionnel (art. R. 121-7 du code de l'action sociale et des "
                    "familles).", _NOTE))
    return blocs


def _partie_organisation(c):
    dossier = c["dossier"]
    blocs = [_p("2 — Organiser la réponse communale", _H1), _p("2.1 — Modalités d'activation du plan", _H2)]
    blocs.append(_p(dossier["modalites_activation"]) if dossier["modalites_activation"]
                 else _vide("Les modalités d'activation ne sont pas rédigées.", "Mon plan de sauvegarde"))

    blocs.append(_p("2.2 — Organisation du dispositif communal", _H2))
    if dossier["lieu_pcc"]:
        repli = f" Lieu de repli : {dossier['lieu_pcc_repli']}." if dossier["lieu_pcc_repli"] else ""
        blocs.append(_p(f"Poste de commandement communal : {dossier['lieu_pcc']}.{repli}"))
    else:
        blocs.append(_vide("Le lieu du poste de commandement communal n'est pas indiqué.", "Mon plan de sauvegarde"))
    if c.get("fonctions"):
        blocs.append(_tableau(
            ("Fonction", "Équipe", "Titulaire", "Téléphone", "Suppléant", "Téléphone"),
            [(f["fonction"], f.get("equipe", ""), f["titulaire"], f["titulaire_telephone"], f["suppleant"],
              f["suppleant_telephone"]) for f in c["fonctions"]], (46, 30, 30, 24, 28, 22)))
    else:
        blocs.append(_vide("L'organigramme du poste de commandement communal est vide.", "Poste de commandement"))
    blocs.append(_p("Membres de la collectivité inscrits dans l'application", _H3))
    if c["organisation"]:
        blocs.append(_tableau(("Nom", "Fonction", "Téléphone"),
                              [(o["nom"] + (" (contact principal)" if o["principal"] else ""), o["fonction"], o["telephone"])
                               for o in c["organisation"]], (70, 70, 40)))
    else:
        blocs.append(_vide("Aucun membre de la collectivité n'est déclaré.", "Vue Ma Collectivité, membres"))

    blocs.append(_p("2.3 — Dispositifs préparés et missions des équipes", _H2))
    if not c["dispositifs"]:
        blocs.append(_vide("Aucun dispositif n'est préparé.", "Mon plan de sauvegarde"))
    for d in c["dispositifs"]:
        blocs.append(_p(d["nom"], _H3))
        if d["description"]:
            blocs.append(_p(d["description"]))
        for libelle, valeurs in (("Risques couverts", d["risques"]), ("Zones", d["zones"]),
                                 ("Équipes", d["equipes"]), ("Points", d["points"])):
            if valeurs:
                blocs.append(_p(f"{libelle} : " + ", ".join(valeurs) + "."))
        if d["missions"]:
            blocs.append(_tableau(("Équipe", "Mission", "Consigne", "Référent", "Priorité"),
                                  [(m["equipe"], m["titre"], m["description"], m["referent"], m["priorite"])
                                   for m in d["missions"]], (32, 40, 64, 28, 16)))
        else:
            blocs.append(_p("Aucune mission type : à l'activation, les équipes n'auront pas de fiche de mission.", _NOTE))

    blocs.append(_p("2.4 — Organisation de l'alerte", _H2))
    blocs.append(_p("Les interlocuteurs ci-dessous sont prévenus à l'ouverture d'une crise ; l'application suit les "
                    "envois et les accusés de réception. L'alerte de la population par FR-Alert relève du préfet.", _NOTE))
    blocs.append(_p("Moyens d'alerte de la population", _H3))
    if c.get("moyens_alerte"):
        blocs.append(_tableau(("Moyen", "Lieu, circuit ou liste", "Quartier", "Personne", "Téléphone"),
                              [(m["type"], m["description"], m["zone"], m["personne"], m["telephone"])
                               for m in c["moyens_alerte"]], (36, 58, 28, 32, 26)))
    else:
        blocs.append(_vide("Aucun moyen d'alerte de la population n'est recensé.", "Alerte de la population"))
    blocs.append(_p("Interlocuteurs à prévenir", _H3))
    blocs += _annuaire(c)

    blocs.append(_p("2.5 — Soutien des populations : lieux d'accueil et de regroupement", _H2))
    if not c["points"]:
        blocs.append(_vide("Aucun point n'est rattaché à un dispositif.", "Mon plan de sauvegarde, points"))
    else:
        blocs.append(_tableau(
            ("Lieu", "Type", "Adresse", "Capacité", "Animaux", "Matériel sur place"),
            [(p["nom"], p["type"], p["adresse"], p["capacite"] or "", "oui" if p["animaux"] else "non",
              "\n".join(p["materiels"])) for p in c["points"]], (34, 24, 42, 16, 18, 46)))
    return blocs


def _annuaire(c):
    if not c["annuaire"]:
        return [_vide("L'annuaire de crise est vide.", "Annuaire de crise")]
    blocs = []
    for categorie, contacts in c["annuaire"].items():
        blocs.append(_p(categorie, _H3))
        blocs.append(_tableau(("Nom", "Organisme", "Téléphone", "Courriel", "Prévenu par"),
                              [(i["nom"], i["organisme"], i["telephone"], i["email"], i["mode"]) for i in contacts],
                              (40, 40, 30, 44, 26)))
    return blocs


def _partie_moyens(c):
    blocs = [_p("3 — Recensement des moyens", _H1), _p("3.1 — Moyens humains", _H2)]
    if c["equipes"]:
        blocs.append(_tableau(
            ("Équipe", "Responsable", "Effectif", "Compétences"),
            [(e["nom"] + (" (réserve communale)" if e["rcsc"] else ""), e["responsable"], e["effectif"],
              ", ".join(e["competences"])) for e in c["equipes"]], (52, 40, 16, 72)))
    else:
        blocs.append(_vide("Aucune équipe n'est déclarée.", "Équipes"))
    blocs.append(_p("3.2 — Moyens matériels et sites ressources", _H2))
    blocs.append(_p("Le matériel entreposé figure avec chaque lieu d'accueil (partie 2.5).", _NOTE))
    blocs += _fiches(c["ressources"], "Aucun site ressource n'est retenu (transport, engins, hébergement, approvisionnement…).",
                     "Sites sensibles")
    return blocs


def _partie_annexes(c):
    blocs = [_p("4 — Annexes", _H1), _p("4.2 — Fiches réflexes", _H2)]
    if not c.get("fonctions"):
        blocs.append(_vide("Aucune fonction n'est déclarée : il n'y a pas de fiche réflexe à éditer.", "Poste de commandement"))
    for f in c.get("fonctions", []):
        titulaire = f" — {f['titulaire']}" if f["titulaire"] else ""
        blocs.append(_p(f"Fiche {f['fonction']}{titulaire}", _H3))
        blocs.append(_p(f["consignes"]) if f["consignes"] else _p("Fiche à rédiger.", _NOTE))
    blocs.append(_p("4.5 — Exercices", _H2))
    if not c.get("exercices"):
        blocs.append(_vide("Aucun exercice n'est consigné.", "Exercices"))
    for e in c.get("exercices", []):
        blocs.append(_p(f"{_date(e['date'])} — {e['theme']}", _H3))
        for libelle, texte in (("Déroulement", e["deroulement"]), ("Enseignements", e["enseignements"]),
                               ("À changer dans le plan", e["actions"])):
            if texte:
                blocs += [_p(libelle, _ENTETE), _p(texte)]
    return blocs


def _partie_cartes(c):
    """Les planches en annexe (core/cartes_pcs.py) : schémas à l'échelle, repères numérotés."""
    cartes = c.get("cartes")
    if not cartes or not (cartes["planche_plan"] or cartes["planche_eau"]):
        return []
    blocs = []
    if cartes["planche_plan"]:
        blocs += [PageBreak(), _p("Carte 1 — Quartiers et lieux du plan", _H2), cartes["planche_plan"], Spacer(1, 2 * mm),
                  _p("Trait fort : territoire de la commune. Traits fins : quartiers"
                     + (f" ({', '.join(cartes['quartiers'])})" if cartes["quartiers"] else " (aucun n'est encore dessiné)")
                     + ". Carrés verts : lieux d'accueil et points des dispositifs. Ronds orange : sites sensibles.", _NOTE)]
    if cartes["planche_eau"]:
        median, haut = cartes["niveaux"] if cartes["niveaux"] else (None, None)
        legende = []
        if haut is not None:
            legende.append(f"Bleu clair : zone inondée simulée à {_niveau(haut)}"
                           + (f" ; bleu soutenu : à {_niveau(median)}" if median != haut else "")
                           + " (hypothèses, sans digues ni courant)")
        if cartes["zonage_officiel"]:
            legende.append(f"Tirets rouges : zone inondable officielle, {cartes['zonage_officiel']} (Géorisques)")
        legende.append("Repères bleus : enjeux atteints par l'eau simulée ou situés en zone officielle")
        blocs += [PageBreak(), _p("Carte 2 — Zones inondables et enjeux", _H2), cartes["planche_eau"], Spacer(1, 2 * mm),
                  _p(". ".join(legende) + ".", _NOTE)]
    if cartes["reperes"]:
        lignes = []
        for r in cartes["reperes"]:
            eau = f"dès {_niveau(r['seuil_m'])}" if r["seuil_m"] is not None else ""
            lignes.append((str(r["numero"]), r["nom"], r["nature"], eau, r["zone_officielle"]))
        blocs += [Spacer(1, 3 * mm), _p("Repères des cartes", _H3),
                  _tableau(("N°", "Désignation", "Nature", "Eau simulée", "Zone officielle"), lignes, (10, 70, 40, 25, 35))]
    return blocs


def generer_pdf(contenu: dict, *, edite_par: str, edite_le=None) -> bytes:
    """Le plan mis en page, en A4 portrait. `contenu` vient de `rassembler`."""
    edite_le = timezone.localtime(edite_le or timezone.now())
    horodatage = edite_le.strftime("%d/%m/%Y à %H:%M")
    commune = contenu["commune"]["nom"]
    pied = f"Plan communal de sauvegarde — {commune} — état au {horodatage}, édité par {edite_par} — diffusion restreinte"

    blocs = _garde(contenu, horodatage, edite_par)
    blocs += _partie_manques(contenu)
    blocs += _partie_revisions(contenu)
    blocs.append(PageBreak())
    blocs += _partie_risques(contenu)
    blocs.append(PageBreak())
    blocs += _partie_organisation(contenu)
    blocs.append(PageBreak())
    blocs += _partie_moyens(contenu)
    blocs.append(PageBreak())
    blocs += _partie_annexes(contenu)
    blocs += _partie_cartes(contenu)

    tampon = io.BytesIO()
    document = SimpleDocTemplate(
        tampon, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=17 * mm,
        title=f"Plan communal de sauvegarde — {commune}", author=edite_par,
    )
    document.build(blocs, canvasmaker=lambda *args, **kwargs: _CanevasNumerote(*args, pied=pied, **kwargs))
    return tampon.getvalue()


# ──────────────────── DICRIM : l'information des habitants sur les risques ────────────────────

#: Consignes générales diffusées par les pouvoirs publics, valables quel que soit le risque.
CONSIGNES_GENERALES = (
    "Mettez-vous à l'abri et suivez les consignes des autorités.",
    "Informez-vous : radio locale, site et panneaux de la commune.",
    "N'allez pas chercher vos enfants à l'école : les enseignants s'en occupent.",
    "Ne téléphonez qu'en cas d'urgence : laissez les lignes libres pour les secours.",
    "Préparez de quoi tenir trois jours : eau, nourriture, lampe, radio à piles, médicaments, papiers.",
)

NUMEROS_URGENCE = (("112", "Numéro d'urgence européen"), ("18", "Sapeurs-pompiers"), ("15", "SAMU"),
                   ("17", "Police, gendarmerie"), ("114", "Urgence par SMS pour les personnes sourdes ou malentendantes"))


def generer_dicrim(contenu: dict, *, edite_le=None) -> bytes:
    """Le document d'information communal sur les risques majeurs, à remettre aux habitants.

    Public par nature : il ne reprend du plan que ce qui peut être affiché en mairie -- les
    risques et ce que la commune en a écrit, la façon dont elle alerte, les lieux d'accueil, les
    consignes. **Aucun nom, aucun téléphone personnel, aucun enjeu nominatif** : l'annuaire, les
    personnes relais et les sites sensibles restent dans le plan, à diffusion restreinte."""
    edite_le = timezone.localtime(edite_le or timezone.now())
    commune = contenu["commune"]["nom"]
    pied = f"Document d'information communal sur les risques majeurs — {commune} — édition du {edite_le:%d/%m/%Y}"

    blocs = [
        Spacer(1, 30 * mm), _p("Risques majeurs : s'informer pour se protéger", _TITRE), Spacer(1, 5 * mm),
        _p(f"Document d'information communal — {commune}", _SOUS_TITRE), Spacer(1, 14 * mm),
        _p("Ce document vous dit à quels risques la commune est exposée, comment vous serez alerté, "
           "où vous rendre et ce qu'il faut faire. Gardez-le à portée de main."),
        _p("Les risques sur la commune", _H1),
    ]
    if contenu["risques_recenses"]:
        blocs.append(_p("Risques recensés par l'État pour la commune : " + ", ".join(contenu["risques_recenses"]) + "."))
    if not contenu["risques"]:
        blocs.append(_p("La commune n'a pas encore détaillé ses risques.", _NOTE))
    for risque in contenu["risques"]:
        blocs.append(_p(risque["nom"], _H2))
        for texte in (risque["generalites"], risque["etat_des_lieux"]):
            if texte:
                blocs.append(_p(texte))

    blocs.append(_p("Comment vous serez alerté", _H1))
    moyens = sorted({m["type"] for m in contenu.get("moyens_alerte", [])})
    if moyens:
        blocs.append(_p("La commune dispose des moyens suivants : " + ", ".join(m.lower() for m in moyens) + "."))
    blocs.append(_p("En cas de danger grave, vous pouvez aussi recevoir une notification FR-Alert sur votre téléphone, "
                    "envoyée par le préfet : aucune inscription n'est nécessaire."))

    lieux = [p for p in contenu["points"] if p["capacite"]]
    if lieux:
        blocs.append(_p("Où vous rendre", _H1))
        blocs.append(_tableau(("Lieu d'accueil", "Adresse", "Animaux acceptés"),
                              [(p["nom"], p["adresse"], "oui" if p["animaux"] else "non") for p in lieux], (60, 90, 30)))
        blocs.append(_p("Le lieu ouvert le jour de l'événement vous sera indiqué au moment de l'alerte.", _NOTE))

    blocs.append(_p("Ce qu'il faut faire", _H1))
    blocs += [_p(f"• {consigne}") for consigne in CONSIGNES_GENERALES]
    blocs.append(_p("Numéros d'urgence", _H1))
    blocs.append(_tableau(("Numéro", "Pour joindre"), NUMEROS_URGENCE, (30, 150)))

    tampon = io.BytesIO()
    document = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                                 bottomMargin=17 * mm, title=f"DICRIM — {commune}")
    document.build(blocs, canvasmaker=lambda *args, **kwargs: _CanevasNumerote(*args, pied=pied, **kwargs))
    return tampon.getvalue()


def texte_public_du_dicrim(contenu: dict) -> str:
    """Tout ce que le DICRIM tire du plan, à plat : sert à vérifier qu'aucune donnée personnelle
    n'y entre (voir les tests)."""
    morceaux = [contenu["commune"]["nom"], *contenu["risques_recenses"]]
    for risque in contenu["risques"]:
        morceaux += [risque["nom"], risque["generalites"], risque["etat_des_lieux"]]
    morceaux += sorted({m["type"] for m in contenu.get("moyens_alerte", [])})
    for point in contenu["points"]:
        if point["capacite"]:
            morceaux += [point["nom"], point["adresse"]]
    return "\n".join(morceaux)
