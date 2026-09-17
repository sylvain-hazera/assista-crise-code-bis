"""Détecteur de connectivité au central (assista-crise.fr) — source de vérité PARTAGÉE pour
tout le reste du satellite (bannière "vous utilisez le local alors que le central est
joignable", écran TFT de statut, décision d'un satellite GW de vers qui relayer) : un seul
processus vérifie et écrit l'état dans un fichier, tous les autres composants le LISENT plutôt
que de refaire chacun leur propre requête réseau — voir le cadrage "Chantier B" section 5
("le health-check central doit tester assista-crise spécifiquement, pas la connectivité
internet brute", décision reprise ici côté satellite).

Écriture atomique (fichier temporaire puis renommage) : un lecteur concurrent (ex: le futur
script d'écran TFT, lu en boucle) ne doit jamais voir un JSON tronqué en cours d'écriture."""
import asyncio
import json
import logging
import os
import time

import httpx

logger = logging.getLogger("etat-connectivite")

CENTRAL_URL = os.environ.get("CENTRAL_URL", "https://assista-crise.fr").rstrip("/")
CHEMIN_VERIFICATION = os.environ.get("CHEMIN_VERIFICATION", "/api/")
INTERVALLE_VERIFICATION_SECONDES = int(os.environ.get("INTERVALLE_VERIFICATION_SECONDES", "30"))
TIMEOUT_VERIFICATION_SECONDES = float(os.environ.get("TIMEOUT_VERIFICATION_SECONDES", "5"))
FICHIER_ETAT = os.environ.get("FICHIER_ETAT_CONNECTIVITE", "/var/run/satellite/etat_connectivite.json")


async def verifier_une_fois(client: httpx.AsyncClient) -> bool:
    """En ligne = le SITE répond (même une erreur 4xx/5xx applicative prouve qu'on l'a
    atteint) — seule une erreur réseau/timeout signifie hors-ligne. Ne vérifie jamais juste
    "internet en général" (ex: pinguer 8.8.8.8) : un DNS local en panne ou un pare-feu qui
    bloque spécifiquement assista-crise.fr doivent compter comme hors-ligne même si le reste
    d'internet fonctionne."""
    try:
        await client.get(f"{CENTRAL_URL}{CHEMIN_VERIFICATION}", timeout=TIMEOUT_VERIFICATION_SECONDES)
        return True
    except httpx.HTTPError:
        return False


def ecrire_etat(en_ligne: bool, depuis: float, fichier=None):
    fichier = fichier or FICHIER_ETAT
    os.makedirs(os.path.dirname(fichier), exist_ok=True)
    tmp = fichier + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "en_ligne": en_ligne,
            "depuis": depuis,
            "derniere_verification": time.time(),
            "central_url": CENTRAL_URL,
        }, f)
    os.replace(tmp, fichier)


async def boucle(client=None, fichier_etat=None, une_seule_iteration=False):
    etat_precedent = None
    depuis = time.time()
    ferme_client = client is None
    client = client or httpx.AsyncClient()
    try:
        while True:
            en_ligne = await verifier_une_fois(client)
            maintenant = time.time()
            if en_ligne != etat_precedent:
                logger.info(
                    "Changement d'état : %s -> %s",
                    etat_precedent, "EN_LIGNE" if en_ligne else "HORS_LIGNE",
                )
                depuis = maintenant
                etat_precedent = en_ligne
            ecrire_etat(en_ligne, depuis, fichier=fichier_etat)
            if une_seule_iteration:
                return en_ligne
            await asyncio.sleep(INTERVALLE_VERIFICATION_SECONDES)
    finally:
        if ferme_client:
            await client.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(boucle())
