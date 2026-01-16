import uuid
from django.db import models
from django.contrib.gis.db import models
from django.contrib.auth.models import AbstractUser

# Create your models here.

class TypeUtilisateur(models.Model):
    type = models.CharField(max_length=50)

    def __str__(self):
        return self.type


class Utilisateur(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # mdp = models.CharField(max_length=255)
    # login = models.CharField(max_length=150, unique=True)
    # prenom = models.CharField(max_length=60)
    # nom = models.CharField(max_length=80)
    # email = models.EmailField(unique=True)
    photo = models.ImageField(upload_to='photos/', null=True, blank=True)
    type_utilisateur = models.ForeignKey(TypeUtilisateur, on_delete=models.SET_NULL, null=True)

class Crise(models.Model):
    id = models.UUIDField(primary_key=True, default=models.UUIDField, editable=False)
    nom = models.CharField(max_length=100)
    localisation = models.PointField(srid=4326)
    debut = models.DateTimeField(auto_now_add=True)
    fin = models.DateTimeField(null=True, blank=True)

