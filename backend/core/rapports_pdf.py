"""Rapports en PDF : un dossier, une mission, une crise pour une collectivité.

**À quoi ils servent.** Après un sinistre, une personne comme une commune doit monter un dossier
pour son assureur, et la commune un dossier de reconnaissance de catastrophe naturelle : ce qui
s'est passé, quand, ce qui a été constaté, ce qui a été fait, avec les photos. Tout cela est
déjà dans l'application, dispersé entre les écrans. Ces rapports le rassemblent et le
prérédigent : il reste à relire, pas à recopier.

- **Rapport de dossier** : la demande d'origine, le bien concerné et l'état des dégâts relevé,
  la chronologie de la prise en charge, les observations, les photos en annexe.
- **Rapport de mission** : l'objectif, les équipes, les dossiers traités, et en annexe le
  résumé de chaque dossier et leurs photos.
- **Rapport de bien sinistré** : pour ce qui n'est pas une habitation — une voiture brûlée, un
  bateau, un hangar — ce que c'est, où il était, la cause et l'état du dommage, les photos.
- **Rapport de crise pour une collectivité** : la période, les chiffres, les moyens engagés,
  l'état des dégâts sur les habitations, les alertes diffusées, le journal de bord ; en annexe
  les missions, les dossiers et les photos.

**Ce qu'ils sont, et ce qu'ils ne sont pas.** Ils restituent ce qui a été enregistré, avec les
dates et les auteurs. Ils ne chiffrent pas un préjudice et ne valent pas expertise ; chaque
rapport le dit. Les valeurs de biens affichées sont indicatives et marquées comme telles.

**Gardés jusqu'à la clôture, pas au-delà.** Le rapport est construit à la demande ; sa dernière
édition est gardée sur le serveur, chiffrée, jusqu'à la clôture de sa crise, puis effacée
(core/cloture_crise.py). Chaque édition est inscrite à la main courante, et chaque page porte le
nom de qui l'a éditée.

**À éditer avant la clôture.** La clôture se propose sept jours à l'avance, et chacun reçoit
alors un lien pour se faire envoyer son rapport : c'est le moment de sortir aussi le rapport de
crise. Après, les rapports gardés sont effacés.

**Les photos sont réduites** (1 400 points de large au plus) et, par défaut, plafonnées par
rapport : un dossier de vingt photos de téléphone ferait sinon un fichier que personne ne peut
envoyer. À l'édition, on peut demander **toutes les photos** : le plafond tombe, pas la réduction.
Chaque photo porte son empreinte numérique quand elle est connue, pour qu'on puisse établir que
c'est bien le fichier déposé ce jour-là.
"""
import io
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .registre_vulnerables_pdf import _CanevasNumerote

SOMBRE = colors.HexColor("#1e293b")
GRIS = colors.HexColor("#6b7280")
FILET = colors.HexColor("#d1d5db")
FOND = colors.HexColor("#e2e8f0")
FOND_NOTE = colors.HexColor("#fef3c7")

#: Photos par rapport. Au-delà, le rapport dit combien n'y figurent pas.
MAX_PHOTOS = {"dossier": 40, "mission": 60, "crise": 80, "bien": 40, "pret": 30}
LARGEUR_PHOTO_PX = 1400
#: Dossiers détaillés en annexe d'un rapport de mission ou de crise.
MAX_DOSSIERS_ANNEXES = 150
MAX_LIGNES_JOURNAL = 400

MENTION = (
    "<b>Portée de ce document.</b> Il restitue ce qui a été enregistré dans l'application, avec les dates et les "
    "auteurs des enregistrements. Il peut être joint à une déclaration de sinistre ou à un dossier de reconnaissance "
    "de l'état de catastrophe naturelle. Il ne chiffre pas un préjudice et ne vaut pas expertise : les valeurs de "
    "biens qui y figurent sont indicatives."
)

_TITRE = ParagraphStyle("r_titre", fontName="Helvetica-Bold", fontSize=18, textColor=SOMBRE, leading=23)
_SOUS_TITRE = ParagraphStyle("r_sous_titre", fontName="Helvetica", fontSize=10.5, textColor=GRIS, leading=14)
_H1 = ParagraphStyle("r_h1", fontName="Helvetica-Bold", fontSize=13, textColor=SOMBRE, leading=17, spaceBefore=6 * mm, spaceAfter=2 * mm)
_H2 = ParagraphStyle("r_h2", fontName="Helvetica-Bold", fontSize=10.5, textColor=SOMBRE, leading=14, spaceBefore=4 * mm, spaceAfter=1.5 * mm)
_CORPS = ParagraphStyle("r_corps", fontName="Helvetica", fontSize=9.5, textColor=SOMBRE, leading=13, spaceAfter=1.5 * mm)
_NOTE = ParagraphStyle("r_note", fontName="Helvetica-Oblique", fontSize=8.5, textColor=GRIS, leading=11.5, spaceAfter=1.5 * mm)
_MENTION = ParagraphStyle("r_mention", fontName="Helvetica", fontSize=8.5, textColor=SOMBRE, leading=11.5,
                          backColor=FOND_NOTE, borderPadding=(5, 6, 5, 6), spaceBefore=3 * mm, spaceAfter=3 * mm)
