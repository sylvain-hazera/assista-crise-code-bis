"""Envoi d'un email par l'API transactionnelle Brevo, au nom d'une institution.

Lève la limite inscrite dans `core/branding.py` depuis l'origine : « compte SMTP unique
Assista-Crise en v1, `reply_to` est le seul levier de personnalisation de l'adresse pour
l'instant ». Une institution qui fournit sa clé Brevo envoie désormais depuis SA propre adresse,
et Assista-Crise n'apparaît plus nulle part dans le message.

Contrat relevé dans la documentation Brevo (developers.brevo.com, reference/send-transac-email
et docs/send-a-transactional-email, lus le 11/11/2026) :

- `POST https://api.brevo.com/v3/smtp/email` ;
- clé dans l'en-tête **`api-key`** — pas `Authorization: Bearer`, qui renvoie 401 ;
- corps : `sender {name, email}`, `to [{email, name}]`, `subject`, et UN SEUL des trois corps
  possibles (`htmlContent`, `textContent`, `templateId`). Nos messages sont en texte brut, donc
  `textContent` seul, comme l'exemple « Text Body » de la documentation ;
- succès : **201** avec `{"messageId": "..."}` ; `202` pour un envoi programmé, qu'on n'utilise
  pas ;
- échec : **400** avec `{"code": "...", "message": "..."}`. Les codes documentés incluent
  `api-key not found`, `Authentication failed`, `unauthorized`, `Insufficient credits`,
  `Domain does not exist` ;
- `429` au-delà des quotas.

Deux choses que la documentation NE dit pas, et qu'on traite donc défensivement : le code HTTP
exact d'une clé invalide (elle ne documente que 400, sans entrée 401/403), et l'erreur renvoyée
pour un expéditeur non vérifié. Tout statut hors 2xx est donc traité de la même façon — un échec
nommé, avec le corps de la réponse remonté tel quel à l'appelant pour la main courante.

**L'adresse expéditrice doit être un « sender » vérifié dans le compte Brevo de l'institution.**
C'est une condition côté partenaire, pas côté code : sans vérification, l'API refuse l'envoi. Le
message d'erreur de Brevo est remonté intact, parce que c'est lui qui le dit.
"""
import json
import logging

import requests

logger = logging.getLogger(__name__)

URL_BREVO = "https://api.brevo.com/v3/smtp/email"

# 20 s : un envoi transactionnel est rapide, et un appel HTTP dans le cycle d'une requête web
# ne doit pas pouvoir la bloquer longtemps. Au-delà, on retombe sur le SMTP (voir l'appelant).
DELAI_MAX_S = 20


class EchecBrevo(Exception):
    """Envoi refusé ou impossible. `detail` est destiné à la main courante, pas à l'utilisateur
    final : il contient le message de Brevo, qui nomme la cause (clé, quota, domaine)."""

    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


def envoyer_email_brevo(cle_api, expediteur_email, expediteur_nom, sujet, message,
                        destinataires, reply_to=None):
    """Envoie un email texte et renvoie le `messageId` de Brevo.

    Lève `EchecBrevo` sur tout refus, panne réseau ou réponse inattendue. L'appelant décide quoi
    en faire — voir `core/envoi_institution.py`, qui retombe sur le SMTP Assista-Crise en
    conservant le texte de l'institution.
    """
    if not cle_api or not expediteur_email:
        raise EchecBrevo("Configuration Brevo incomplète (clé ou adresse expéditrice absente).")
    if not destinataires:
        raise EchecBrevo("Aucun destinataire.")

    expediteur = {"email": expediteur_email}
    if expediteur_nom:
        # 70 caractères maximum d'après la documentation ; tronqué plutôt que refusé, un nom
        # d'association un peu long ne doit pas empêcher un envoi.
        expediteur["name"] = expediteur_nom[:70]

    charge = {
        "sender": expediteur,
        "to": [{"email": adresse} for adresse in destinataires],
        "subject": sujet,
        # `textContent` SEUL : la documentation dit « You can only pick one of the three body
        # types per request ». Ajouter un htmlContent dérivé changerait l'apparence du message
        # et nous en ferions une seconde version à maintenir.
        "textContent": message,
    }
    if reply_to:
        charge["replyTo"] = {"email": reply_to}

    try:
        reponse = requests.post(
            URL_BREVO,
            headers={
                # Noms d'en-têtes conformes à la documentation. `api-key` et non
                # `Authorization` : l'autre forme renvoie 401.
                "api-key": cle_api,
                "Content-Type": "application/json",
                "accept": "application/json",
            },
            data=json.dumps(charge),
            timeout=DELAI_MAX_S,
        )
    except requests.RequestException as erreur:
        raise EchecBrevo(f"Brevo injoignable : {erreur}") from erreur

    if reponse.status_code == 429:
        raise EchecBrevo("Quota Brevo dépassé (429).")

    if not 200 <= reponse.status_code < 300:
        raise EchecBrevo(f"Brevo a refusé l'envoi ({reponse.status_code}) : "
                         f"{_message_erreur(reponse)}")

    # 201 porte un messageId ; 202 (envoi programmé, non utilisé ici) a un corps non documenté.
    # On ne fait donc pas dépendre le succès de la présence du champ.
    try:
        return (reponse.json() or {}).get("messageId") or ""
    except ValueError:
        return ""


