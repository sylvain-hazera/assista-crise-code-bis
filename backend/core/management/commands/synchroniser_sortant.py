"""Pousse vers le central les EvenementSynchronisation EN_ATTENTE accumulés localement — voir
core/sync_outbox.py pour le peuplement et SatelliteViewSet.synchroniser côté central pour
l'application. Exécuté en boucle par le conteneur `sync-sortant` (profil Full,
satellite/docker-compose.yml), toujours tenté que le central soit vu en ligne ou non par
etat_connectivite.py (décision utilisateur du 2026-09-18 : la synchro sortante ne dépend pas de
cet indicateur, elle échoue proprement toute seule si le central est injoignable).

Un coup par exécution (pas de boucle interne) — la boucle vit dans le conteneur, pas ici, même
esprit que les autres scripts satellite/ (etat_connectivite.py excepté, qui boucle lui-même
pour des raisons historiques propres à son usage direct hors Docker)."""
import logging

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import EtatEvenementSynchronisation, EvenementSynchronisation

logger = logging.getLogger(__name__)


def _serialiser_evenement(evenement):
    return {
        "id": str(evenement.id),
        "modele": evenement.modele,
        "objet_id": str(evenement.objet_id),
        "action": evenement.action,
        "payload": evenement.payload,
        "version_de_base": evenement.version_de_base.isoformat() if evenement.version_de_base else None,
        "auteur_local_email": evenement.auteur_local_email,
        "auteur_local_nom": evenement.auteur_local_nom,
    }


class Command(BaseCommand):
    help = "Pousse les événements de synchronisation locale en attente vers le central."

    def handle(self, *args, **options):
        central_url = settings.SATELLITE_CENTRAL_URL
        satellite_id = settings.SATELLITE_ID
        email = settings.SATELLITE_EMAIL
        password = settings.SATELLITE_PASSWORD
        if not all([central_url, satellite_id, email, password]):
            self.stdout.write(
                "SATELLITE_CENTRAL_URL/SATELLITE_ID/SATELLITE_EMAIL/SATELLITE_PASSWORD non "
                "configurés — synchronisation sortante inactive (comportement historique)."
            )
            return

        evenements = list(
            EvenementSynchronisation.objects
            .filter(etat=EtatEvenementSynchronisation.EN_ATTENTE)
            .order_by("cree_le")
        )
        if not evenements:
            return

        try:
            reponse_token = requests.post(
                f"{central_url.rstrip('/')}/api/token/", json={"email": email, "password": password}, timeout=15,
            )
            reponse_token.raise_for_status()
            jeton = reponse_token.json()["access"]

            reponse = requests.post(
                f"{central_url.rstrip('/')}/api/satellites/{satellite_id}/synchroniser/",
                json={"evenements": [_serialiser_evenement(e) for e in evenements]},
                headers={"Authorization": f"Bearer {jeton}"},
                timeout=60,
            )
            reponse.raise_for_status()
        except requests.RequestException as exc:
            # Central injoignable ou en erreur : rien à marquer, tout reste EN_ATTENTE pour le
            # prochain passage — jamais de connexion synchrone bloquante, voir la docstring du
            # module EvenementSynchronisation.
            logger.warning("Synchronisation sortante échouée (%s) — retentée au prochain passage.", exc)
            self.stdout.write(f"Échec de connexion au central : {exc}")
            return

        resultats_par_id = {r["id"]: r for r in reponse.json().get("resultats", [])}
        applique, en_conflit, en_erreur = 0, 0, 0
        for evenement in evenements:
            resultat = resultats_par_id.get(str(evenement.id))
            if resultat is None:
                continue
            if resultat["resultat"] in ("applique", "deja_applique"):
                evenement.etat = EtatEvenementSynchronisation.SYNCHRONISE
                evenement.synchronise_le = timezone.now()
                evenement.save(update_fields=["etat", "synchronise_le"])
                applique += 1
            elif resultat["resultat"] == "conflit":
                # Jamais retenté automatiquement : un administrateur doit arbitrer côté central
                # (ConflitSynchronisation) — retenter reposterait le même conflit en boucle.
                evenement.etat = EtatEvenementSynchronisation.CONFLIT
                evenement.erreur = resultat.get("detail", "")
                evenement.save(update_fields=["etat", "erreur"])
                en_conflit += 1
            else:
                # "erreur" : laissé EN_ATTENTE pour être retenté (peut être transitoire côté
                # central) — seul le message est mémorisé pour diagnostic.
                evenement.erreur = resultat.get("detail", "")
                evenement.save(update_fields=["erreur"])
                en_erreur += 1

        self.stdout.write(f"Synchronisation sortante : {applique} appliqué(s), {en_conflit} en conflit, {en_erreur} en erreur.")