_CELLULE = ParagraphStyle("r_cellule", fontName="Helvetica", fontSize=8.5, textColor=SOMBRE, leading=10.5)
_CELLULE_FORTE = ParagraphStyle("r_cellule_forte", parent=_CELLULE, fontName="Helvetica-Bold")
_ENTETE = ParagraphStyle("r_entete", fontName="Helvetica-Bold", fontSize=8, textColor=SOMBRE, leading=10)
_LEGENDE = ParagraphStyle("r_legende", fontName="Helvetica", fontSize=7.5, textColor=GRIS, leading=9.5)
_LARGEUR = 180 * mm


# ───────────────────────────────── ce que l'on rassemble ─────────────────────────────────

def _date(valeur, heure=True) -> str:
    if not valeur:
        return ""
    if hasattr(valeur, "hour"):
        return timezone.localtime(valeur).strftime("%d/%m/%Y à %H:%M" if heure else "%d/%m/%Y")
    return valeur.strftime("%d/%m/%Y")


def _duree(debut, fin) -> str:
    if not debut or not fin or fin < debut:
        return ""
    minutes = int((fin - debut).total_seconds() // 60)
    jours, reste = divmod(minutes, 1440)
    heures, minutes = divmod(reste, 60)
    if jours:
        return f"{jours} j {heures} h"
    return f"{heures} h {minutes:02d}" if heures else f"{minutes} min"


def _photo(champ, legende, quand=None, empreinte="") -> dict | None:
    """Ce qu'il faut pour poser une photo en annexe, ou None si le fichier n'est pas lisible."""
    if not champ:
        return None
    return {"champ": champ, "legende": legende, "date": _date(quand), "empreinte": empreinte or ""}


def photos_du_dossier(dossier) -> list[dict]:
    """Les photos qui documentent un dossier : celles de la demande ou du signalement d'origine,
    puis les pièces déposées sur le dossier et sur l'habitation concernée."""
    photos = []
    demande = dossier.demande
    if demande is not None:
        photos.append(_photo(demande.photo, "Photo jointe à la demande", demande.created_at))
        for photo in demande.photos.all():
            photos.append(_photo(photo.image, "Photo jointe à la demande", photo.date_ajout))
    if dossier.information is not None:
        photos.append(_photo(dossier.information.photo, "Photo jointe au signalement", dossier.information.created_at))
    sources = [(dossier.documents.all(), "Pièce déposée sur le dossier")]
    if dossier.habitation is not None:
        sources.append((dossier.habitation.documents.all(), "Pièce déposée sur l'habitation"))
    for documents, nature in sources:
        for document in documents:
            legende = nature + (f" — {document.commentaire}" if document.commentaire else "")
            photos.append(_photo(document.fichier, legende, document.date_upload, document.sha256))
    return [photo for photo in photos if photo]


def dossier_resume(dossier, nommer) -> dict:
    """Tout ce qu'un rapport dit d'un dossier. `nommer(utilisateur)` rend un nom affichable."""
    habitation = dossier.habitation
    bien = None
    if habitation is not None:
        bien = {
            "adresse": habitation.adresse or "", "commune": habitation.commune_nom or "",
            "parcelle": habitation.parcelle_cadastrale or "",
            "evaluation": habitation.get_statut_evaluation_display(),
            "nature": habitation.get_nature_degats_display() if habitation.nature_degats else "",
            "chantier": habitation.get_statut_chantier_display() if habitation.statut_chantier else "",
            "evalue_le": _date(habitation.date_derniere_evaluation),
            "evalue_par": nommer(habitation.evalue_par) if habitation.evalue_par_id else "",
            "surfaces": [(libelle, totale, impactee) for libelle, totale, impactee in (
                ("Habitable", habitation.surface_habitable_totale, habitation.surface_habitable_impactee),
                ("Non habitable (annexes, garage…)", habitation.surface_non_habitable_totale, habitation.surface_non_habitable_impactee),
            ) if totale is not None or impactee is not None],
            "valeur": habitation.valeur_estimee, "valeur_source": habitation.valeur_source or "",
            "observations": [(_date(c.date_creation), nommer(c.auteur) if c.auteur_id else "", c.commentaire)
                             for c in habitation.commentaires.select_related("auteur").order_by("date_creation")],
        }
    origine = None
    if dossier.demande is not None:
        demande = dossier.demande
        origine = {"nature": "Demande d'aide", "titre": demande.title, "description": demande.description or "",
                   "type": str(demande.request_type) if demande.request_type_id else "", "recue_le": _date(demande.created_at),
                   "demandeur": f"{demande.first_name_request or ''} {demande.last_name_request or ''}".strip()}
    elif dossier.information is not None:
        information = dossier.information
        origine = {"nature": "Signalement", "titre": information.title, "description": "",
                   "type": str(information.information_type) if information.information_type_id else "",
                   "recue_le": _date(information.created_at), "demandeur": ""}
    return {
        "numero": dossier.numero, "titre": dossier.titre, "description": dossier.description or "",
        "statut": dossier.get_statut_display(), "clos": dossier.statut == dossier.Statut.CLOTURE,
        "priorite": dossier.get_priorite_display() if dossier.priorite else "",
        "crise": dossier.crise.name if dossier.crise_id else "",
        "competence": str(dossier.competence) if dossier.competence_id else "",
        "equipe": dossier.equipe.name if dossier.equipe_id else "",
        "mission": dossier.mission.titre if dossier.mission_id else "",
        "demandeur_institution": dossier.institution_demandeuse.nom if dossier.institution_demandeuse_id else "",
        "cree_le": _date(dossier.date_creation), "affecte_le": _date(dossier.date_affectation),
        "resolu_le": _date(dossier.date_resolution), "cloture_le": _date(dossier.date_cloture),
        "duree": _duree(dossier.date_creation, dossier.date_cloture or dossier.date_resolution),
        "origine": origine, "bien": bien,
        "chronologie": [(_date(h.date_creation), nommer(h.auteur) if h.auteur_id else "", h.evenement, h.commentaire or "")
                        for h in dossier.historique.select_related("auteur").order_by("date_creation")],
        "observations": [(_date(c.date_creation), nommer(c.auteur) if c.auteur_id else "", c.commentaire)
                         for c in dossier.commentaires.select_related("auteur").order_by("date_creation")],
        "photos": photos_du_dossier(dossier),
    }


def bien_resume(bien, nommer) -> dict:
    """Tout ce que le rapport dit d'un bien sinistré autre qu'une habitation."""
    return {
        "designation": bien.designation, "type": bien.get_type_bien_display(), "identification": bien.identification or "",
        "description": bien.description or "", "adresse": bien.adresse or "",
        "position": f"{bien.location.y:.5f}, {bien.location.x:.5f}" if bien.location else "",
        "etat": bien.get_statut_evaluation_display(), "detruit": bien.statut_evaluation == "DETRUITE",
        "nature": bien.get_nature_degats_display() if bien.nature_degats else "",
        "crise": bien.crise.name if bien.crise_id else "",
        "releve_par": nommer(bien.cree_par) if bien.cree_par_id else "",
        "releve_le": _date(bien.date_creation), "modifie_le": _date(bien.modifie_le),
        "collectivite": bien.institution.nom if bien.institution_id else "",
        "proprietaire": bien.proprietaire_nom or "",
        "photos": [p for p in (_photo(d.fichier, "Photo du bien" + (f" — {d.commentaire}" if d.commentaire else ""),
                                      d.date_upload, d.sha256) for d in bien.documents.order_by("date_upload")) if p],
    }


def _dossiers_prets(queryset):
    return (queryset.select_related("crise", "competence", "equipe", "mission", "demande", "information", "habitation",
                                    "institution_demandeuse")
            .prefetch_related("documents", "demande__photos", "habitation__documents").order_by("date_creation"))


def mission_resume(mission, nommer, dossiers=None) -> dict:
    dossiers = list(_dossiers_prets(mission.dossiers.all()) if dossiers is None else dossiers)
    return {
        "titre": mission.titre, "description": mission.description or "", "statut": mission.get_statut_display(),
        "close": mission.statut == mission.Statut.TERMINEE,
        "crise": mission.crise.name if mission.crise_id else "",
        "institution": mission.institution.nom if mission.institution_id else "",
        "interet_general": mission.interet_general,
        "equipes": sorted(equipe.name for equipe in mission.equipes.all()),
        "creee_le": _date(mission.date_creation), "cloturee_le": _date(mission.date_cloture),
        "duree": _duree(mission.date_creation, mission.date_cloture),
        "dossiers": [dossier_resume(dossier, nommer) for dossier in dossiers[:MAX_DOSSIERS_ANNEXES]],
        "dossiers_omis": max(0, len(dossiers) - MAX_DOSSIERS_ANNEXES),
    }


def _bilan_stock(institution, crise, environment) -> dict:
    from . import stocks
    return stocks.bilan_de_crise(institution, crise, environment)


def _blocs_stock(c: dict, numero: int) -> list:
    """Matériel et dons de la crise : ce qui a été distribué depuis le stock, ce qui y est entré."""
    stock = c.get("stock") or {}
    if not stock.get("distribue") and not stock.get("recu"):
        return []
    euros = lambda v: (f"{v:.2f} €".replace(".", ",") if v is not None else "")       # noqa: E731
    blocs = [_p(f"{numero} — Matériel et dons", _H1)]
    if stock["distribue"]:
        blocs += [_p("Distribué ou consommé depuis le stock de la collectivité", _H2),
                  _tableau(("Article", "Quantité", "Valeur indicative"),
                           [(l["designation"], f"{l['quantite']} {l['unite']}", euros(l["valeur"])) for l in stock["distribue"]], (110, 35, 35))]
        if stock["valeur_distribuee"]:
            blocs.append(_p(f"Valeur indicative de ce qui a été distribué : {euros(stock['valeur_distribuee'])} (coût moyen des articles).", _NOTE))
    if stock["recu"]:
        blocs += [_p("Reçu pour la crise (dons, apports, achats)", _H2),
                  _tableau(("Article", "Quantité", "Valeur indicative"),
                           [(l["designation"], f"{l['quantite']} {l['unite']}", euros(l["valeur"])) for l in stock["recu"]], (110, 35, 35))]
    return blocs


def crise_resume(crise, institution, environment, nommer) -> dict:
    """La crise vue par UNE collectivité : ce qui relève de sa commune, de ses équipes et de ce
    qu'elle a elle-même consigné. Une autre collectivité touchée par la même crise édite le sien."""
    from django.db.models import Q

    from .models import AlertePopulation, Dossier, Habitation, Information, JournalCollectivite, Mission, Request

    commune = institution.commune_code or ""
    a_nous = Q(institution_demandeuse=institution) | Q(equipe__institution=institution)
    if commune:
        a_nous |= Q(demande__commune_code=commune) | Q(information__commune_code=commune)
    dossiers = list(_dossiers_prets(Dossier.objects.filter(a_nous, crise=crise, environment=environment).distinct()))
    missions = list(Mission.objects.filter(
        Q(institution=institution) | Q(equipes__institution=institution), crise=crise, environment=environment)
        .distinct().select_related("crise", "institution").prefetch_related("equipes").order_by("date_creation"))
    par_mission = {}
    for dossier in dossiers:
        par_mission.setdefault(dossier.mission_id, []).append(dossier)

    habitations = list(Habitation.objects.filter(crise=crise, environment=environment, **({"commune_code": commune} if commune else {})))
    degats, causes = {}, {}
    for habitation in habitations:
        if habitation.nature_degats:
            causes[habitation.get_nature_degats_display()] = causes.get(habitation.get_nature_degats_display(), 0) + 1
        ligne = degats.setdefault(habitation.get_statut_evaluation_display(), {"nombre": 0, "habitable": 0.0, "annexes": 0.0, "valeur": 0})
        ligne["nombre"] += 1
        ligne["habitable"] += habitation.surface_habitable_impactee or 0
        ligne["annexes"] += habitation.surface_non_habitable_impactee or 0
        ligne["valeur"] += float(habitation.valeur_estimee or 0)

    par_statut = {}
    for dossier in dossiers:
        par_statut[dossier.get_statut_display()] = par_statut.get(dossier.get_statut_display(), 0) + 1
    journal = list(JournalCollectivite.objects.filter(institution=institution, crise=crise, environment=environment)
                   .select_related("auteur").order_by("date_creation"))
    alertes = list(AlertePopulation.objects.filter(institution=institution, crise=crise, environment=environment)
                   .order_by("date_creation"))
    demandes = Request.objects.filter(crisis=crise, environment=environment, **({"commune_code": commune} if commune else {})).count()
    signalements = Information.objects.filter(crisis=crise, environment=environment, **({"commune_code": commune} if commune else {})).count()
    equipes = sorted({equipe.name for mission in missions for equipe in mission.equipes.all()}
                     | {dossier.equipe.name for dossier in dossiers if dossier.equipe_id})
    return {
        "nom": crise.name, "type": crise.get_type_display() if hasattr(crise, "get_type_display") else (crise.type or ""),
        "description": crise.description or "", "close": crise.end_date is not None,
        "debut": _date(crise.start_date), "fin": _date(crise.end_date), "duree": _duree(crise.start_date, crise.end_date),
        "collectivite": institution.nom, "commune": institution.commune_nom or "", "commune_code": commune,
        "chiffres": [("Demandes d'aide reçues sur la commune", demandes), ("Signalements reçus sur la commune", signalements),
                     ("Dossiers ouverts", len(dossiers)), ("Missions conduites", len(missions)),
                     ("Équipes engagées", len(equipes)), ("Habitations évaluées", len(habitations)),
                     ("Alertes diffusées aux habitants", len(alertes))],
        "dossiers_par_statut": sorted(par_statut.items()),
        "equipes": equipes,
        "degats": sorted(degats.items()),
        "stock": _bilan_stock(institution, crise, environment),
        "causes": sorted(causes.items(), key=lambda paire: -paire[1]),
        "alertes": [(_date(a.date_creation), a.titre, ", ".join(a.canaux or []), a.destinataires) for a in alertes],
        "journal": [(_date(j.date_creation), nommer(j.auteur) if j.auteur_id else "", j.contenu or "") for j in journal[:MAX_LIGNES_JOURNAL]],
        "journal_omis": max(0, len(journal) - MAX_LIGNES_JOURNAL),
        "missions": [mission_resume(mission, nommer, par_mission.get(mission.id, [])) for mission in missions],
        # Les dossiers qui ne relèvent d'aucune de ces missions, pour qu'aucun ne manque en annexe.
        "dossiers_hors_mission": [dossier_resume(d, nommer) for d in dossiers
                                  if d.mission_id not in {m.id for m in missions}][:MAX_DOSSIERS_ANNEXES],
    }


# ───────────────────────────────────── la mise en page ─────────────────────────────────────

def _p(texte, style=_CORPS) -> Paragraph:
    # Tout vient d'une saisie : un « < » dans un commentaire ferait échouer l'édition entière.
    return Paragraph(escape(str(texte if texte is not None else "")).replace("\n", "<br/>"), style)


def _tableau(entetes, lignes, largeurs_mm, forte=0) -> Table:
    contenu = [[Paragraph(escape(e), _ENTETE) for e in entetes]] if entetes else []
    for ligne in lignes:
        contenu.append([_p(valeur, _CELLULE_FORTE if rang == forte and entetes else _CELLULE) for rang, valeur in enumerate(ligne)])
    tableau = Table(contenu, colWidths=[largeur * mm for largeur in largeurs_mm], repeatRows=1 if entetes else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.5, FILET), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if entetes:
        style.append(("BACKGROUND", (0, 0), (-1, 0), FOND))
    tableau.setStyle(TableStyle(style))
    return tableau


def _fiche(paires) -> Table:
    """Un tableau libellé / valeur, sans les lignes vides."""
    lignes = [(libelle, valeur) for libelle, valeur in paires if valeur not in (None, "", [])]
    tableau = Table([[_p(libelle, _CELLULE_FORTE), _p(valeur, _CELLULE)] for libelle, valeur in lignes],
                    colWidths=[50 * mm, 130 * mm])
    tableau.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, FILET), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("BACKGROUND", (0, 0), (0, -1), FOND), ("TOPPADDING", (0, 0), (-1, -1), 3),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return tableau


