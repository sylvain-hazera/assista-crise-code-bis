"""Envoi de SMS au nom d'une institution : registre de fournisseurs, et rien d'autre.

Même forme que le registre de canaux d'alerte PCS (`core/alertes_pcs.py`), écrit « pour que
SMS/Intramuros/Facebook s'ajoutent plus tard par une fonction + une entrée, sans toucher au
reste ». Ajouter un opérateur = une fonction d'envoi + une entrée dans `FOURNISSEURS`. Aucune
migration : `ConfigurationEnvoiInstitution.fournisseur_sms` est une chaîne libre, pas un choix
figé.

**Mobimel n'est PAS implémenté, et c'est volontaire** (11/11/2026). L'opérateur existe — il
apparaît comme fournisseur SMS chez d'autres éditeurs français — mais aucune documentation
publique de son API n'a pu être trouvée : ni endpoint, ni paramètres, ni forme
d'authentification. Écrire un adaptateur sur des suppositions produirait du code qui compile,
qui a l'air juste, et qui échoue au premier envoi réel — avec en plus le risque d'envoyer des
identifiants à une URL inventée. Il faut la documentation de Mobimel, ou la page « API » du
compte client.

Tout le reste est construit : la configuration par institution, le stockage chiffré de la clé,
l'écran de saisie, la journalisation et le point d'appel. L'adaptateur est la seule pièce
manquante, et elle tient en une fonction.
"""
import logging

logger = logging.getLogger(__name__)


class EchecSms(Exception):
    """Envoi refusé ou impossible. `detail` est destiné à la main courante."""

    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


class FournisseurNonImplemente(EchecSms):
    """Le fournisseur est déclaré dans la configuration mais n'a pas d'adaptateur.

    Distinct d'`EchecSms` pour que l'appelant puisse le dire autrement : ce n'est pas une panne,
    c'est une fonctionnalité qui n'existe pas encore, et le message à l'écran n'est pas le
    même."""


def _envoyer_mobimel(cle_api, expediteur, numero, message):
    """Adaptateur Mobimel — EN ATTENTE DE SA DOCUMENTATION.

    Lève délibérément plutôt que de deviner un contrat. Ce qu'il faut pour l'écrire :

    - l'URL de l'endpoint d'envoi et la méthode HTTP ;
    - le nom exact de l'en-tête (ou du paramètre) qui porte la clé ;
    - la forme du corps : nom des champs du numéro, du message, de l'expéditeur ;
    - le format attendu du numéro (international `+33…`, national `06…`, ou `336…`) ;
    - ce que renvoie un succès, et ce que renvoie un refus.

    Le format du numéro est le point le plus souvent faux dans ce genre d'intégration : un
    opérateur qui attend `33612345678` et reçoit `+33612345678` accepte l'appel et ne livre
    rien. C'est pour cela qu'il est listé ici et qu'on ne le suppose pas."""
    raise FournisseurNonImplemente(
        "L'envoi par Mobimel n'est pas encore implémenté : la documentation de son API est "
        "nécessaire (endpoint, en-tête de clé, champs du corps, format du numéro)."
    )


def _envoyer_brevo(cle_api, expediteur, numero, message):
    """SMS transactionnel par Brevo — la même clé API que pour les emails."""
    from .envoi_brevo import EchecBrevo, envoyer_sms_brevo

    try:
        return envoyer_sms_brevo(cle_api, expediteur, numero, message)
    except EchecBrevo as echec:
        raise EchecSms(echec.detail) from echec


#: Fournisseurs connus. La clé est ce qu'on stocke dans
#: `ConfigurationEnvoiInstitution.fournisseur_sms`.
FOURNISSEURS = {
    "BREVO": {
        "libelle": "Brevo (même clé que les emails)",
        "envoyer": _envoyer_brevo,
        "implemente": True,
    },
    "MOBIMEL": {
        "libelle": "Mobimel",
        "envoyer": _envoyer_mobimel,
        "implemente": False,
    },
}


def fournisseurs_disponibles():
    """Pour l'écran de configuration : ce qu'on peut proposer, et ce qui marche vraiment.

    `implemente` est servi à l'interface plutôt que de masquer les fournisseurs non terminés :
    un opérateur absent de la liste laisse croire qu'il n'est pas prévu, alors qu'il attend sa
    documentation. Le dire est plus utile que de le cacher — même raisonnement que
    `invitationImpossible` sur le bloc d'ajout, où nommer un geste impossible vaut mieux que de
    le laisser manquer."""
    return [
        {"code": code, "libelle": infos["libelle"], "implemente": infos["implemente"]}
        for code, infos in sorted(FOURNISSEURS.items())
    ]


def envoyer_sms_pour_institution(institution, numero, message):
    """Envoie un SMS au nom de l'institution.

    Renvoie `(True, identifiant)` ou `(False, motif)`. Ne lève jamais : un SMS est un canal
    d'appoint, et son échec ne doit pas faire échouer l'action qui l'accompagne — c'est la même
    posture que `send_mail_logged` avec `fail_silently` pour les emails d'accompagnement.
    """
    from django.utils import timezone

    from .envoi_institution import configuration_envoi

    config = configuration_envoi(institution)
    if config is None or not config.sms_configure:
        return False, "non configuré"

    fournisseur = FOURNISSEURS.get(config.fournisseur_sms)
    if fournisseur is None:
        motif = f"Fournisseur SMS inconnu : « {config.fournisseur_sms} »."
        _noter_echec(config, motif)
        return False, motif

    try:
        identifiant = fournisseur["envoyer"](
            cle_api=config.cle_sms_effective,
            expediteur=config.sms_expediteur or (institution.nom_affichage or institution.nom),
            numero=numero,
            message=message,
        )
    except EchecSms as echec:
        _noter_echec(config, echec.detail)
        logger.warning("Envoi SMS refusé pour « %s » : %s", institution.nom, echec.detail)
        return False, echec.detail
    except Exception as erreur:
        _noter_echec(config, f"Erreur inattendue : {erreur}")
        logger.exception("Erreur inattendue à l'envoi SMS pour « %s ».", institution.nom)
        return False, str(erreur)

    config.dernier_envoi_sms_le = timezone.now()
    config.derniere_erreur_sms = ""
    config.save(update_fields=['dernier_envoi_sms_le', 'derniere_erreur_sms',
                               'date_modification'])
    return True, identifiant


def _noter_echec(config, detail):
    config.derniere_erreur_sms = (detail or "")[:500]
    config.save(update_fields=['derniere_erreur_sms', 'date_modification'])
