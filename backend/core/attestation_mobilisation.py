"""Attestation PDF pour une DemandeMobilisation, avec QR code de vérification — voir
DemandeMobilisation.__doc__ (core/models.py) pour la nuance volontaire entre cette "demande" et
une réquisition légale au sens strict, reprise ici dans le texte du PDF lui-même.

Mise en page "pliage en 4" (cadrage utilisateur du 2026-09-21, à partir d'un exemplaire de
référence fourni) : une page A4 divisée en 4 zones égales, chacune utile une fois le document
plié en deux puis en deux à nouveau —
  1 (haut-gauche)  : objet de la demande, identification du destinataire, immatriculation le
                     cas échéant.
  2 (haut-droite)  : QR code de vérification + mentions légales.
  3 (bas-gauche)   : point de rendez-vous — nom, adresse, coordonnées GPS, mini-carte.
  4 (bas-droite)   : contact à joindre en arrivant sur place, équipe, mission en cours.

Généré à la demande, jamais stocké : reconstruit à l'identique à chaque envoi/téléchargement à
partir des données actuelles de la demande (statut inclus) — jamais un PDF figé qui pourrait
diverger d'une révocation survenue après coup."""

import io
import math
from pathlib import Path

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as canvas_module
from reportlab.platypus import Frame, Image as RLImage, Paragraph, Spacer

LOGO_PATH = Path(__file__).parent / "static_assets" / "logo_assista_crise.png"

# Palette reprise du logo assista-crise (teal + charbon) — voir frontend/public/logo.png.
TEAL = colors.HexColor("#0d9488")
DARK = colors.HexColor("#1e293b")
GREY = colors.HexColor("#6b7280")
LIGHT_BORDER = colors.HexColor("#d1d5db")

TEXTE_LEGAL = (
    "Le titulaire déclare être en pleine possession de ses moyens et, le cas échéant, "
    "titulaire des permis de conduire et/ou certifications CACES requis pour la mission "
    "confiée. Ce document n'est ni une réquisition légale (article L. 2215-1 du CGCT), ni un "
    "laissez-passer opposable aux forces de l'ordre : il atteste une demande formelle émise "
    "par l'autorité mentionnée en zone 1, vérifiable via le QR code ci-dessus."
)

STYLE_TITRE_ZONE = ParagraphStyle(
    "titre_zone", fontName="Helvetica-Bold", fontSize=9.5, textColor=colors.white,
    backColor=TEAL, leading=13, spaceAfter=3.5 * mm, borderPadding=(4, 4, 4, 6),
)
STYLE_LABEL = ParagraphStyle(
    "label", fontName="Helvetica-Bold", fontSize=7.5, textColor=GREY, leading=9, spaceAfter=0.4 * mm,
)
STYLE_VALEUR = ParagraphStyle(
    "valeur", fontName="Helvetica", fontSize=10, textColor=DARK, leading=12.5, spaceAfter=2.6 * mm,
)
STYLE_VALEUR_FORTE = ParagraphStyle(
    "valeur_forte", fontName="Helvetica-Bold", fontSize=11, textColor=DARK, leading=13, spaceAfter=1.5 * mm,
)
STYLE_PETIT = ParagraphStyle(
    "petit", fontName="Helvetica", fontSize=8, textColor=GREY, leading=10, spaceAfter=2 * mm,
)
STYLE_LEGAL = ParagraphStyle(
    "legal", fontName="Helvetica", fontSize=6.6, textColor=GREY, leading=8.6, spaceAfter=1.5 * mm,
)
STYLE_URL = ParagraphStyle(
    "url", fontName="Helvetica", fontSize=6.6, textColor=TEAL, leading=8.6, spaceAfter=2.5 * mm,
)


def nom_cible(demande) -> str:
    if demande.cible_utilisateur_id:
        u = demande.cible_utilisateur
        return f"{u.first_name} {u.last_name}".strip() or u.email
    if demande.cible_institution_id:
        return demande.cible_institution.nom
    if demande.cible_offre_id:
        o = demande.cible_offre
        return f"{o.first_name_offer} {o.last_name_offer}".strip() or o.email_offer
    return "—"


def email_cible(demande) -> str | None:
    if demande.cible_utilisateur_id:
        return demande.cible_utilisateur.email
    if demande.cible_institution_id:
        return demande.cible_institution.email
    if demande.cible_offre_id:
        return demande.cible_offre.email_offer
    return None


