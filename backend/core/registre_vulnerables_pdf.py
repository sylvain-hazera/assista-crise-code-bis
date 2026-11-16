"""Édition PDF du registre communal des personnes vulnérables.

C'est l'annexe nominative du plan communal de sauvegarde (« populations nécessitant une attention
particulière » de la trame de l'État). Elle ne figure JAMAIS dans le document principal du plan,
que beaucoup de monde lit : elle se sort d'ici, par une personne nommément désignée par le maire
et engagée au secret (art. R. 121-7 du CASF), depuis l'écran du registre.

**Rien n'est stocké.** Le PDF est construit en mémoire à chaque demande, depuis les fiches du
moment, et part dans la réponse : aucune copie sur le serveur, aucune version figée qui
contiendrait encore une personne radiée depuis.

**Chaque page dit qui l'a sortie, et quand.** Une feuille nominative finit par traîner — dans une
voiture, sur un bureau, dans une poubelle. Le nom de celui qui l'a éditée, imprimé en pied de
chaque page, est la seule chose qui lui rappelle qu'elle est à lui, et la seule qui permette de
remonter à la source d'une feuille retrouvée. L'édition est aussi inscrite à la main courante,
avec le nombre de fiches et jamais leur contenu.
"""
import io
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvas_module
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SOMBRE = colors.HexColor("#1e293b")
GRIS = colors.HexColor("#6b7280")
FILET = colors.HexColor("#d1d5db")
FOND_ENTETE = colors.HexColor("#e2e8f0")
FOND_AVERTISSEMENT = colors.HexColor("#fef3c7")

SANS_QUARTIER = "Sans quartier renseigné"

AVERTISSEMENT = (
    "<b>Document nominatif, couvert par le secret professionnel.</b> Le registre des personnes "
    "vulnérables est tenu par la commune, pour la seule protection de ces personnes en cas de "
    "crise (art. L. 121-6-1 et R. 121-7 du code de l'action sociale et des familles). Ne le "
    "transmettez qu'aux personnes désignées par le maire, gardez-le sous clé, et détruisez cet "
    "exemplaire dès qu'il ne sert plus : seul le registre tenu dans l'application fait foi."
)

_TITRE = ParagraphStyle("titre", fontName="Helvetica-Bold", fontSize=15, textColor=SOMBRE, leading=19)
_SOUS_TITRE = ParagraphStyle("sous_titre", fontName="Helvetica", fontSize=9.5, textColor=GRIS, leading=13)
_AVERTISSEMENT = ParagraphStyle(
    "avertissement", fontName="Helvetica", fontSize=8.5, textColor=SOMBRE, leading=11.5,
    backColor=FOND_AVERTISSEMENT, borderPadding=(5, 6, 5, 6),
)
_QUARTIER = ParagraphStyle(
    "quartier", fontName="Helvetica-Bold", fontSize=11, textColor=SOMBRE, leading=14,
    spaceBefore=5 * mm, spaceAfter=2 * mm,
)
_CELLULE = ParagraphStyle("cellule", fontName="Helvetica", fontSize=8.5, textColor=SOMBRE, leading=10.5)
_CELLULE_FORTE = ParagraphStyle("cellule_forte", parent=_CELLULE, fontName="Helvetica-Bold")
_ENTETE = ParagraphStyle("entete", fontName="Helvetica-Bold", fontSize=8, textColor=SOMBRE, leading=10)
_VIDE = ParagraphStyle("vide", fontName="Helvetica-Oblique", fontSize=10, textColor=GRIS, leading=14)

_COLONNES = ("Nom, prénom", "Adresse", "Téléphone", "Besoins particuliers", "Personne à prévenir", "Observations")
_LARGEURS = (40 * mm, 62 * mm, 28 * mm, 48 * mm, 46 * mm, 43 * mm)


def lignes_du_registre(personnes) -> list[tuple[str, list[dict]]]:
    """Les fiches rangées par quartier, puis par nom : `[(quartier, [fiche, …]), …]`.

    Le tri se fait ici et non en base : nom, prénom et adresse sont chiffrés, la base ne sait
    pas les ordonner. « Sans quartier » vient en dernier, pour ne pas ouvrir le document sur les
    fiches les moins bien renseignées."""
    par_quartier: dict[str, list[dict]] = {}
    for personne in personnes:
        quartier = personne.zone.nom if personne.zone_id and personne.zone else SANS_QUARTIER
        aidant = " — ".join(
            morceau for morceau in (personne.contact_aidant_nom, personne.contact_aidant_telephone) if morceau
        )
        par_quartier.setdefault(quartier, []).append({
            "nom": f"{(personne.nom or '').strip()} {(personne.prenom or '').strip()}".strip(),
            "adresse": (personne.adresse or "").strip(),
            "telephone": (personne.telephone or "").strip(),
            "besoins": sorted(categorie.nom for categorie in personne.categories.all()),
            "aidant": aidant,
        })
    for fiches in par_quartier.values():
        fiches.sort(key=lambda fiche: (fiche["nom"].casefold(), fiche["adresse"].casefold()))
    return sorted(par_quartier.items(), key=lambda paire: (paire[0] == SANS_QUARTIER, paire[0].casefold()))


