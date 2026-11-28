"""Bénévolat d'une association : heures et kilomètres, valorisation, abandon de frais (26/11/2026).

Demande de Sylvain après l'annonce de FCBA 33 : « suivi des heures et des kilomètres […]
facilitant le suivi comptable et la valorisation du bénévolat ». Le relevé d'heures existe
déjà (EngagementPersonnel, core/engagements_personnels.py) : ce module le **lit**, il ne le
double pas.

- **Valorisation** : heures VALIDÉES × taux horaire, kilomètres VALIDÉS × tarif du véhicule,
  par bénévole, par manifestation ou crise, par mois. Les taux sont ceux que l'association a
  saisis pour l'année (ReglagesBenevolat) : aucun barème n'est codé en dur.
- **Abandon de frais** : le bénévole renonce au remboursement de ses frais kilométriques
  validés d'une année ; le bureau accepte, et le montant est figé ; le reçu fiscal (mentions du
  Cerfa n° 11580) n'est possible que si l'association s'est déclarée habilitée.
- Les kilomètres sont chiffrés en base : tous les totaux sont faits ici, en Python.
"""
import csv
import datetime
import io
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    AbandonFrais, EngagementPersonnel, NatureFraisDeplacement, ReglagesBenevolat, StatutAbandonFrais, VehiculeBenevole,
)

#: Taux de la réduction d'impôt, affiché comme une information (CGI art. 200), jamais calculé
#: comme un droit : il dépend de la situation du donateur et de l'association.
TAUX_REDUCTION_INFORMATIF = 66


class ErreurBenevolat(ValueError):
    """Geste refusé ; le message est fait pour être lu."""


def reglages(institution, annee, environment) -> ReglagesBenevolat:
    r, _ = ReglagesBenevolat.objects.get_or_create(institution=institution, annee=annee, environment=environment)
    return r