def immatriculation_cible(demande) -> str | None:
    """Uniquement connue quand la cible est une offre d'aide ayant déclaré un véhicule (voir
    Offer.immatriculation) — jamais renseignée pour un utilisateur/institution inscrit."""
    if demande.cible_offre_id and demande.cible_offre.immatriculation:
        return demande.cible_offre.immatriculation
    return None


def url_verification(demande, base_url: str) -> str:
    # /api/ : seul préfixe que le proxy (ac_proxy) route vers le backend Django — tout le reste
    # tombe sur le frontend Angular (SPA, try_files vers index.html), voir sa configuration
    # nginx. Cette page est volontairement servie en HTML directement par Django (pas une route
    # Angular), donc doit rester sous /api/ malgré son contenu. `base_url` doit être le domaine
    # public assista-crise.fr (settings.SERVER_URL), jamais l'hôte de la requête qui a déclenché
    # la génération — demande explicite du 2026-09-21, le QR doit toujours pointer vers la même
    # adresse quel que soit l'endroit d'où l'attestation a été émise.
    return f"{base_url.rstrip('/')}/api/verifier-mobilisation/{demande.jeton_verification}/"


# ─────────────────────────────────────────────────────────────────────────────
# Mini-carte (zone 3) — mosaïque de tuiles OpenStreetMap publiques, la France n'est pas
# couverte par le tileserver auto-hébergé de ce projet (bordeaux.mbtiles uniquement, en tuiles
# vectorielles non rasterisables simplement) — décision utilisateur du 2026-09-21 après
# clarification explicite de ce compromis (dépendance externe + coordonnées GPS envoyées à
# l'infrastructure publique OSM).
# ─────────────────────────────────────────────────────────────────────────────

TAILLE_TUILE_OSM = 256
USER_AGENT_OSM = "AssistaCrise/1.0 (+https://www.assista-crise.fr; contact@assista-crise.fr)"


def _deg2num_frac(lat: float, lon: float, zoom: int):
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = (lon + 180.0) / 360.0 * n
    ytile = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


def generer_mini_carte(lat: float, lon: float, zoom: int = 16, taille_finale: int = 300):
    """Retourne un buffer PNG (BytesIO) avec un repère centré sur le point, ou None si la
    récupération des tuiles a échoué (pas de connexion, service OSM indisponible...) — ne lève
    jamais d'exception : un problème réseau externe ne doit jamais casser la génération du PDF,
    les coordonnées GPS restent affichées en texte à côté dans tous les cas (voir zone 3)."""
    try:
        import requests
        from PIL import Image, ImageDraw

        xfrac, yfrac = _deg2num_frac(lat, lon, zoom)
        xtile, ytile = int(xfrac), int(yfrac)

        mosaique = Image.new("RGB", (TAILLE_TUILE_OSM * 3, TAILLE_TUILE_OSM * 3), "#e5e7eb")
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT_OSM
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                tx, ty = xtile + dx, ytile + dy
                url = f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png"
                reponse = session.get(url, timeout=4)
                reponse.raise_for_status()
                tuile = Image.open(io.BytesIO(reponse.content)).convert("RGB")
                mosaique.paste(tuile, ((dx + 1) * TAILLE_TUILE_OSM, (dy + 1) * TAILLE_TUILE_OSM))

        px = int((xfrac - (xtile - 1)) * TAILLE_TUILE_OSM)
        py = int((yfrac - (ytile - 1)) * TAILLE_TUILE_OSM)
        demi = 150
        recadree = mosaique.crop((px - demi, py - demi, px + demi, py + demi)).resize(
            (taille_finale, taille_finale), Image.LANCZOS,
        )

        dessin = ImageDraw.Draw(recadree)
        cx, cy = taille_finale // 2, taille_finale // 2
        rayon = 8
        dessin.ellipse((cx - rayon, cy - rayon, cx + rayon, cy + rayon),
                        fill=(13, 148, 136), outline=(255, 255, 255), width=2)

        sortie = io.BytesIO()
        recadree.save(sortie, format="PNG")
        sortie.seek(0)
        return sortie
    except Exception:
        return None


