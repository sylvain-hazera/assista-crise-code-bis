"""Enregistre en base les comptes d'infrastructure du broker MQTT, à partir des mêmes secrets
que ceux dont le conteneur du broker s'amorce.

Pourquoi c'est indispensable et pas un confort : Django réécrit `passwd` et `acl` à partir de la
BASE (core/mqtt_comptes.py). Sans ces lignes, la première création de compte depuis l'interface
web réécrirait les fichiers sans les comptes d'amorçage -- l'exporteur de supervision et le pont
Meshtastic perdraient l'accès au broker, silencieusement.

Idempotent : un compte déjà enregistré n'est pas touché (son mot de passe peut avoir été
régénéré depuis l'interface, on ne le remet pas à la valeur du secret). À lancer après le premier
démarrage, et sans risque autant de fois qu'on veut.
"""
import os

from django.core.management.base import BaseCommand

from core.models import CompteMqtt, RoleCompteMqtt
from core.mqtt_comptes import ecrire_fichiers

# (nom du compte, fichier de secret, rôle, description) -- mêmes noms que la `command` du service
# mosquitto dans docker-compose.114.yml et que mosquitto/config/acl.114.
COMPTES = [
    ("exporter", "mqtt_exporter_password", RoleCompteMqtt.SUPERVISION,
     "Exporteur de métriques du broker (supervision)"),
    ("pont", "mqtt_pont_password", RoleCompteMqtt.RADIO,
     "Pont Meshtastic d'Assista-Crise"),
    ("passerelle1", "mqtt_passerelle1_password", RoleCompteMqtt.RADIO,
     "Première passerelle radio"),
]


class Command(BaseCommand):
    help = "Enregistre les comptes d'infrastructure du broker MQTT depuis /run/secrets."

    def add_arguments(self, parseur):
        parseur.add_argument(
            "--dossier-secrets", default="/run/secrets",
            help="Où lire les fichiers de secrets (par défaut /run/secrets).",
        )

    def handle(self, *args, **options):
        dossier = options["dossier_secrets"]
        crees, gardes, absents = 0, 0, []

        for nom, fichier_secret, role, description in COMPTES:
            if CompteMqtt.objects.filter(nom=nom).exists():
                gardes += 1
                continue
            chemin = os.path.join(dossier, fichier_secret)
            try:
                with open(chemin) as fichier:
                    mot_de_passe = fichier.read().strip()
            except OSError:
                absents.append(chemin)
                continue
            if not mot_de_passe:
                absents.append(chemin)
                continue
            CompteMqtt.objects.create(
                nom=nom, mot_de_passe=mot_de_passe, role=role, description=description,
                infrastructure=True,
            )
            crees += 1

        self.stdout.write(f"Comptes MQTT d'infrastructure : {crees} créé(s), {gardes} conservé(s).")
        for chemin in absents:
            # Pas une erreur fatale : en dev ou sur un satellite, ces secrets n'existent pas.
            self.stdout.write(f"  secret absent, compte non enregistré : {chemin}")

        if ecrire_fichiers():
            self.stdout.write("Fichiers du broker réécrits.")
        else:
            self.stdout.write("MQTT_COMPTES_DIR non configuré : fichiers du broker non réécrits.")
