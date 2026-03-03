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