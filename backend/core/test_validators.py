import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from core.validators import validate_image_file
from io import BytesIO
from PIL import Image


@pytest.mark.django_db
class TestImageValidator:
    """Tests du validateur d'images"""
    
    def create_test_image(self, format='PNG', size=(100, 100), file_size_mb=None):
        """Créer une image de test"""
        img = Image.new('RGB', size, color='red')
        img_io = BytesIO()
        img.save(img_io, format=format)
        img_io.seek(0)
        
        # Si on veut une taille spécifique, remplir avec des données
        if file_size_mb:
            target_size = file_size_mb * 1024 * 1024
            img_io = BytesIO(b'0' * int(target_size))
        
        return SimpleUploadedFile(
            f"test.{format.lower()}",
            img_io.getvalue(),
            content_type=f"image/{format.lower()}"
        )
    
    def test_valid_png_image(self):
        """Test image PNG valide"""
        file = self.create_test_image('PNG')
        try:
            validate_image_file(file)
        except ValidationError:
            pytest.fail("Image PNG valide ne devrait pas lever d'exception")
    
    def test_valid_jpeg_image(self):
        """Test image JPEG valide"""
        file = self.create_test_image('JPEG')
        try:
            validate_image_file(file)
        except ValidationError:
            pytest.fail("Image JPEG valide ne devrait pas lever d'exception")
    
    def test_valid_webp_image(self):
        """Test image WEBP valide"""
        file = self.create_test_image('WEBP')
        try:
            validate_image_file(file)
        except ValidationError:
            pytest.fail("Image WEBP valide ne devrait pas lever d'exception")
    
    def test_valid_gif_image(self):
        """Test image GIF valide"""
        file = self.create_test_image('GIF')
        try:
            validate_image_file(file)
        except ValidationError:
            pytest.fail("Image GIF valide ne devrait pas lever d'exception")
    
    def test_image_too_large(self):
        """Test image trop volumineuse (> 5 Mo)"""
        file = self.create_test_image('PNG', file_size_mb=6)
        
        with pytest.raises(ValidationError) as exc_info:
            validate_image_file(file)
        
        assert "Fichier trop volumineux" in str(exc_info.value)
        assert "5 Mo" in str(exc_info.value)
    
    def test_invalid_format_bmp(self):
        """Test format non autorisé (BMP)"""
        file = self.create_test_image('BMP')
        
        with pytest.raises(ValidationError) as exc_info:
            validate_image_file(file)
        
        # BMP est capturé par l'exception générale car verify() échoue avant
        assert "Fichier image invalide" in str(exc_info.value) or "Format d'image non supporté" in str(exc_info.value)
    
    def test_corrupted_file(self):
        """Test fichier corrompu"""
        corrupted_file = SimpleUploadedFile(
            "corrupted.png",
            b"This is not an image file",
            content_type="image/png"
        )
        
        with pytest.raises(ValidationError) as exc_info:
            validate_image_file(corrupted_file)
        
        assert "Fichier image invalide" in str(exc_info.value)