def generer_qr_image(url: str) -> io.BytesIO:
    buffer = io.BytesIO()
    qrcode.make(url).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _contact_point(demande):
    """Contact à joindre à l'arrivée sur le point de rendez-vous (zone 4) — le responsable du
    point en priorité, sinon le leader ou le régulateur de l'équipe qui le tient, sinon aucun
    contact de terrain spécifique (repli sur l'institution émettrice, voir zone4_flowables)."""
    point = demande.point_operationnel
    if point is None:
        return None, None
    equipe = point.equipe
    if point.responsable_id:
        return point.responsable, equipe
    if equipe and equipe.leader_id:
        return equipe.leader, equipe
    if equipe and equipe.regulateur_id:
        return equipe.regulateur, equipe
    return None, equipe


# ─────────────────────────────────────────────────────────────────────────────
# Contenu des 4 zones
# ─────────────────────────────────────────────────────────────────────────────

def _zone1_flowables(demande):
    flow = [Paragraph("1 · OBJET &amp; IDENTIFICATION", STYLE_TITRE_ZONE)]
    flow.append(Paragraph("Autorité émettrice", STYLE_LABEL))
    flow.append(Paragraph(demande.institution_emettrice.nom, STYLE_VALEUR_FORTE))
    flow.append(Paragraph("Nature de la demande", STYLE_LABEL))
    flow.append(Paragraph(demande.get_type_demande_display(), STYLE_VALEUR))
    flow.append(Paragraph("Crise", STYLE_LABEL))
    flow.append(Paragraph(demande.crise.name, STYLE_VALEUR))
    flow.append(Paragraph("Destinataire", STYLE_LABEL))
    flow.append(Paragraph(nom_cible(demande), STYLE_VALEUR))
    immat = immatriculation_cible(demande)
    if immat:
        flow.append(Paragraph("Véhicule (immatriculation)", STYLE_LABEL))
        flow.append(Paragraph(immat, STYLE_VALEUR))
    if demande.motif:
        flow.append(Paragraph("Motif", STYLE_LABEL))
        flow.append(Paragraph(demande.motif, STYLE_VALEUR))
    flow.append(Paragraph(
        f"Réf. {str(demande.id)[:8].upper()} — émise le "
        f"{demande.date_creation.strftime('%d/%m/%Y à %H:%M')}", STYLE_PETIT,
    ))
    return flow


def _zone2_flowables(demande, base_url):
    url = url_verification(demande, base_url)
    flow = [Paragraph("2 · VÉRIFICATION &amp; MENTIONS LÉGALES", STYLE_TITRE_ZONE)]
    flow.append(RLImage(generer_qr_image(url), width=26 * mm, height=26 * mm))
    flow.append(Spacer(1, 1.5 * mm))
    flow.append(Paragraph(url, STYLE_URL))
    flow.append(Paragraph(f"Statut au moment de l'émission : {demande.get_statut_display()}.", STYLE_LEGAL))
    flow.append(Spacer(1, 1 * mm))
    flow.append(Paragraph(TEXTE_LEGAL, STYLE_LEGAL))
    return flow


def _zone3_flowables(demande):
    flow = [Paragraph("3 · POINT DE RENDEZ-VOUS", STYLE_TITRE_ZONE)]
    point = demande.point_operationnel
    if point is not None:
        flow.append(Paragraph(point.nom, STYLE_VALEUR_FORTE))
        if point.adresse:
            flow.append(Paragraph(point.adresse, STYLE_VALEUR))
        if point.location is not None:
            lat, lon = point.location.y, point.location.x
            flow.append(Paragraph(f"GPS : {lat:.5f}, {lon:.5f}", STYLE_PETIT))
            carte = generer_mini_carte(lat, lon)
            if carte is not None:
                flow.append(Spacer(1, 1.5 * mm))
                flow.append(RLImage(carte, width=38 * mm, height=38 * mm))
    elif demande.lieu_texte:
        flow.append(Paragraph(demande.lieu_texte, STYLE_VALEUR_FORTE))
    else:
        flow.append(Paragraph(
            "Aucun lieu de rendez-vous spécifique — se conformer aux instructions de "
            "l'autorité émettrice.", STYLE_VALEUR,
        ))
    return flow