def _centimes(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def tarif_km(r: ReglagesBenevolat, vehicule: str, puissance=None):
    """Le tarif d'un kilomètre. Une voiture dont on connaît la puissance prend le tarif de sa
    tranche si le trésorier l'a saisi (28/11/2026) ; sinon le tarif voiture."""
    if vehicule == VehiculeBenevole.VOITURE:
        if puissance and r.tarifs_km_puissance:
            tranche = str(min(7, max(3, int(puissance))))
            try:
                valeur = Decimal(str(r.tarifs_km_puissance.get(tranche) or "").replace(",", "."))
                if valeur > 0:
                    return valeur
            except (ArithmeticError, ValueError):
                pass
        return r.tarif_km_voiture
    if vehicule == VehiculeBenevole.DEUX_ROUES:
        return r.tarif_km_deux_roues
    return None


def lignes_de(institution, environment, annee, utilisateur=None, validees=True):
    """Les lignes de relevé d'une association pour une année : parties en son nom, avec une de
    ses équipes, ou sur une de ses manifestations."""
    debut = timezone.make_aware(datetime.datetime(annee, 1, 1))
    fin = timezone.make_aware(datetime.datetime(annee + 1, 1, 1))
    qs = (EngagementPersonnel.objects.filter(environment=environment, parti_le__gte=debut, parti_le__lt=fin)
          .filter(Q(institution=institution) | Q(equipe__institution=institution) | Q(manifestation__institution=institution))
          .exclude(rentre_le__isnull=True)
          .select_related("utilisateur", "crise", "manifestation", "equipe", "vehicule_personnel")
          .prefetch_related("frais").distinct().order_by("parti_le"))
    if utilisateur is not None:
        qs = qs.filter(utilisateur=utilisateur)
    if validees:
        qs = qs.filter(valide_le__isnull=False)
    return list(qs)


def _heures(ligne) -> Decimal:
    d = ligne.duree
    return Decimal(str(round(d.total_seconds() / 3600, 2))) if d else Decimal("0")


def tarif_ligne(ligne, r: ReglagesBenevolat):
    vp = ligne.vehicule_personnel
    return tarif_km(r, ligne.vehicule, vp.puissance() if vp is not None else None)


def frais_km_ligne(ligne, r: ReglagesBenevolat) -> Decimal:
    t = tarif_ligne(ligne, r)
    return _centimes(Decimal(str(ligne.kilometres_nombre())) * t) if t else Decimal("0.00")


def frais_annexes_ligne(ligne, nature=None) -> Decimal:
    """Péages et stationnement de la ligne (28/11/2026), ou d'une seule nature."""
    return _centimes(sum((Decimal(str(f.montant_nombre())) for f in ligne.frais.all()
                          if nature is None or f.nature == nature), Decimal("0")))


def frais_ligne(ligne, r: ReglagesBenevolat) -> Decimal:
    """Tout ce que la ligne coûte au bénévole : kilomètres, péages, stationnement."""
    return frais_km_ligne(ligne, r) + frais_annexes_ligne(ligne)


def trajet(ligne) -> str:
    """« Domicile → Firminy », vide si rien n'est dit."""
    if not (ligne.lieu_depart or ligne.lieu_arrivee):
        return ""
    return f"{ligne.lieu_depart or '?'} → {ligne.lieu_arrivee or '?'}"


def _nom(u) -> str:
    return f"{u.first_name} {u.last_name}".strip() or u.email


def valorisation(institution, environment, annee) -> dict:
    """Le tableau de la page « Bénévolat » : totaux, par bénévole, par activité, par mois."""
    r = reglages(institution, annee, environment)
    lignes = lignes_de(institution, environment, annee)
    par_benevole, par_activite, par_mois = {}, {}, {}
    total_h, total_km, total_frais, total_annexes = Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
    for l in lignes:
        h, km, frais = _heures(l), Decimal(str(l.kilometres_nombre())), frais_ligne(l, r)
        annexes = frais_annexes_ligne(l)
        total_h += h; total_km += km; total_frais += frais; total_annexes += annexes
        b = par_benevole.setdefault(l.utilisateur_id, {"utilisateur": str(l.utilisateur_id), "nom": _nom(l.utilisateur),
                                                       "heures": Decimal("0"), "kilometres": Decimal("0"), "frais": Decimal("0"),
                                                       "frais_annexes": Decimal("0")})
        b["heures"] += h; b["kilometres"] += km; b["frais"] += frais; b["frais_annexes"] += annexes
        cle = ("m", l.manifestation_id) if l.manifestation_id else ("c", l.crise_id)
        a = par_activite.setdefault(cle, {"genre": "manifestation" if l.manifestation_id else "crise", "nom": l.objet_nom,
                                          "date": timezone.localtime(l.parti_le).date(), "heures": Decimal("0"), "benevoles": set()})
        a["heures"] += h; a["benevoles"].add(l.utilisateur_id)
        mois = timezone.localtime(l.parti_le).strftime("%Y-%m")
        par_mois[mois] = par_mois.get(mois, Decimal("0")) + h
    taux = r.taux_horaire
    for b in par_benevole.values():
        b["valorisation"] = _centimes(b["heures"] * taux) if taux else None
    return {
        "annee": annee,
        "reglages": reglages_en_dict(r),
        "heures": total_h, "kilometres": total_km, "frais": _centimes(total_frais),
        "frais_annexes": _centimes(total_annexes),
        "valorisation_heures": _centimes(total_h * taux) if taux else None,
        "benevoles": sorted(par_benevole.values(), key=lambda b: b["nom"].lower()),
        "activites": [dict(a, benevoles=len(a["benevoles"])) for a in sorted(par_activite.values(), key=lambda a: a["date"])],
        "mois": [{"mois": k, "heures": v} for k, v in sorted(par_mois.items())],
        "lignes_a_valider": len(lignes_de(institution, environment, annee, validees=False)) - len(lignes),
    }


def reglages_en_dict(r: ReglagesBenevolat) -> dict:
    return {
        "annee": r.annee, "taux_horaire": r.taux_horaire, "tarif_km_voiture": r.tarif_km_voiture,
        "tarif_km_deux_roues": r.tarif_km_deux_roues, "tarifs_km_puissance": r.tarifs_km_puissance or {},
        "recus_fiscaux": r.recus_fiscaux,
        "fondement_recus": r.fondement_recus, "signataire_nom": r.signataire_nom,
        "signataire_qualite": r.signataire_qualite, "dernier_recu": r.dernier_recu,
    }


def export_lignes(institution, environment, annee, format_="csv"):
    """Les lignes validées de l'année, pour le comptable : (contenu, type MIME, extension)."""
    r = reglages(institution, annee, environment)
    entetes = ["Bénévole", "Activité", "Type", "Départ", "Retour", "Heures", "Véhicule", "Puissance (CV)", "Motif",
               "Trajet", "A/R", "Compteur départ", "Compteur arrivée", "Kilomètres", "Frais km (€)", "Péages (€)",
               "Stationnement (€)", "Frais total (€)", "Valorisation (€)", "Validé le"]
    rangs = []
    for l in lignes_de(institution, environment, annee):
        h = _heures(l)
        rangs.append([
            _nom(l.utilisateur), l.objet_nom, "Manifestation" if l.manifestation_id else "Crise",
            timezone.localtime(l.parti_le).strftime("%d/%m/%Y %H:%M"), timezone.localtime(l.rentre_le).strftime("%d/%m/%Y %H:%M"),
            float(h), l.get_vehicule_display(),
            (l.vehicule_personnel.puissance() or "") if l.vehicule_personnel_id else "",
            l.motif, trajet(l), "oui" if l.aller_retour else "non", l.compteur_depart, l.compteur_arrivee,
            l.kilometres_nombre(), float(frais_km_ligne(l, r)),
            float(frais_annexes_ligne(l, NatureFraisDeplacement.PEAGE)),
            float(frais_annexes_ligne(l, NatureFraisDeplacement.STATIONNEMENT)), float(frais_ligne(l, r)),
            float(_centimes(h * r.taux_horaire)) if r.taux_horaire else "",
            timezone.localtime(l.valide_le).strftime("%d/%m/%Y") if l.valide_le else "",
        ])
    if format_ == "xlsx":
        from openpyxl import Workbook
        classeur = Workbook()
        feuille = classeur.active
        feuille.title = f"Bénévolat {annee}"
        feuille.append(entetes)
        for rang in rangs:
            feuille.append(rang)
        sortie = io.BytesIO()
        classeur.save(sortie)
        return sortie.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, delimiter=";")
    ecrivain.writerow(entetes)
    ecrivain.writerows(rangs)
    # BOM : Excel ouvre ainsi les accents correctement.
    return ("﻿" + sortie.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", "csv"


# --- Abandon de frais ------------------------------------------------------------------------

def frais_abandonnables(institution, environment, annee, utilisateur) -> dict:
    r = reglages(institution, annee, environment)
    lignes = [l for l in lignes_de(institution, environment, annee, utilisateur)
              if l.kilometres_nombre() > 0 or frais_annexes_ligne(l) > 0]
    frais_km = sum((frais_km_ligne(l, r) for l in lignes), Decimal("0.00"))
    peages = sum((frais_annexes_ligne(l, NatureFraisDeplacement.PEAGE) for l in lignes), Decimal("0.00"))
    stationnement = sum((frais_annexes_ligne(l, NatureFraisDeplacement.STATIONNEMENT) for l in lignes), Decimal("0.00"))
    return {"lignes": [str(l.id) for l in lignes], "kilometres": sum(l.kilometres_nombre() for l in lignes),
            "frais_km": str(_centimes(frais_km)), "peages": str(_centimes(peages)),
            "stationnement": str(_centimes(stationnement)),
            "montant": str(_centimes(frais_km + peages + stationnement))}


def demander_abandon(institution, environment, annee, utilisateur, adresse: str) -> AbandonFrais:
    """Le bénévole renonce au remboursement de ses frais validés de l'année. L'adresse figure
    sur le reçu fiscal (mention obligatoire) : elle est demandée ici, et gardée chiffrée."""
    r = reglages(institution, annee, environment)
    if not r.recus_fiscaux:
        raise ErreurBenevolat("Votre association n'a pas indiqué pouvoir délivrer des reçus fiscaux : parlez-en à son bureau.")
    if not (adresse or "").strip():
        raise ErreurBenevolat("Indiquez votre adresse : elle figure sur le reçu fiscal.")
    frais = frais_abandonnables(institution, environment, annee, utilisateur)
    if Decimal(frais["montant"]) <= 0:
        raise ErreurBenevolat("Aucun frais de déplacement validé sur cette année (ou tarif non renseigné par l'association).")
    abandon, cree = AbandonFrais.objects.get_or_create(
        institution=institution, utilisateur=utilisateur, annee=annee, environment=environment,
        defaults={"detail": dict(frais, adresse=adresse.strip()[:300])})
    if not cree:
        if abandon.statut in (StatutAbandonFrais.ACCEPTE, StatutAbandonFrais.RECU_EMIS):
            raise ErreurBenevolat("Votre renonciation pour cette année a déjà été acceptée.")
        abandon.statut, abandon.detail, abandon.motif_refus = StatutAbandonFrais.DEMANDE, dict(frais, adresse=adresse.strip()[:300]), ""
        abandon.save(update_fields=["statut", "detail", "motif_refus"])
    return abandon


@transaction.atomic
def accepter_abandon(abandon, par) -> AbandonFrais:
    """Le bureau accepte : le montant est recalculé une dernière fois puis figé, et le reçu
    reçoit son numéro (« 2027-0001 »)."""
    if abandon.statut != StatutAbandonFrais.DEMANDE:
        raise ErreurBenevolat("Cette demande n'est plus en attente.")
    if abandon.utilisateur_id == par.id:
        raise ErreurBenevolat("On n'accepte pas sa propre renonciation : c'est à un autre membre du bureau de le faire.")
    r = ReglagesBenevolat.objects.select_for_update().get(pk=reglages(abandon.institution, abandon.annee, abandon.environment).pk)
    if not r.recus_fiscaux:
        raise ErreurBenevolat("Cochez d'abord, dans les réglages de l'année, que l'association délivre des reçus fiscaux.")
    frais = frais_abandonnables(abandon.institution, abandon.environment, abandon.annee, abandon.utilisateur)
    if Decimal(frais["montant"]) <= 0:
        raise ErreurBenevolat("Plus aucun frais validé à abandonner sur cette année.")
    r.dernier_recu += 1
    r.save(update_fields=["dernier_recu", "modifie_le"])
    abandon.detail = dict(frais, adresse=(abandon.detail or {}).get("adresse", ""))
    abandon.statut = StatutAbandonFrais.RECU_EMIS
    abandon.numero_recu = f"{abandon.annee}-{r.dernier_recu:04d}"
    abandon.date_recu = timezone.localdate()
    abandon.traite_par = par
    abandon.save(update_fields=["detail", "statut", "numero_recu", "date_recu", "traite_par"])
    return abandon


def refuser_abandon(abandon, par, motif) -> AbandonFrais:
    if abandon.statut != StatutAbandonFrais.DEMANDE:
        raise ErreurBenevolat("Cette demande n'est plus en attente.")
    if not (motif or "").strip():
        raise ErreurBenevolat("Dites pourquoi : la personne ne peut pas le deviner.")
    abandon.statut, abandon.motif_refus, abandon.traite_par = StatutAbandonFrais.REFUSE, motif.strip()[:300], par
    abandon.save(update_fields=["statut", "motif_refus", "traite_par"])
    return abandon


# --- Montant en lettres (mention du reçu) ------------------------------------------------------

_UNITES = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
           "treize", "quatorze", "quinze", "seize"]