def nombre_de_fiches(groupes) -> int:
    return sum(len(fiches) for _quartier, fiches in groupes)


class _CanevasNumerote(canvas_module.Canvas):
    """Écrit « page x / y » : le total n'est connu qu'une fois tout le document posé, d'où les
    pages gardées en attente puis rejouées à l'enregistrement. Sur un registre de quarante
    pages, « page 3 » seule ne dit pas qu'il en manque."""

    def __init__(self, *args, pied: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._pied = pied
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for etat in self._pages:
            self.__dict__.update(etat)
            largeur, _hauteur = self._pagesize
            self.setFont("Helvetica", 7.5)
            self.setFillColor(GRIS)
            self.drawString(12 * mm, 8 * mm, self._pied)
            self.drawRightString(largeur - 12 * mm, 8 * mm, f"page {self._pageNumber} / {total}")
            super().showPage()
        super().save()


def _paragraphe(texte: str, style=_CELLULE) -> Paragraph:
    # Les valeurs viennent d'une saisie : un « < » ou un « & » dans une adresse ferait échouer
    # l'analyse du balisage de ReportLab, et l'édition entière avec.
    return Paragraph(escape(texte or ""), style)


def _tableau(fiches: list[dict]) -> Table:
    lignes = [[Paragraph(titre, _ENTETE) for titre in _COLONNES]]
    for fiche in fiches:
        lignes.append([
            _paragraphe(fiche["nom"], _CELLULE_FORTE),
            _paragraphe(fiche["adresse"]),
            _paragraphe(fiche["telephone"]),
            _paragraphe(", ".join(fiche["besoins"])),
            _paragraphe(fiche["aidant"]),
            "",   # laissée vide : c'est la colonne où l'on écrit, sur le terrain
        ])
    tableau = Table(lignes, colWidths=_LARGEURS, repeatRows=1)
    tableau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), FOND_ENTETE),
        ("GRID", (0, 0), (-1, -1), 0.5, FILET),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tableau


def generer_pdf_registre(groupes, *, commune: str, edite_par: str, edite_le=None) -> bytes:
    """Le registre mis en page, en A4 paysage.

    `groupes` vient de `lignes_du_registre`. `commune` et `edite_par` sont des libellés déjà
    lisibles ; `edite_le` vaut maintenant par défaut."""
    edite_le = timezone.localtime(edite_le or timezone.now())
    horodatage = edite_le.strftime("%d/%m/%Y à %H:%M")
    total = nombre_de_fiches(groupes)
    pied = f"Registre des personnes vulnérables — {commune} — édité le {horodatage} par {edite_par} — confidentiel"

    contenu = [
        _paragraphe("Registre communal des personnes vulnérables", _TITRE),
        _paragraphe(
            f"{commune} — {total} personne{'s' if total > 1 else ''} inscrite{'s' if total > 1 else ''} "
            f"— édité le {horodatage} par {edite_par}", _SOUS_TITRE),
        Spacer(1, 3 * mm),
        Paragraph(AVERTISSEMENT, _AVERTISSEMENT),
    ]
    if not groupes:
        contenu += [Spacer(1, 8 * mm), _paragraphe("Aucune personne n'est inscrite au registre de cette commune.", _VIDE)]
    for quartier, fiches in groupes:
        contenu.append(_paragraphe(f"{quartier} — {len(fiches)} personne{'s' if len(fiches) > 1 else ''}", _QUARTIER))
        contenu.append(_tableau(fiches))

    tampon = io.BytesIO()
    document = SimpleDocTemplate(
        tampon, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=15 * mm,
        title="Registre des personnes vulnérables", author=edite_par,
    )
    document.build(contenu, canvasmaker=lambda *args, **kwargs: _CanevasNumerote(*args, pied=pied, **kwargs))
    return tampon.getvalue()
