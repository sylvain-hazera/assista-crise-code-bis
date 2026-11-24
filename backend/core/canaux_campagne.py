"""Par quel canal une campagne part, ce que cela coûte, et ce qu'il reste pour payer.

Demande de Sylvain du 13/11/2026 : « compte tenu des coûts, on doit avoir la possibilité de
choisir entre brevo mail / brevo sms / mobimel / Matrix avec un rappel des coûts / solde
restant ».

**Le coût n'est pas une note de bas de page, c'est un critère de choix.** Écrire à quatre cents
bénévoles ne vaut pas la même chose par email (quelques centimes au total) et par SMS (plusieurs
dizaines d'euros), et la décision se prend au moment de composer la campagne — pas en découvrant
la facture. L'écran annonce donc, pour chaque canal : ce qu'il consomme, ce qu'il reste, et s'il
suffit pour cette campagne-ci.

**Matrix n'est plus un canal** depuis son arrêt (24/11/2026) : une campagne qui le cite encore
part par l'application (`CANAL_MATRIX` reste connu pour être relu, jamais proposé).

**On ne bloque pas un envoi faute de crédits**, on prévient. Une association qui sait son
compte à sec peut vouloir partir quand même sur les cent premières personnes, ou basculer sur
un autre canal. C'est sa décision, pas celle du logiciel — mais elle doit être prise en
connaissance de cause.

Les tarifs sont **indicatifs et déclarés par l'institution** : ils dépendent de son contrat, et
nous ne les connaissons pas. Zéro = non renseigné, et l'écran dit alors « coût inconnu » plutôt
que « gratuit ».
"""

CANAL_EMAIL = "BREVO_EMAIL"
CANAL_SMS = "BREVO_SMS"
CANAL_MOBIMEL = "MOBIMEL"
CANAL_MATRIX = "MATRIX"
CANAL_APPLICATION = "APPLICATION"


def sans_matrix(canaux):
    """Les canaux, Matrix remplacé par l'application (arrêt de Matrix, 24/11/2026), sans doublon."""
    return list(dict.fromkeys(CANAL_APPLICATION if c == CANAL_MATRIX else c for c in canaux))

#: Ce que chaque canal sait faire, dans l'ordre où on le propose : du plus large au plus cher.
CANAUX = [
    {
        "code": CANAL_APPLICATION,
        "libelle": "Application mobile",
        "detail": "Gratuit, et le seul canal qui dit ce que le message est devenu : reçu, vu, "
                  "lu, répondu. Ne touche que les personnes qui ont l'application — "
                  "complétez par un autre canal pour les autres. Application fermée, la "
                  "notification peut mettre jusqu'à un quart d'heure à sonner.",
        "unite": None,
    },
    {
        "code": CANAL_EMAIL,
        "libelle": "Email",
        "detail": "Part à tous ceux qui ont une adresse. Le canal le moins cher, et celui "
                  "qui porte un lien cliquable vers la grille de disponibilités.",
        "unite": "crédit email",
    },
    {
        "code": CANAL_SMS,
        "libelle": "SMS (Brevo)",
        "detail": "Lu presque à coup sûr, et sans connexion. Nettement plus cher : à garder "
                  "pour l'urgence ou pour relancer ceux qui n'ont pas répondu.",
        "unite": "crédit SMS",
    },
    {
        "code": CANAL_MOBIMEL,
        "libelle": "SMS (Mobimel)",
        "detail": "Second opérateur SMS, si votre contrat y est.",
        "unite": "SMS",
    },
]


def _joignables(campagne, cibles):
    """Combien de personnes chaque canal peut réellement atteindre.

    Un canal qui n'atteint personne est pire qu'un canal cher : on compte donc les
    destinataires AVANT de parler d'argent."""
    email = sum(1 for c in cibles if c.utilisateur.email)
    sms = sum(1 for c in cibles if c.utilisateur.phone_number)
    from .notifications_application import joignables_par_application

    # Un téléphone qui a parlé au serveur récemment : un fait, pas une estimation.
    application = len(joignables_par_application(c.utilisateur_id for c in cibles))
    return {"email": email, "sms": sms, "application": application}


def apercu_des_canaux(campagne, cibles):
    """Pour chaque canal : qui il atteint, ce qu'il coûte, ce qu'il reste, et si ça suffit.

    Rendu à l'écran de composition, avant l'envoi. `cibles` est la liste déjà figée des
    destinataires (voir `CibleCampagne`) : on chiffre ce qui partira vraiment, pas une
    estimation sur l'effectif total de l'association."""
    from .envoi_institution import configuration_envoi

    config = configuration_envoi(campagne.institution)
    portee = _joignables(campagne, cibles)

    restants = {
        CANAL_EMAIL: getattr(config, "brevo_credits_email", None) if config else None,
        CANAL_SMS: getattr(config, "brevo_credits_sms", None) if config else None,
        CANAL_MOBIMEL: None,   # Pas d'API de solde tant que l'adaptateur n'est pas écrit.
        CANAL_APPLICATION: None,
    }
    tarifs = {
        CANAL_EMAIL: getattr(config, "cout_unitaire_email", 0) if config else 0,
        CANAL_SMS: getattr(config, "cout_unitaire_sms", 0) if config else 0,
        CANAL_MOBIMEL: getattr(config, "cout_unitaire_sms_mobimel", 0) if config else 0,
        CANAL_APPLICATION: 0,
    }
    disponible = {
        CANAL_EMAIL: bool(config and config.email_configure),
        CANAL_SMS: bool(config and config.fournisseur_sms == "BREVO" and config.sms_configure),
        CANAL_MOBIMEL: bool(config and config.fournisseur_sms == "MOBIMEL"
                            and config.sms_configure),
        CANAL_APPLICATION: portee["application"] > 0,
    }

    apercu = []
    for canal in CANAUX:
        code = canal["code"]
        destinataires = {
            CANAL_EMAIL: portee["email"], CANAL_SMS: portee["sms"],
            CANAL_MOBIMEL: portee["sms"],
            CANAL_APPLICATION: portee["application"],
        }[code]
        restant = restants[code]
        tarif = tarifs[code] or 0
        apercu.append({
            **canal,
            "destinataires": destinataires,
            # Les personnes que CE canal laisse de côté : le chiffre qui manque le plus
            # souvent quand on choisit « le moins cher ».
            "non_joignables": len(cibles) - destinataires,
            "disponible": disponible[code],
            "credits_restants": restant,
            # Centimes, pour ne pas traîner des flottants sur de l'argent.
            "cout_unitaire_centimes": tarif,
            "cout_total_centimes": tarif * destinataires if tarif else None,
            # None = on ne sait pas (pas de solde connu) ; l'écran dit « inconnu », jamais
            # « suffisant ».
            "credits_suffisants": (None if restant is None
                                   else restant >= destinataires),
        })
    return apercu
