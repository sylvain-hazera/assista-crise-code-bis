"""Photos remontées d'un satellite au central (lot F, 20/11/2026).

Les fichiers ne passent pas par la file d'événements (core/sync_outbox.py, du JSON) : une photo
d'un bien (évaluation des dégâts) ou d'un dossier, déposée sur le satellite pendant une coupure,
part ensuite par `POST /api/satellites/<id>/pieces/`, une par une, avec son empreinte SHA-256.
Le central recalcule l'empreinte des octets reçus et refuse la pièce si elle diffère : la photo
scellée au moment du constat arrive telle quelle, ou pas du tout.

Une pièce dont le bien ou le dossier n'est pas encore connu du central (son événement n'est pas
encore passé) est simplement retentée au passage suivant. Une pièce acceptée est notée
(`PieceEnvoyee`) et n'est jamais renvoyée.
"""
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

PIECES_PAR_PASSAGE = 20


# ── Côté satellite ──

def a_envoyer():
    """Les photos de biens et de dossiers déposées ici et pas encore acceptées par le central."""
    from django.db.models import Q

    from .models import Document, PieceEnvoyee

    deja = PieceEnvoyee.objects.values_list("document_id", flat=True)
    return (Document.objects.filter(Q(habitation__isnull=False) | Q(dossier__isnull=False))
            .exclude(id__in=deja).order_by("date_upload")[:PIECES_PAR_PASSAGE])


def envoyer(poster):
    """Envoie les photos en attente. `poster(donnees, fichiers)` rend (code HTTP, corps JSON).
    Rend {"envoyees", "en_attente"}."""
    from .models import PieceEnvoyee

    envoyees = en_attente = 0
    for document in a_envoyer():
        try:
            with document.fichier.open("rb") as flux:
                octets = flux.read()
        except (OSError, ValueError):
            logger.warning("Photo %s illisible sur le satellite : non envoyée.", document.id)
            en_attente += 1
            continue
        donnees = {
            "id": str(document.id), "sha256": document.sha256 or hashlib.sha256(octets).hexdigest(),
            "habitation": str(document.habitation_id or ""), "dossier": str(document.dossier_id or ""),
            "auteur": str(document.auteur_id or ""), "commentaire": document.commentaire or "",
            "date_upload": document.date_upload.isoformat() if document.date_upload else "",
            "metadata_publiques": json.dumps(document.metadata_publiques or {}),
            "metadata_privees": json.dumps(document.metadata_privees or {}),
        }
        code, _corps = poster(donnees, {"fichier": (document.fichier.name.rsplit("/", 1)[-1], octets)})
        if code in (200, 201):
            PieceEnvoyee.objects.get_or_create(document_id=document.id)
            envoyees += 1
        else:
            en_attente += 1
    return {"envoyees": envoyees, "en_attente": en_attente}


# ── Côté central ──

class PieceRefusee(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def recevoir(satellite, donnees, fichier):
    """Enregistre une photo envoyée par un satellite. Rend (document, créé). Lève PieceRefusee."""
    import uuid

    from django.utils.dateparse import parse_datetime

    from .models import Document, Dossier, Habitation, User

    try:
        identifiant = uuid.UUID(str(donnees.get("id")))
    except (TypeError, ValueError):
        raise PieceRefusee("id : identifiant de la pièce attendu")
    if fichier is None:
        raise PieceRefusee("fichier manquant")
    octets = fichier.read()
    empreinte = hashlib.sha256(octets).hexdigest()
    if (donnees.get("sha256") or "").lower() != empreinte:
        raise PieceRefusee("l'empreinte du fichier reçu ne correspond pas à celle du satellite")
    existant = Document.objects.filter(pk=identifiant).first()
    if existant is not None:
        if existant.sha256 != empreinte:
            raise PieceRefusee("une autre pièce porte déjà cet identifiant", code=409)
        return existant, False

    environnement = satellite.environment
    habitation = dossier = None
    if donnees.get("habitation"):
        habitation = Habitation.objects.filter(pk=donnees["habitation"], environment=environnement).first()
        if habitation is None:
            raise PieceRefusee("bien inconnu du central (pas encore synchronisé)", code=404)
    if donnees.get("dossier"):
        dossier = Dossier.objects.filter(pk=donnees["dossier"], environment=environnement).first()
        if dossier is None:
            raise PieceRefusee("dossier inconnu du central (pas encore synchronisé)", code=404)
    if habitation is None and dossier is None:
        raise PieceRefusee("une pièce se rattache à un bien ou à un dossier")

    def _json(texte):
        try:
            valeur = json.loads(texte or "{}")
        except ValueError:
            return {}
        return valeur if isinstance(valeur, dict) else {}

    from django.core.files.base import ContentFile

    auteur = User.objects.filter(pk=donnees.get("auteur") or None).first() if donnees.get("auteur") else None
    document = Document(id=identifiant, auteur=auteur, commentaire=donnees.get("commentaire") or "", sha256=empreinte,
                        metadata_publiques=_json(donnees.get("metadata_publiques")),
                        metadata_privees=_json(donnees.get("metadata_privees")),
                        habitation=habitation, dossier=dossier, environment=environnement)
    document.fichier.save(getattr(fichier, "name", None) or f"{identifiant}.jpg", ContentFile(octets), save=False)
    document.save()
    date = parse_datetime(donnees.get("date_upload") or "")
    if date is not None:
        Document.objects.filter(pk=document.pk).update(date_upload=date)
    return document, True
