"""Attestation PDF pour une DemandeMobilisation, avec QR code de vérification — voir
DemandeMobilisation.__doc__ (core/models.py) pour la nuance volontaire entre cette "demande" et
une réquisition légale au sens strict, reprise ici dans le texte du PDF lui-même.

Généré à la demande, jamais stocké : reconstruit à l'identique à chaque envoi/téléchargement à
partir des données actuelles de la demande (statut inclus) — jamais un PDF figé qui pourrait
diverger d'une révocation survenue après coup."""

import io

import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def nom_cible(demande) -> str:
    """Même résolution que DemandeMobilisationSerializer.get_cible_nom — dupliquée ici (pas
    réimportée) pour ne jamais faire dépendre la génération PDF de la couche serializers."""
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


def url_verification(demande, base_url: str) -> str:
    # /api/ : seul préfixe que le proxy (ac_proxy) route vers le backend Django — tout le reste
    # tombe sur le frontend Angular (SPA, try_files vers index.html), voir sa configuration
    # nginx. Cette page est volontairement servie en HTML directement par Django (pas une route
    # Angular), donc doit rester sous /api/ malgré son contenu.
    return f"{base_url.rstrip('/')}/api/verifier-mobilisation/{demande.jeton_verification}/"


def generer_pdf_demande_mobilisation(demande, base_url: str) -> bytes:
    """Retourne les octets du PDF (tout en mémoire, aucun fichier temporaire sur disque)."""
    qr_buffer = io.BytesIO()
    qrcode.make(url_verification(demande, base_url)).save(qr_buffer, format="PNG")
    qr_buffer.seek(0)

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    largeur, hauteur = A4
    marge = 20 * mm
    y = hauteur - marge

    c.setFont("Helvetica-Bold", 17)
    c.drawString(marge, y, "ATTESTATION DE MOBILISATION")
    y -= 9 * mm

    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.grey)
    c.drawString(
        marge, y,
        "Ce document ne constitue pas une réquisition au sens légal (article L. 2215-1 du CGCT) — il atteste",
    )
    y -= 4.2 * mm
    c.drawString(
        marge, y,
        "une demande formelle adressée par l'autorité émettrice, tracée sur la plateforme Assista Crise.",
    )
    c.setFillColor(colors.black)
    y -= 12 * mm

    def ligne(label: str, valeur: str):
        nonlocal y
        c.setFont("Helvetica-Bold", 10)
        c.drawString(marge, y, label)
        c.setFont("Helvetica", 10)
        c.drawString(marge + 48 * mm, y, (valeur or "—")[:75])
        y -= 7.5 * mm

    ligne("Autorité émettrice :", demande.institution_emettrice.nom)
    if demande.emetteur_id:
        emetteur_nom = f"{demande.emetteur.first_name} {demande.emetteur.last_name}".strip() or demande.emetteur.email
        ligne("Émis par :", emetteur_nom)
    ligne("Crise :", demande.crise.name)
    ligne("Destinataire :", nom_cible(demande))
    ligne("Nature de la demande :", demande.get_type_demande_display())
    if demande.point_operationnel_id:
        ligne("Lieu :", demande.point_operationnel.nom)
    elif demande.lieu_texte:
        ligne("Lieu :", demande.lieu_texte)
    if demande.motif:
        ligne("Motif :", demande.motif)
    ligne("Date d'émission :", demande.date_creation.strftime("%d/%m/%Y à %H:%M"))
    ligne("Statut :", demande.get_statut_display())

    y -= 8 * mm
    c.setFont("Helvetica", 9)
    c.drawString(marge, y, "Scannez ce QR code pour vérifier l'authenticité et le statut à jour de cette attestation :")
    y -= 3 * mm

    taille_qr = 32 * mm
    c.drawImage(ImageReader(qr_buffer), marge, y - taille_qr, width=taille_qr, height=taille_qr)

    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.grey)
    c.drawString(marge + taille_qr + 6 * mm, y - taille_qr / 2, url_verification(demande, base_url))
    c.setFillColor(colors.black)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()