def _message_erreur(reponse):
    """Le message de Brevo, ou le corps brut. Jamais une phrase de notre cru : c'est ce texte
    qui dit si la clé est invalide, le quota dépassé ou l'expéditeur non vérifié, et le
    remplacer par « erreur d'envoi » ferait perdre la seule information utile."""
    try:
        corps = reponse.json() or {}
    except ValueError:
        return (reponse.text or "")[:300]
    code = corps.get("code")
    message = corps.get("message") or (reponse.text or "")[:300]
    return f"{code} — {message}" if code else message


# ══ SMS et crédits : la même clé API ══════════════════════════════════════════════════════════
#
# Ajouté le 12/11/2026. Contrat vérifié contre l'API réelle, sans rien envoyer :
#
# - `POST /v3/transactionalSMS/send` avec un corps vide répond 400 « Sender name is missing » :
#   l'endpoint existe et accepte la clé `xkeysib-` des emails. Corps : `sender`, `recipient`,
#   `content`, `type` ;
# - `GET /v3/account` rend `plan: [{type, credits, creditsType, startDate, endDate}]`. Le
#   nombre rendu est le RESTANT (19 995 puis 19 994 après un envoi), pas le quota. Les crédits
#   SMS y figurent comme une entrée de type « sms » quand le compte en a acheté ; leur absence
#   veut dire zéro.

URL_BREVO_SMS = "https://api.brevo.com/v3/transactionalSMS/send"
URL_BREVO_COMPTE = "https://api.brevo.com/v3/account"


def expediteur_sms(nom):
    """Nom d'expéditeur accepté par Brevo : 11 caractères alphanumériques au plus.

    « Réserve Résilience - Casques Jaunes » ne passe pas tel quel. On retire accents, espaces
    et ponctuation plutôt que de laisser l'API refuser l'envoi au moment où l'on en a besoin."""
    import re
    import unicodedata

    sans_accent = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode()
    propre = re.sub(r"[^A-Za-z0-9]", "", sans_accent)
    return propre[:11] or "Alerte"


def numero_international(numero):
    """Numéro tel que Brevo l'attend : E.164 **sans** le « + ».

    La conversion elle-même vit dans `core/telephone.py`, avec la table des indicatifs
    d'outre-mer : chaque fournisseur a sa manie de présentation, aucun n'a besoin de sa
    propre table."""
    from .telephone import pour_fournisseur

    return pour_fournisseur(numero, avec_plus=False)


def envoyer_sms_brevo(cle_api, expediteur, numero, message):
    """Envoie un SMS transactionnel et renvoie sa référence. Lève `EchecBrevo` sinon."""
    destinataire = numero_international(numero)
    if destinataire is None:
        raise EchecBrevo(f"Numéro de téléphone inexploitable : « {numero} ».")
    try:
        reponse = requests.post(
            URL_BREVO_SMS,
            headers={"api-key": cle_api, "content-type": "application/json",
                     "accept": "application/json"},
            data=json.dumps({
                "sender": expediteur_sms(expediteur), "recipient": destinataire,
                "content": message, "type": "transactional",
            }),
            timeout=DELAI_MAX_S,
        )
    except requests.RequestException as erreur:
        raise EchecBrevo(f"Brevo injoignable : {erreur}") from erreur
    if not 200 <= reponse.status_code < 300:
        raise EchecBrevo(f"Brevo a refusé le SMS ({reponse.status_code}) : {reponse.text[:300]}")
    try:
        corps = reponse.json()
    except ValueError:
        corps = {}
    return str(corps.get("messageId") or corps.get("reference") or "")


def lire_credits_brevo(cle_api):
    """Les crédits RESTANTS du compte : `{"email": n|None, "sms": n, "fin_periode": date|None}`.

    `email` vaut None quand le compte n'a pas de plafond lisible (certaines formules) : on ne
    transforme pas « inconnu » en zéro, ce qui déclencherait une alerte pour rien. `sms` vaut
    zéro en l'absence d'entrée, parce que là l'absence veut bien dire « aucun crédit »."""
    try:
        reponse = requests.get(
            URL_BREVO_COMPTE, headers={"api-key": cle_api, "accept": "application/json"},
            timeout=DELAI_MAX_S)
    except requests.RequestException as erreur:
        raise EchecBrevo(f"Brevo injoignable : {erreur}") from erreur
    if reponse.status_code != 200:
        raise EchecBrevo(f"Brevo a refusé la lecture du compte ({reponse.status_code}) : "
                         f"{reponse.text[:300]}")
    try:
        plans = reponse.json().get("plan") or []
    except ValueError as erreur:
        raise EchecBrevo("Réponse illisible de Brevo.") from erreur

    email, sms, fin = None, 0, None
    for plan in plans:
        credits = plan.get("credits")
        if (plan.get("type") or "").lower() == "sms":
            sms = int(credits or 0)
        elif credits is not None and plan.get("creditsType") == "sendLimit":
            email = int(credits) if email is None else email + int(credits)
            fin = plan.get("endDate") or fin
    return {"email": email, "sms": sms, "fin_periode": fin}