_DIZAINES = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante", 60: "soixante"}


def _moins_de_cent(n: int) -> str:
    if n <= 16:
        return _UNITES[n]
    if n < 20:
        return "dix-" + _UNITES[n - 10]
    if n < 70:
        d, u = (n // 10) * 10, n % 10
        return _DIZAINES[d] + ("" if u == 0 else (" et un" if u == 1 else "-" + _UNITES[u]))
    if n < 80:
        return "soixante" + (" et onze" if n == 71 else "-" + _moins_de_cent(n - 60))
    if n == 80:
        return "quatre-vingts"
    return "quatre-vingt-" + _moins_de_cent(n - 80)


def _moins_de_mille(n: int) -> str:
    c, reste = divmod(n, 100)
    if c == 0:
        return _moins_de_cent(reste)
    debut = "cent" if c == 1 else _UNITES[c] + " cent" + ("s" if reste == 0 else "")
    return debut + ("" if reste == 0 else " " + _moins_de_cent(reste))


def en_lettres(n: int) -> str:
    """Entier en toutes lettres (orthographe traditionnelle), jusqu'au milliard exclu."""
    if n < 1000:
        return _moins_de_mille(n)
    if n < 1_000_000:
        m, reste = divmod(n, 1000)
        debut = "mille" if m == 1 else _moins_de_mille(m).removesuffix("s") + " mille"
        return debut + ("" if reste == 0 else " " + _moins_de_mille(reste))
    mi, reste = divmod(n, 1_000_000)
    return _moins_de_mille(mi) + " million" + ("s" if mi > 1 else "") + ("" if reste == 0 else " " + en_lettres(reste))


def montant_en_lettres(montant: Decimal) -> str:
    euros = int(montant)
    centimes = int((_centimes(montant) - euros) * 100)
    texte = f"{en_lettres(euros)} euro{'s' if euros > 1 else ''}"
    return texte + (f" et {en_lettres(centimes)} centime{'s' if centimes > 1 else ''}" if centimes else "")


# --- Reçu fiscal (PDF, jamais stocké) ------------------------------------------------------------

def recu_pdf(abandon) -> bytes:
    """Reçu au titre des dons à certains organismes d'intérêt général, pour une renonciation au
    remboursement de frais : les mentions du Cerfa n° 11580, sur une page. Reconstruit à chaque
    téléchargement à partir de ce qui a été figé à l'acceptation."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    if abandon.statut != StatutAbandonFrais.RECU_EMIS:
        raise ErreurBenevolat("Le reçu n'est disponible qu'une fois la renonciation acceptée.")
    r = reglages(abandon.institution, abandon.annee, abandon.environment)
    inst, u, d = abandon.institution, abandon.utilisateur, abandon.detail or {}
    montant = Decimal(d.get("montant", "0"))
    sombre, gris = colors.HexColor("#1e293b"), colors.HexColor("#6b7280")
    titre = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=sombre, spaceAfter=2 * mm)
    sous = ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, leading=11, textColor=gris, spaceAfter=5 * mm)
    rubrique = ParagraphStyle("r", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.white,
                              backColor=sombre, borderPadding=(3, 3, 3, 5), spaceBefore=4 * mm, spaceAfter=3 * mm)
    texte = ParagraphStyle("x", fontName="Helvetica", fontSize=9.5, leading=13, textColor=sombre, spaceAfter=1.5 * mm)
    petit = ParagraphStyle("p", fontName="Helvetica", fontSize=7.5, leading=10, textColor=gris)

    def p(t, style=texte):
        from xml.sax.saxutils import escape
        return Paragraph(escape(str(t or "")).replace("\n", "<br/>"), style)

    elements = [
        p("Reçu au titre des dons à certains organismes d'intérêt général", titre),
        p(f"Articles 200, 238 bis et 978 du code général des impôts — reçu n° {abandon.numero_recu}", sous),
        p("Bénéficiaire des versements", rubrique),
        p(inst.nom), p(inst.adresse or ""),
        p(" ".join(x for x in [inst.commune_code_postal or "", inst.commune_nom or ""] if x)),
        p(f"Objet : {inst.description}" if inst.description else ""),
        p(r.fondement_recus or ""),
        p("Donateur", rubrique),
        p(_nom(u)), p(d.get("adresse", "")),
        p("Don", rubrique),
        p(f"Le bénéficiaire reconnaît avoir reçu au titre des dons et versements ouvrant droit à réduction d'impôt "
          f"la somme de {montant:.2f} € ({montant_en_lettres(montant)})."),
        p(f"Année des frais : {abandon.annee}. Date du reçu : {abandon.date_recu:%d/%m/%Y}."),
    ]
    tableau = Table([
        ["Forme du don", "Renonciation expresse au remboursement de frais engagés par un bénévole"],
        ["Nature du don", "Frais de déplacement : kilomètres, péages, stationnement (abandon de frais)"
         if Decimal(d.get("peages") or "0") + Decimal(d.get("stationnement") or "0") > 0
         else "Frais kilométriques (abandon de frais)"],
        ["Kilomètres", f"{float(d.get('kilometres', 0)):.0f} km, sur {len(d.get('lignes', []))} déplacement(s) validé(s)"
         + (f", soit {d['frais_km']} €" if d.get("frais_km") else "")],
        *([["Péages", f"{d['peages']} €"]] if Decimal(d.get("peages") or "0") > 0 else []),
        *([["Stationnement", f"{d['stationnement']} €"]] if Decimal(d.get("stationnement") or "0") > 0 else []),
        ["Mode de versement", "Autre (abandon de frais)"],
    ], colWidths=[45 * mm, 120 * mm])
    tableau.setStyle(TableStyle([
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9), ("FONT", (1, 0), (1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), sombre), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements += [Spacer(1, 3 * mm), tableau, Spacer(1, 8 * mm),
                 p(f"Fait le {abandon.date_recu:%d/%m/%Y}, pour l'association : {r.signataire_nom}"
                   + (f", {r.signataire_qualite}" if r.signataire_qualite else "") + "."),
                 p("Signature :"), Spacer(1, 18 * mm),
                 p("Le donateur a renoncé expressément, par écrit, au remboursement de ces frais. L'association conserve les "
                   "justificatifs des déplacements. Ce reçu est établi d'après les déclarations validées dans l'application ; "
                   "il appartient à l'association de vérifier qu'elle remplit les conditions pour le délivrer.", petit)]
    sortie = io.BytesIO()
    SimpleDocTemplate(sortie, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=15 * mm,
                      title=f"Reçu {abandon.numero_recu}").build(elements)
    return sortie.getvalue()


# --- Relevé kilométrique imprimable (28/11/2026, PDF jamais stocké) -----------------------------

def lignes_de_deplacement(institution, environment, utilisateur, du, au, validees_seulement=True):
    """Les déplacements d'un bénévole pour une association entre deux dates (incluses) : les
    lignes terminées qui portent des kilomètres ou des frais."""
    debut = timezone.make_aware(datetime.datetime.combine(du, datetime.time.min))
    fin = timezone.make_aware(datetime.datetime.combine(au, datetime.time.max))
    qs = (EngagementPersonnel.objects.filter(environment=environment, utilisateur=utilisateur,
                                             parti_le__gte=debut, parti_le__lte=fin)
          .filter(Q(institution=institution) | Q(equipe__institution=institution) | Q(manifestation__institution=institution))
          .exclude(rentre_le__isnull=True)
          .select_related("crise", "manifestation", "equipe", "vehicule_personnel")
          .prefetch_related("frais").distinct().order_by("parti_le"))
    if validees_seulement:
        qs = qs.filter(valide_le__isnull=False)
    return [l for l in qs if l.kilometres_nombre() > 0 or frais_annexes_ligne(l) > 0]


def releve_km_pdf(utilisateur, institution, environment, du, au, validees_seulement=True) -> bytes:
    """L'état des frais de déplacement d'un bénévole : une ligne par déplacement (date, motif,
    trajet, compteurs, km, frais), les totaux, « certifié exact » et deux signatures. Le
    bénévole l'imprime avec ses lignes en attente (marquées comme telles) ; le bureau, avec
    les seules lignes validées."""
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    r = reglages(institution, au.year, environment)
    lignes = lignes_de_deplacement(institution, environment, utilisateur, du, au, validees_seulement)
    sombre, gris, filet = colors.HexColor("#1e293b"), colors.HexColor("#6b7280"), colors.HexColor("#d1d5db")
    titre = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=sombre, spaceAfter=1 * mm)
    sous = ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, leading=11, textColor=gris, spaceAfter=3 * mm)
    texte = ParagraphStyle("x", fontName="Helvetica", fontSize=9, leading=12, textColor=sombre)
    cellule = ParagraphStyle("c", fontName="Helvetica", fontSize=7.5, leading=9, textColor=sombre)
    petit = ParagraphStyle("p", fontName="Helvetica", fontSize=7.5, leading=10, textColor=gris)

    def p(t, style=texte):
        return Paragraph(escape(str(t or "")).replace("\n", "<br/>"), style)

    def euros(v: Decimal) -> str:
        return f"{v:.2f}".replace(".", ",") if v else ""

    def nombre(v) -> str:
        return format(Decimal(str(v)).normalize(), "f").replace(".", ",")

    vehicules = []
    for l in lignes:
        if l.vehicule_personnel_id and l.vehicule_personnel not in vehicules:
            vehicules.append(l.vehicule_personnel)
    elements = [
        p("Relevé kilométrique et frais de déplacement", titre),
        p(f"Du {du:%d/%m/%Y} au {au:%d/%m/%Y} — "
          + ("lignes validées par l'association" if validees_seulement else "lignes validées et en attente de validation"), sous),
        p(f"Association : {institution.nom}"),
        p(f"Bénévole : {_nom(utilisateur)}"),
        p("Véhicule(s) : " + ("; ".join(v.designation for v in vehicules) if vehicules else "non précisé")),
        Spacer(1, 4 * mm),
    ]
    entete = ["Date", "Motif", "Trajet", "A/R", "Compteur\ndépart", "Compteur\narrivée", "Km", "€/km", "Frais km",
              "Péage", "Station.", "Total", "Validation"]
    rangs = [entete]
    t_km, t_fkm, t_pea, t_sta = Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
    for l in lignes:
        km = Decimal(str(l.kilometres_nombre()))
        tarif = tarif_ligne(l, r)
        fkm = frais_km_ligne(l, r)
        pea = frais_annexes_ligne(l, NatureFraisDeplacement.PEAGE)
        sta = frais_annexes_ligne(l, NatureFraisDeplacement.STATIONNEMENT)
        t_km += km; t_fkm += fkm; t_pea += pea; t_sta += sta
        rangs.append([
            timezone.localtime(l.parti_le).strftime("%d/%m/%Y"), p(l.motif or l.objet_nom, cellule), p(trajet(l), cellule),
            "oui" if l.aller_retour else "non", l.compteur_depart, l.compteur_arrivee, nombre(km),
            f"{tarif:.3f}".replace(".", ",") if tarif else "", euros(fkm), euros(pea), euros(sta), euros(fkm + pea + sta),
            timezone.localtime(l.valide_le).strftime("%d/%m/%Y") if l.valide_le else "en attente",
        ])
    rangs.append(["Total", "", "", "", "", "", nombre(t_km), "", euros(t_fkm), euros(t_pea), euros(t_sta),
                  euros(t_fkm + t_pea + t_sta), ""])
    tableau = Table(rangs, repeatRows=1, colWidths=[18 * mm, 46 * mm, 52 * mm, 9 * mm, 17 * mm, 17 * mm, 12 * mm,
                                                     12 * mm, 16 * mm, 14 * mm, 14 * mm, 16 * mm, 19 * mm])
    tableau.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5), ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 7.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), sombre), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
        ("GRID", (0, 0), (-1, -1), 0.4, filet), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (3, 1), (-2, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    signatures = Table([[p("Le bénévole, « certifié exact »"), p(f"Pour l'association : {r.signataire_nom or ''}"
                                                                  + (f", {r.signataire_qualite}" if r.signataire_qualite else ""))],
                        ["", ""]], colWidths=[120 * mm, 120 * mm], rowHeights=[None, 20 * mm])
    signatures.setStyle(TableStyle([("BOX", (0, 0), (0, -1), 0.4, filet), ("BOX", (1, 0), (1, -1), 0.4, filet),
                                    ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    tarifs = []
    if r.tarif_km_voiture:
        tarifs.append(f"voiture {nombre(r.tarif_km_voiture)} €/km")
    if r.tarifs_km_puissance:
        tarifs.append("par puissance fiscale : " + ", ".join(
            f"{'≤ ' if k == '3' else ('≥ ' if k == '7' else '')}{k} CV {nombre(v)} €/km"
            for k, v in sorted(r.tarifs_km_puissance.items()) if v))
    if r.tarif_km_deux_roues:
        tarifs.append(f"moto, scooter {nombre(r.tarif_km_deux_roues)} €/km")
    elements += [
        tableau, Spacer(1, 3 * mm),
        p(("Tarifs retenus par l'association pour " + str(au.year) + " : " + " ; ".join(tarifs) + ".") if tarifs
          else "L'association n'a pas encore renseigné ses tarifs kilométriques : seuls les kilomètres sont relevés.", petit),
        Spacer(1, 5 * mm),
        p(f"Fait le {timezone.localdate():%d/%m/%Y}."), Spacer(1, 2 * mm), signatures, Spacer(1, 3 * mm),
        p("Relevé établi d'après les déclarations du bénévole dans l'application. Les justificatifs de péage et de "
          "stationnement sont conservés par l'association. En cas d'abandon de frais, ce relevé accompagne la "
          "renonciation écrite du bénévole.", petit),
    ]
    sortie = io.BytesIO()
    SimpleDocTemplate(sortie, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                      bottomMargin=12 * mm, title=f"Relevé kilométrique — {_nom(utilisateur)}").build(elements)
    return sortie.getvalue()