def _zone4_flowables(demande):
    flow = [Paragraph("4 · CONTACT À VOTRE ARRIVÉE", STYLE_TITRE_ZONE)]
    contact, equipe = _contact_point(demande)

    if contact is not None:
        nom = f"{contact.first_name} {contact.last_name}".strip() or contact.email
        flow.append(Paragraph("Contact", STYLE_LABEL))
        flow.append(Paragraph(nom, STYLE_VALEUR_FORTE))
        if contact.phone_number:
            flow.append(Paragraph("Téléphone", STYLE_LABEL))
            flow.append(Paragraph(contact.phone_number, STYLE_VALEUR))
        flow.append(Paragraph("Email", STYLE_LABEL))
        flow.append(Paragraph(contact.email, STYLE_VALEUR))
    else:
        # Aucun contact de terrain spécifique (pas de point, ou point sans responsable/équipe) :
        # repli sur l'institution émettrice plutôt que de laisser la zone vide.
        inst = demande.institution_emettrice
        flow.append(Paragraph("Contact", STYLE_LABEL))
        flow.append(Paragraph(inst.nom, STYLE_VALEUR_FORTE))
        if inst.telephone:
            flow.append(Paragraph("Téléphone", STYLE_LABEL))
            flow.append(Paragraph(inst.telephone, STYLE_VALEUR))
        if inst.email:
            flow.append(Paragraph("Email", STYLE_LABEL))
            flow.append(Paragraph(inst.email, STYLE_VALEUR))

    if equipe is not None:
        flow.append(Paragraph("Équipe", STYLE_LABEL))
        flow.append(Paragraph(equipe.name, STYLE_VALEUR))
        if equipe.mission_active_id:
            flow.append(Paragraph("Mission en cours", STYLE_LABEL))
            flow.append(Paragraph(equipe.mission_active.titre, STYLE_VALEUR))
    return flow


def generer_pdf_demande_mobilisation(demande, base_url: str) -> bytes:
    """Retourne les octets du PDF (tout en mémoire, aucun fichier temporaire sur disque)."""
    buffer = io.BytesIO()
    largeur, hauteur = A4
    c = canvas_module.Canvas(buffer, pagesize=A4)

    hauteur_entete = 26 * mm
    c.setFillColor(colors.white)
    c.rect(0, hauteur - hauteur_entete, largeur, hauteur_entete, fill=1, stroke=0)

    try:
        c.drawImage(
            str(LOGO_PATH), 8 * mm, hauteur - hauteur_entete + 4 * mm,
            width=17 * mm, height=17 * mm, mask="auto", preserveAspectRatio=True,
        )
    except Exception:
        pass  # logo manquant : le reste du document reste généré normalement

    c.setFillColor(DARK)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(30 * mm, hauteur - 12.5 * mm, "ATTESTATION DE MOBILISATION")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(GREY)
    c.drawString(30 * mm, hauteur - 18.5 * mm, "Pliez ce document en deux, puis en deux à nouveau, pour un format poche.")

    c.setStrokeColor(TEAL)
    c.setLineWidth(1.2)
    c.line(0, hauteur - hauteur_entete, largeur, hauteur - hauteur_entete)

    # Grille 2x2 sous le bandeau — voir le docstring du module pour la correspondance zone/pli.
    zone_hauteur = (hauteur - hauteur_entete) / 2
    zone_largeur = largeur / 2
    zones = {
        1: (0, hauteur - hauteur_entete - zone_hauteur, zone_largeur, zone_hauteur),
        2: (zone_largeur, hauteur - hauteur_entete - zone_hauteur, zone_largeur, zone_hauteur),
        3: (0, 0, zone_largeur, zone_hauteur),
        4: (zone_largeur, 0, zone_largeur, zone_hauteur),
    }

    c.setStrokeColor(LIGHT_BORDER)
    c.setDash(2, 2.5)
    c.setLineWidth(0.7)
    c.line(zone_largeur, 0, zone_largeur, hauteur - hauteur_entete)
    c.line(0, zone_hauteur, largeur, zone_hauteur)
    c.setDash()

    contenus = {
        1: _zone1_flowables(demande),
        2: _zone2_flowables(demande, base_url),
        3: _zone3_flowables(demande),
        4: _zone4_flowables(demande),
    }
    marge_zone = 5 * mm
    for numero, (x, y, w, h) in zones.items():
        frame = Frame(
            x + marge_zone, y + marge_zone, w - 2 * marge_zone, h - 2 * marge_zone,
            showBoundary=0, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        )
        frame.addFromList(list(contenus[numero]), c)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()