def _nombre(valeur, unite="") -> str:
    if valeur in (None, ""):
        return ""
    texte = f"{float(valeur):,.0f}".replace(",", " ") if float(valeur) == int(float(valeur)) else f"{float(valeur):,.1f}".replace(",", " ").replace(".", ",")
    return f"{texte} {unite}".strip()


def _corps_du_dossier(d: dict, niveau=_H1, complet=True) -> list:
    """Les rubriques d'un dossier. `complet` faux : la version courte des annexes."""
    blocs = [_fiche([
        ("Numéro", d["numero"]), ("Statut", d["statut"]), ("Priorité", d["priorite"]), ("Crise", d["crise"]),
        ("Compétence mobilisée", d["competence"]), ("Équipe", d["equipe"]), ("Mission", d["mission"]),
        ("Demandé par", d["demandeur_institution"]), ("Ouvert le", d["cree_le"]), ("Affecté le", d["affecte_le"]),
        ("Résolu le", d["resolu_le"]), ("Clôturé le", d["cloture_le"]), ("Durée de prise en charge", d["duree"]),
    ])]
    if d["description"]:
        blocs += [_p("Objet", niveau), _p(d["description"])]
    if d["origine"]:
        o = d["origine"]
        blocs += [_p(f"{o['nature']} à l'origine du dossier", niveau),
                  _fiche([("Intitulé", o["titre"]), ("Nature", o["type"]), ("Reçue le", o["recue_le"]),
                          ("Demandeur", o["demandeur"] if complet else ""), ("Ce qui était demandé", o["description"])])]
    if d["bien"]:
        b = d["bien"]
        blocs += [_p("Bien concerné et dégâts constatés", niveau),
                  _fiche([("Adresse", b["adresse"]), ("Commune", b["commune"]), ("Parcelle cadastrale", b["parcelle"]),
                          ("État des dégâts relevé", b["evaluation"]), ("Cause du dommage", b.get("nature", "")),
                          ("Relevé le", b["evalue_le"]), ("Relevé par", b["evalue_par"]),
                          ("Travaux", b["chantier"]),
                          ("Valeur indicative du bien", (_nombre(b["valeur"], "€") + (f" (source : {b['valeur_source']})" if b["valeur_source"] else "")
                                                          + " — indicative, ne vaut pas expertise") if b["valeur"] else "")])]
        if b["surfaces"]:
            blocs += [Spacer(1, 2 * mm), _tableau(("Surfaces", "Totale", "Touchée par les dégâts"),
                                                  [(libelle, _nombre(totale, "m²"), _nombre(impactee, "m²")) for libelle, totale, impactee in b["surfaces"]],
                                                  (80, 50, 50))]
        if b["observations"] and complet:
            blocs += [_p("Observations sur le bien", _H2), _tableau(("Date", "Par", "Observation"), b["observations"], (32, 38, 110), forte=-1)]
    if d["chronologie"]:
        blocs += [_p("Chronologie de la prise en charge", niveau),
                  _tableau(("Date", "Par", "Événement", "Précision"), d["chronologie"], (32, 34, 54, 60), forte=2)]
    if d["observations"] and complet:
        blocs += [_p("Observations consignées", niveau), _tableau(("Date", "Par", "Observation"), d["observations"], (32, 38, 110), forte=-1)]
    return blocs


