from django.core.exceptions import ValidationError
from PIL import Image

def validate_image_file(file):
    limit_mb = 5
    if file.size > limit_mb * 1024 * 1024:
        raise ValidationError(f"File too large. Size should not exceed {limit_mb} MB.")

    try:
        img = Image.open(file)
        img.verify()

        allowed_formats = ['JPEG', 'PNG', 'WEBP', 'GIF']
        if img.format not in allowed_formats:
            raise ValidationError(f"Unsupported image format: {img.format}. Allowed: {allowed_formats}")
            
    except Exception:
        raise ValidationError("Invalid image file. The file is corrupted or not an image.")