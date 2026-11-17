"""La feuille d'inventaire : ce que le stock dit avoir, et une colonne vide pour ce qu'on compte.

On l'imprime, on fait le tour du dépôt un crayon à la main, puis on saisit la colonne d'un bloc
(`stocks.inventorier`). L'inventaire se fait à l'aveugle si on le demande : sans la quantité
attendue, on compte ce qu'on voit au lieu de confirmer ce qu'on lit."""
import io
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import stocks
from .registre_vulnerables_pdf import FILET, FOND_ENTETE, GRIS, SOMBRE, _CanevasNumerote

_TITRE = ParagraphStyle("inv_titre", fontName="Helvetica-Bold", fontSize=15, textColor=SOMBRE, leading=19)
_SOUS = ParagraphStyle("inv_sous", fontName="Helvetica", fontSize=9.5, textColor=GRIS, leading=13)
_CELLULE = ParagraphStyle("inv_cellule", fontName="Helvetica", fontSize=8.5, textColor=SOMBRE, leading=10.5)
_ENTETE = ParagraphStyle("inv_entete", fontName="Helvetica-Bold", fontSize=8, textColor=SOMBRE, leading=10)


def lignes_d_inventaire(etat: list[dict], depot) -> list[dict]:
    """Ce qu'il y a à compter dans ce dépôt : une ligne par article, ou par lot quand il y en a.
    Les articles actifs sans stock y figurent aussi : c'est en comptant qu'on en retrouve."""
    lignes = []
    for article in etat:
        a = article["article"]
        lots = [l for l in article["lots"] if l["depot"] == str(depot.id) and l["quantite"] > 0]
        attendu = article["par_depot"].get(str(depot.id), stocks.ZERO)
        en_lots = sum((l["quantite"] for l in lots), stocks.ZERO)
        for lot in lots:
            lignes.append({"article": a, "lot": lot["lot"], "date_peremption": lot["date_peremption"], "attendu": lot["quantite"]})
        if attendu - en_lots != 0 or not lots:
            if a.actif or attendu:
                lignes.append({"article": a, "lot": "", "date_peremption": None, "attendu": attendu - en_lots})
    return lignes


def feuille(etat: list[dict], depot, *, institution: str, edite_par: str, a_l_aveugle=False) -> bytes:
    maintenant = timezone.localtime().strftime("%d/%m/%Y à %H:%M")
    lignes = lignes_d_inventaire(etat, depot)
    titres = ["Référence", "Article", "Lot", "Péremption", "Attendu", "Compté", "Remarque"]
    table = [[Paragraph(t, _ENTETE) for t in titres]]
    for ligne in lignes:
        a = ligne["article"]
        table.append([
            Paragraph(escape(a.reference), _CELLULE), Paragraph(escape(a.designation), _CELLULE), Paragraph(escape(ligne["lot"]), _CELLULE),
            Paragraph(ligne["date_peremption"].strftime("%d/%m/%Y") if ligne["date_peremption"] else "", _CELLULE),
            Paragraph("" if a_l_aveugle else f"{stocks._nombre(ligne['attendu'])} {escape(a.unite)}", _CELLULE), "", "",
        ])
    tableau = Table(table, colWidths=(26 * mm, 58 * mm, 22 * mm, 20 * mm, 20 * mm, 18 * mm, 22 * mm), repeatRows=1)
    tableau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), FOND_ENTETE), ("GRID", (0, 0), (-1, -1), 0.5, FILET), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("BOX", (5, 1), (5, -1), 1, colors.HexColor("#1e293b")),
    ]))
    contenu = [
        Paragraph(f"Feuille d'inventaire — {escape(depot.nom)}", _TITRE),
        Paragraph(f"{escape(institution)} — éditée le {maintenant} par {escape(edite_par)} — {len(lignes)} ligne(s) à compter"
                  + (" — inventaire à l'aveugle : comptez ce que vous voyez" if a_l_aveugle else ""), _SOUS),
        Spacer(1, 4 * mm), tableau, Spacer(1, 6 * mm),
        Paragraph("Compté le ……………………   par ………………………………………   Ce qui n'est pas sur la feuille s'ajoute à la main, en dessous.", _SOUS),
    ]
    tampon = io.BytesIO()
    document = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
                                 title=f"Feuille d'inventaire — {depot.nom}", author=edite_par)
    pied = f"Feuille d'inventaire — {depot.nom} — {institution} — éditée le {maintenant}"
    document.build(contenu, canvasmaker=lambda *args, **kwargs: _CanevasNumerote(*args, pied=pied, **kwargs))
    return tampon.getvalue()