def _vignette(photo: dict, largeur):
    """La photo réduite et sa légende, ou None si le fichier est illisible (photo effacée, format
    inattendu) : une photo manquante ne doit pas empêcher d'éditer le rapport."""
    try:
        from PIL import Image as ImagePIL, ImageOps

        with photo["champ"].open("rb") as fichier:
            brut = fichier.read()
        image = ImageOps.exif_transpose(ImagePIL.open(io.BytesIO(brut)))      # photos de téléphone : dans le bon sens
        image = image.convert("RGB")
        image.thumbnail((LARGEUR_PHOTO_PX, LARGEUR_PHOTO_PX))
        tampon = io.BytesIO()
        image.save(tampon, format="JPEG", quality=72)
        tampon.seek(0)
        hauteur = largeur * image.height / image.width
        if hauteur > 105 * mm:
            largeur, hauteur = largeur * (105 * mm) / hauteur, 105 * mm
        return Image(tampon, width=largeur, height=hauteur)
    except Exception:
        return None


def _annexe_photos(photos: list[dict], plafond: int | None, titre="Annexe — Photos") -> list:
    """`plafond` None : toutes les photos (demandé à l'édition ; le fichier peut être lourd)."""
    if not photos:
        return []
    blocs = [PageBreak(), _p(titre, _H1)]
    if plafond is None:
        plafond = len(photos)
    retenues, illisibles, rang = photos[:plafond], 0, 0
    cellules = []
    for photo in retenues:
        image = _vignette(photo, 86 * mm)
        if image is None:
            illisibles += 1
            continue
        rang += 1
        legende = f"Photo {rang} — {photo['legende']}" + (f" — {photo['date']}" if photo["date"] else "")
        if photo.get("dossier"):
            legende += f" — dossier {photo['dossier']}"
        if photo["empreinte"]:
            legende += f"<br/>Empreinte SHA-256 : {photo['empreinte'][:32]}…"
        cellules.append([image, Paragraph(legende, _LEGENDE)])
    for debut in range(0, len(cellules), 2):
        paire = cellules[debut:debut + 2]
        ligne = Table([[paire[0], paire[1] if len(paire) > 1 else ""]], colWidths=[90 * mm, 90 * mm])
        ligne.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        blocs.append(KeepTogether(ligne))
    if len(photos) > plafond:
        blocs.append(_p(f"{len(photos) - plafond} autre(s) photo(s) ne figurent pas ici : le rapport en retient {plafond} au plus. "
                        "Pour les avoir toutes, cochez « toutes les photos » à l'édition ; elles restent aussi consultables "
                        "dans l'application, dossier par dossier.", _NOTE))
    if illisibles:
        blocs.append(_p(f"{illisibles} photo(s) n'ont pas pu être reproduites (fichier illisible ou effacé).", _NOTE))
    if rang == 0:
        blocs.append(_p("Aucune photo n'a pu être reproduite.", _NOTE))
    return blocs


