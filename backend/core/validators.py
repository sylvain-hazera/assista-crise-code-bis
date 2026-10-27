from django.core.exceptions import ValidationError
from PIL import Image

def validate_image_file(file):
    limit_mb = 5
    if file.size > limit_mb * 1024 * 1024:
        raise ValidationError(f"Fichier trop volumineux. La taille ne doit pas dépasser {limit_mb} Mo.")

    try:
        img = Image.open(file)
        img.verify()

        allowed_formats = ['JPEG', 'PNG', 'WEBP', 'GIF']
        if img.format not in allowed_formats:
            raise ValidationError(f"Format d'image non supporté : {img.format}. Formats autorisés : {allowed_formats}")
            
    except Exception:
        raise ValidationError("Fichier image invalide. Le fichier est corrompu ou n'est pas une image.")


def validate_convention_file(file):
    """Convention signée entre une collectivité et une entreprise (voir SiteSensible) : mêmes
    contraintes qu'un scan de pièce — PDF ou photo, 10 Mo — parce qu'une convention arrive de la
    même façon, scannée au service ou photographiée en mairie."""
    validate_identity_document_file(file)


def validate_identity_document_file(file):
    """Pour les pièces d'identité (voir PieceIdentiteReserve) : contrairement à
    validate_image_file, accepte aussi un PDF (scan) en plus d'une photo, et une limite plus
    généreuse (un scan recto/verso dépasse facilement 5 Mo)."""
    limit_mb = 10
    if file.size > limit_mb * 1024 * 1024:
        raise ValidationError(f"Fichier trop volumineux. La taille ne doit pas dépasser {limit_mb} Mo.")

    position = file.tell()
    header = file.read(5)
    file.seek(position)
    if header[:5] == b"%PDF-":
        return

    try:
        img = Image.open(file)
        img.verify()
        allowed_formats = ['JPEG', 'PNG']
        if img.format not in allowed_formats:
            raise ValidationError(f"Format non supporté : {img.format}. Formats autorisés : {allowed_formats} ou PDF.")
    except ValidationError:
        raise
    except Exception:
        raise ValidationError("Fichier invalide. Le fichier est corrompu ou n'est ni une image JPEG/PNG ni un PDF.")
    finally:
        file.seek(position)