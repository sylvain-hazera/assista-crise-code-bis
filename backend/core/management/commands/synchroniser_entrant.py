"""Applique localement le rafraîchissement central -> local (SatelliteViewSet.donnees) — deux
régimes, voir core/sync_outbox.py pour le détail complet de chacun :

- **Dossier/Mission** (MUTABLE, voir `appliquer_objet_mutable`) : un objet avec une écriture
  locale encore EN_ATTENTE est ignoré (jamais écrasé silencieusement — exactement ce que toute
  cette mécanique existe pour éviter). `modifie_le` posé à la valeur EXACTE reçue du central
  (pas "maintenant" — auto_now l'aurait sinon réécrasée) via `QuerySet.update()`, qui ne
  déclenche aucun signal : c'est ce qui permet à une future écriture locale de capturer une
  `version_de_base` qui correspond vraiment à ce que le central connaît, plutôt qu'un horodatage
  local arbitraire qui déclencherait un faux conflit au prochain envoi. Un conflit déjà tranché
  côté central (`ConflitSynchronisationViewSet.resoudre`) redescend donc automatiquement dès ce
  passage, puisque rien ne le bloque plus une fois résolu.
- **Crisis/Request/Offer/Information** (voir `sync_outbox.appliquer_payload_pull`) : upsert par
  id, jamais de conflit possible à détecter (pas dans `sync_outbox.MODELES_SYNCHRONISABLES` —
  jamais édités localement, alimentés par les citoyens via internet, le central fait toujours
  autorité). Les FK vers un catalogue partagé (RequestType/OfferType/InformationType/
  MaterielCatalogue/Competence, peuplé indépendamment par ses propres migrations sur chaque
  déploiement — un même uuid n'a AUCUNE raison de coïncider entre central et satellite) sont
  résolues par clé naturelle (nom métier) plutôt que par id, get_or_create localement si
  absentes — voir sync_outbox.MODELES_PULL_SEUL. Un auteur (`author`) pas encore connu
  localement (aucun mécanisme de synchronisation des comptes utilisateurs à ce jour) est mis à
  None plutôt que de bloquer tout l'enregistrement."""
import logging

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import EtatEvenementSynchronisation, EvenementSynchronisation

logger = logging.getLogger(__name__)

MODELES_MUTABLES_ENTRANTS = ("Dossier", "Mission")
MODELES_PULL_SEUL_ENTRANTS = ("Crisis", "Request", "Offer", "Information")
CLES_JSON_PAR_MODELE = {
    "Dossier": "dossiers", "Mission": "missions",
    "Crisis": "crises", "Request": "demandes", "Offer": "offres", "Information": "signalements",
}


def appliquer_objet_mutable(apps_get_model, nom_modele, item):
    """Renvoie "applique", "ignore_local_en_attente" ou "erreur" — jamais tout ou rien pour le
    lot entier (voir la docstring du module)."""
    objet_id = item["id"]
    if EvenementSynchronisation.objects.filter(
        modele=nom_modele, objet_id=objet_id, etat=EtatEvenementSynchronisation.EN_ATTENTE,
    ).exists():
        return "ignore_local_en_attente"

    ModeleClasse = apps_get_model('core', nom_modele)
    champs = {k: v for k, v in item.items() if k not in ("id", "modifie_le")}
    modifie_le_central = item["modifie_le"]

    if ModeleClasse.objects.filter(pk=objet_id).exists():
        ModeleClasse.objects.filter(pk=objet_id).update(modifie_le=modifie_le_central, **champs)
    else:
        objet = ModeleClasse(id=objet_id, **champs)
        objet._synchronisation_entrante = True
        objet.save()
        ModeleClasse.objects.filter(pk=objet_id).update(modifie_le=modifie_le_central)

    # La copie centrale vient d'être acceptée comme nouvelle référence : un conflit resté en
    # l'état (déjà tranché côté central, voir ConflitSynchronisationViewSet.resoudre) n'a plus
    # lieu d'être bloquant localement.
    EvenementSynchronisation.objects.filter(
        modele=nom_modele, objet_id=objet_id, etat=EtatEvenementSynchronisation.CONFLIT,
    ).delete()
    return "applique"


class Command(BaseCommand):
    help = "Applique localement le rafraîchissement central -> local (SatelliteViewSet.donnees)."

    def handle(self, *args, **options):
        from django.apps import apps

        from core.sync_outbox import appliquer_payload_pull

        central_url = settings.SATELLITE_CENTRAL_URL
        satellite_id = settings.SATELLITE_ID
        email = settings.SATELLITE_EMAIL
        password = settings.SATELLITE_PASSWORD
        if not all([central_url, satellite_id, email, password]):
            self.stdout.write(
                "SATELLITE_CENTRAL_URL/SATELLITE_ID/SATELLITE_EMAIL/SATELLITE_PASSWORD non "
                "configurés — synchronisation entrante inactive (comportement historique)."
            )
            return

        try:
            reponse_token = requests.post(
                f"{central_url.rstrip('/')}/api/token/", json={"email": email, "password": password}, timeout=15,
            )
            reponse_token.raise_for_status()
            jeton = reponse_token.json()["access"]

            reponse = requests.get(
                f"{central_url.rstrip('/')}/api/satellites/{satellite_id}/donnees/",
                headers={"Authorization": f"Bearer {jeton}"},
                timeout=60,
            )
            reponse.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Synchronisation entrante échouée (%s) — retentée au prochain passage.", exc)
            self.stdout.write(f"Échec de connexion au central : {exc}")
            return

        donnees = reponse.json()
        compteurs = {"applique": 0, "ignore_local_en_attente": 0, "erreur": 0}

        for nom_modele in MODELES_MUTABLES_ENTRANTS:
            for item in donnees.get(CLES_JSON_PAR_MODELE[nom_modele], []):
                try:
                    resultat = appliquer_objet_mutable(apps.get_model, nom_modele, item)
                except Exception:
                    logger.exception("Échec application entrante %s %s", nom_modele, item.get("id"))
                    resultat = "erreur"
                compteurs[resultat] += 1

        for nom_modele in MODELES_PULL_SEUL_ENTRANTS:
            ModeleClasse = apps.get_model('core', nom_modele)
            for item in donnees.get(CLES_JSON_PAR_MODELE[nom_modele], []):
                try:
                    appliquer_payload_pull(apps.get_model, ModeleClasse, nom_modele, item)
                    compteurs["applique"] += 1
                except Exception:
                    logger.exception("Échec application entrante %s %s", nom_modele, item.get("id"))
                    compteurs["erreur"] += 1

        self.stdout.write(
            f"Synchronisation entrante : {compteurs['applique']} appliqué(s), "
            f"{compteurs['ignore_local_en_attente']} ignoré(s) (écriture locale en attente), "
            f"{compteurs['erreur']} erreur(s)."
        )