def _photos_des_dossiers(dossiers: list[dict]) -> list[dict]:
    return [{**photo, "dossier": d["numero"]} for d in dossiers for photo in d["photos"]]


def _annexe_dossiers(dossiers: list[dict], titre: str) -> list:
    if not dossiers:
        return []
    blocs = [PageBreak(), _p(titre, _H1)]
    for d in dossiers:
        blocs += [_p(f"Dossier {d['numero']} — {d['titre']}", _H2)] + _corps_du_dossier(d, niveau=_H2, complet=False) + [Spacer(1, 3 * mm)]
    return blocs


def _plafond(nature: str, toutes: bool):
    return None if toutes else MAX_PHOTOS[nature]


def _entete(titre, sous_titre) -> list:
    return [_p(titre, _TITRE), _p(sous_titre, _SOUS_TITRE), Paragraph(MENTION, _MENTION)]


def _blocs_dossier(d: dict, horodatage: str, toutes: bool = False) -> list:
    nature = "Rapport de clôture de dossier" if d["clos"] else "Rapport de dossier"
    etat = f"clôturé le {d['cloture_le']}" if d["clos"] else f"en cours — état au {horodatage}"
    blocs = _entete(f"{nature} n° {d['numero']}", f"{d['titre']} — {etat}")
    blocs += _corps_du_dossier(d)
    blocs += _annexe_photos(d["photos"], _plafond("dossier", toutes))
    return blocs


def _blocs_mission(m: dict, horodatage: str, toutes: bool = False) -> list:
    nature = "Rapport de clôture de mission" if m["close"] else "Rapport de mission"
    etat = f"terminée le {m['cloturee_le']}" if m["close"] and m["cloturee_le"] else f"état au {horodatage}"
    blocs = _entete(nature, f"{m['titre']} — {etat}")
    blocs.append(_fiche([("Mission", m["titre"]), ("Statut", m["statut"]), ("Crise", m["crise"]), ("Conduite par", m["institution"]),
                         ("Équipes engagées", ", ".join(m["equipes"])), ("Ouverte le", m["creee_le"]), ("Terminée le", m["cloturee_le"]),
                         ("Durée", m["duree"]), ("Mission d'intérêt général", "oui" if m["interet_general"] else "")]))
    if m["description"]:
        blocs += [_p("Objectif", _H1), _p(m["description"])]
    blocs.append(_p("Dossiers traités dans cette mission", _H1))
    if m["dossiers"]:
        blocs.append(_tableau(("N°", "Objet", "Statut", "Ouvert le", "Clôturé le"),
                              [(d["numero"], d["titre"], d["statut"], d["cree_le"], d["cloture_le"]) for d in m["dossiers"]],
                              (28, 72, 26, 27, 27), forte=1))
    else:
        blocs.append(_p("Aucun dossier n'a été rattaché à cette mission.", _NOTE))
    if m["dossiers_omis"]:
        blocs.append(_p(f"{m['dossiers_omis']} autre(s) dossier(s) ne sont pas détaillés ici.", _NOTE))
    blocs += _annexe_dossiers(m["dossiers"], "Annexe — Rapports des dossiers")
    blocs += _annexe_photos(_photos_des_dossiers(m["dossiers"]), _plafond("mission", toutes))
    return blocs


def _blocs_crise(c: dict, horodatage: str, toutes: bool = False) -> list:
    nature = "Rapport de clôture de crise" if c["close"] else "Rapport de crise"
    etat = f"close le {c['fin']}" if c["close"] else f"en cours — état au {horodatage}"
    blocs = _entete(f"{nature} — {c['collectivite']}", f"{c['nom']} — {etat}")
    blocs.append(_fiche([("Événement", c["nom"]), ("Nature", c["type"]), ("Collectivité", c["collectivite"]),
                         ("Commune", f"{c['commune']} ({c['commune_code']})" if c["commune"] else c["commune_code"]),
                         ("Début", c["debut"]), ("Fin", c["fin"]), ("Durée", c["duree"]), ("Description", c["description"])]))
    blocs += [_p("1 — En chiffres", _H1), _tableau((), [(libelle, str(nombre)) for libelle, nombre in c["chiffres"]], (130, 50))]
    if c["dossiers_par_statut"]:
        blocs += [_p("Dossiers par statut", _H2), _tableau(("Statut", "Nombre"), [(s, str(n)) for s, n in c["dossiers_par_statut"]], (130, 50))]

    blocs.append(_p("2 — Dégâts relevés sur les habitations", _H1))
    if c["degats"]:
        blocs.append(_tableau(("État relevé", "Habitations", "Surface habitable touchée", "Annexes touchées", "Valeur indicative cumulée"),
                              [(etat_, str(l["nombre"]), _nombre(l["habitable"], "m²") if l["habitable"] else "",
                                _nombre(l["annexes"], "m²") if l["annexes"] else "", _nombre(l["valeur"], "€") if l["valeur"] else "")
                               for etat_, l in c["degats"]], (46, 26, 38, 34, 36)))
        if c.get("causes"):
            blocs.append(_p("Causes des dommages constatés : " + ", ".join(f"{cause} ({nombre})" for cause, nombre in c["causes"]) + "."))
        blocs.append(_p("Les valeurs sont indicatives (ventes passées du secteur ou saisie) : elles situent un ordre de grandeur et "
                        "ne valent pas expertise.", _NOTE))
    else:
        blocs.append(_p("Aucune habitation n'a été référencée pour l'estimation des dégâts de cette crise.", _NOTE))

    blocs.append(_p("3 — Moyens engagés", _H1))
    blocs.append(_p("Équipes : " + ", ".join(c["equipes"]) + "." if c["equipes"] else "Aucune équipe n'est rattachée aux missions et dossiers de la collectivité.",
                    _CORPS if c["equipes"] else _NOTE))
    if c["missions"]:
        blocs.append(_tableau(("Mission", "Équipes", "Statut", "Ouverte le", "Terminée le", "Dossiers"),
                              [(m["titre"], ", ".join(m["equipes"]), m["statut"], m["creee_le"], m["cloturee_le"], str(len(m["dossiers"])))
                               for m in c["missions"]], (52, 44, 22, 24, 24, 14)))
    if c["alertes"]:
        blocs += [_p("4 — Alertes diffusées aux habitants", _H1),
                  _tableau(("Date", "Objet", "Canaux", "Destinataires"), [(d, t, canaux, str(n)) for d, t, canaux, n in c["alertes"]],
                           (32, 78, 46, 24), forte=1)]
    suivant = 5 if c["alertes"] else 4
    stock = _blocs_stock(c, suivant)
    blocs += stock
    suivant += 1 if stock else 0
    blocs.append(_p(f"{suivant} — Journal de bord de la collectivité", _H1))
    if c["journal"]:
        blocs.append(_tableau(("Date", "Par", "Consigné"), c["journal"], (32, 36, 112), forte=-1))
        if c["journal_omis"]:
            blocs.append(_p(f"{c['journal_omis']} entrée(s) plus récentes ne figurent pas ici.", _NOTE))
    else:
        blocs.append(_p("Rien n'a été consigné au journal de bord pour cette crise.", _NOTE))

    tous = [d for m in c["missions"] for d in m["dossiers"]] + c["dossiers_hors_mission"]
    if c["missions"]:
        blocs += [PageBreak(), _p("Annexe A — Rapports des missions", _H1)]
        for m in c["missions"]:
            blocs += [_p(m["titre"], _H2),
                      _fiche([("Statut", m["statut"]), ("Équipes engagées", ", ".join(m["equipes"])), ("Ouverte le", m["creee_le"]),
                              ("Terminée le", m["cloturee_le"]), ("Durée", m["duree"]), ("Objectif", m["description"]),
                              ("Dossiers traités", ", ".join(d["numero"] for d in m["dossiers"]))]), Spacer(1, 3 * mm)]
    blocs += _annexe_dossiers(tous, "Annexe B — Rapports des dossiers")
    blocs += _annexe_photos(_photos_des_dossiers(tous), _plafond("crise", toutes), "Annexe C — Photos")
    return blocs


def _blocs_bien(b: dict, horodatage: str, toutes: bool = False) -> list:
    blocs = _entete("Rapport de bien sinistré", f"{b['designation']} — état au {horodatage}")
    blocs.append(_fiche([
        ("Bien", b["designation"]), ("Type", b["type"]), ("Immatriculation, numéro de série", b["identification"]),
        ("Propriétaire", b["proprietaire"]), ("Crise", b["crise"]), ("État constaté", b["etat"]), ("Cause du dommage", b["nature"]),
        ("Lieu", b["adresse"]), ("Position relevée (latitude, longitude)", b["position"]),
        ("Relevé le", b["releve_le"]), ("Relevé par", b["releve_par"]), ("Pour le compte de", b["collectivite"]),
        ("Dernière mise à jour", b["modifie_le"]),
    ]))
    if b["description"]:
        blocs += [_p("Constat", _H1), _p(b["description"])]
    if not b["photos"]:
        blocs.append(_p("Aucune photo n'a été déposée pour ce bien.", _NOTE))
    blocs += _annexe_photos(b["photos"], _plafond("bien", toutes))
    return blocs


def _blocs_pret(f: dict, horodatage: str, toutes: bool = False) -> list:
    """La fiche de prêt (core/stocks_echanges.py) : qui prête quoi à qui, l'état au départ, l'état
    au retour, et la place des signatures — c'est ce papier qu'on sort quand le matériel revient
    abîmé et que chacun se souvient d'autre chose."""
    preteur, emprunteur = (f["institution"], f["tiers"]) if f["consenti"] else (f["tiers"], f["institution"])
    blocs = _entete("Fiche de prêt de matériel", f"{f['designation']} — état au {horodatage}")
    blocs.append(_fiche([
        ("Matériel", f["designation"]), ("Numéro de série, immatriculation", f["identification"]),
        ("Quantité", f"{f['quantite']} {f['unite']}".strip()),
        ("Prêté par", preteur), ("Prêté à", emprunteur),
        (f"{f['tiers']} ({f['tiers_type'].lower()})", f["tiers_contact"]),
        ("Début du prêt", f["debut"]), ("Retour prévu", f["retour_prevu"]), ("Crise", f["crise"]),
        ("Situation", f["statut"] + (" — retour en retard" if f["en_retard"] else "")), ("Enregistré par", f["enregistre_par"]),
    ]))
    if f["conditions"]:
        blocs += [_p("Conditions du prêt", _H1), _p(f["conditions"])]
    blocs += [_p("État au départ", _H1), _fiche([("État", f["etat_depart"]), ("Constat", f["constat_depart"]),
                                                   ("Photos", f"{len(f['photos_depart'])} en annexe" if f["photos_depart"] else "aucune")])]
    blocs.append(_p("État au retour", _H1))
    if f["rendu"]:
        blocs.append(_fiche([("Rendu le", f["retour"]), ("Quantité rendue", f"{f['quantite_rendue']} {f['unite']}".strip()),
                             ("État", f["etat_retour"]), ("Constat", f["constat_retour"]), ("Reçu par", f["rendu_a"]),
                             ("Photos", f"{len(f['photos_retour'])} en annexe" if f["photos_retour"] else "aucune")]))
        if f["reserve"]:
            blocs.append(_p("Rendu avec réserve : le matériel est revenu en moins bon état qu'au départ, ou en moindre quantité.", _NOTE))
    else:
        blocs.append(_p("Le matériel n'est pas encore rendu. État au retour : ……………………………………  Constat : ……………………………………………………………………", _NOTE))
    blocs += [_p("Signatures", _H1), _fiche([
        (f"Le prêteur — {preteur}", "Au départ : ……………………………   Au retour : ……………………………"),
        (f"L'emprunteur — {emprunteur}", "Au départ : ……………………………   Au retour : ……………………………")])]
    plafond = _plafond("pret", toutes)
    blocs += _annexe_photos(f["photos_depart"], plafond, titre="Annexe — Photos au départ")
    blocs += _annexe_photos(f["photos_retour"], plafond, titre="Annexe — Photos au retour")
    return blocs


_BLOCS = {"dossier": _blocs_dossier, "mission": _blocs_mission, "crise": _blocs_crise, "bien": _blocs_bien, "pret": _blocs_pret}
_PIEDS = {"dossier": lambda r: f"Rapport de dossier n° {r['numero']}", "mission": lambda r: f"Rapport de mission — {r['titre']}",
          "bien": lambda r: f"Rapport de bien sinistré — {r['designation']}",
          "pret": lambda r: f"Fiche de prêt — {r['designation']}",
          "crise": lambda r: f"Rapport de crise — {r['nom']} — {r['collectivite']}"}


def generer(nature: str, rapport: dict, *, edite_par: str, edite_le=None, toutes_les_photos: bool = False) -> bytes:
    """Le rapport mis en page (A4 portrait). `nature` : « dossier », « mission » ou « crise » ;
    `rapport` vient de `dossier_resume`, `mission_resume` ou `crise_resume`. `toutes_les_photos` :
    sans plafond — un assureur peut les vouloir toutes, au prix d'un fichier plus lourd."""
    edite_le = timezone.localtime(edite_le or timezone.now())
    horodatage = edite_le.strftime("%d/%m/%Y à %H:%M")
    pied = f"{_PIEDS[nature](rapport)} — édité le {horodatage} par {edite_par}"
    tampon = io.BytesIO()
    document = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                                 bottomMargin=17 * mm, title=_PIEDS[nature](rapport), author=edite_par)
    document.build(_BLOCS[nature](rapport, horodatage, toutes_les_photos),
                   canvasmaker=lambda *args, **kwargs: _CanevasNumerote(*args, pied=pied[:150], **kwargs))
    return tampon.getvalue()
