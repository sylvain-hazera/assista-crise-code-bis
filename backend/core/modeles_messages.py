"""Modèles de messages : registre des textes envoyés, placeholders, et rendu.

Trois besoins d'un seul mécanisme (demande du 11/11/2026) :

1. **Une institution réécrit les textes envoyés en son nom** — 37 messages atteignent son
   public (bénévoles, citoyens, demandeurs). Les 14 envois internes et techniques (alertes
   administrateur, supervision) n'en font pas partie : ils ne vont pas à ses bénévoles, et les
   laisser réécrire permettrait de casser le texte d'une alerte que seuls les administrateurs de
   la plateforme lisent.
2. **Une fenêtre de relecture avant envoi**, pour les ~25 envois où l'on écrit à quelqu'un
   d'autre que soi (voir `relisible`).
3. **Des placeholders** plutôt que des valeurs, pour qu'un même texte serve plusieurs
   destinataires.

LA RÈGLE QUI PORTE TOUT LE RESTE : **un placeholder de lien n'est jamais résolu ailleurs qu'à
l'instant de l'envoi.** Onze points d'envoi utilisent `build_magic_link`, et un lien magique est
un *porteur d'identité* — qui l'a peut agir comme la personne. Le cas qui le prouve :
`UserViewSet.send_password_reset`, où un administrateur déclenche une réinitialisation POUR
QUELQU'UN D'AUTRE. Afficher ce lien dans une fenêtre de relecture donnerait à l'administrateur
de quoi prendre la main sur le compte du bénévole. Les placeholders `[LIEN…]` restent donc
littéralement dans le brouillon et dans l'aperçu ; `rendre()` ne les remplace que quand on
l'appelle avec `pour_envoi=True`, ce que seul le chemin d'envoi fait.

Forme des placeholders : `[MAJUSCULES]`. Pas `{...}`, qui entre en conflit avec le formatage
Python, et surtout pas le `{signature}` existant — ce marqueur interne de `send_branded_mail`
est remplacé AVANT que cette couche ne voie le texte, et les 48 appels en place n'ont donc pas
à changer.

**Crochets littéraux : on les double.** `[[PCS]]` rend `[PCS]`. Le besoin est réel — le sujet de
l'alerte PCS commence par `[PCS]`, préfixe sur lequel des filtres de boîte mail peuvent porter.
Sans échappement, `rendre()` le laissait intact seulement parce qu'aucune valeur n'était fournie
pour « PCS » : le jour où un placeholder de ce nom existerait, le sujet changerait en silence.
Doubler rend l'intention explicite au lieu de la laisser dépendre d'une absence.
"""
import re
from dataclasses import dataclass, field

#: Un placeholder : `[PRENOM]`, `[LIEN_ACTIVATION]`…
MOTIF_PLACEHOLDER = re.compile(r"\[([A-Z][A-Z0-9_]*)\]")

#: Crochets littéraux, doublés : `[[PCS]]` rend `[PCS]`. Repérés AVANT la substitution pour
#: qu'un texte échappé ne puisse jamais être pris pour un placeholder.
MOTIF_ECHAPPE = re.compile(r"\[\[([^\[\]]*)\]\]")

#: Préfixe des placeholders qui portent un secret. Tout ce qui commence par là est résolu au
#: dernier moment et jamais stocké résolu. Le préfixe plutôt qu'une liste nommée : ajouter un
#: nouveau lien ne doit pas demander de penser à l'inscrire quelque part pour qu'il soit
#: protégé — l'oubli irait dans le mauvais sens.
PREFIXE_SECRET = "LIEN"

#: Segment SMS en GSM-7. Au-delà, le message est découpé et facturé par segment, et chaque
#: segment d'un message concaténé ne porte plus que 153 caractères utiles (en-tête de
#: concaténation). Affiché à la saisie : un texte de 161 caractères coûte deux fois le prix d'un
#: texte de 160, ce qui ne se devine pas.
SMS_SEGMENT = 160
SMS_SEGMENT_CONCATENE = 153


class CanalMessage:
    EMAIL = "EMAIL"
    SMS = "SMS"


@dataclass(frozen=True)
class ModeleDefaut:
    """Le texte d'origine d'un message, et ce qu'on peut en faire.

    `relisible` dit si une fenêtre de relecture a du sens : vrai quand le message part vers
    quelqu'un d'AUTRE que celui qui agit. Faux pour un accusé de réception que la personne
    s'envoie à elle-même en s'inscrivant — y ouvrir un éditeur montrerait à quelqu'un le mail
    qu'il est en train de recevoir, avec son propre lien de connexion dedans.

    `personnalisable` dit si une institution peut le réécrire : faux pour les alertes internes
    et techniques.
    """

    cle: str
    libelle: str
    sujet: str
    corps: str
    #: Placeholders que l'appelant doit fournir. Vérifié par un test : un modèle qui en emploie
    #: un qui n'est pas déclaré ici partirait avec `[PRENOM]` en clair dans le mail.
    placeholders: tuple = ()
    relisible: bool = False
    personnalisable: bool = True
    canal: str = CanalMessage.EMAIL
    #: À quoi sert ce message, pour l'écran de personnalisation. Une institution qui réécrit un
    #: texte doit savoir quand il part et à qui.
    quand: str = ""


def placeholders_du_texte(texte):
    """Les placeholders employés dans un texte, dans l'ordre d'apparition, sans doublon.

    Ignore les crochets doublés : `[[PCS]]` est du texte, pas un placeholder — sinon l'écran de
    personnalisation réclamerait une valeur pour « PCS »."""
    sans_echappes = MOTIF_ECHAPPE.sub("", texte or "")
    vus = []
    for nom in MOTIF_PLACEHOLDER.findall(sans_echappes):
        if nom not in vus:
            vus.append(nom)
    return vus


def est_secret(nom_placeholder):
    """Vrai pour `[LIEN]`, `[LIEN_ACTIVATION]`, `[LIEN_SUIVI]`… — tout ce qui porte un secret."""
    return nom_placeholder.startswith(PREFIXE_SECRET)


def rendre(texte, valeurs, pour_envoi=False):
    """Remplace les placeholders par leurs valeurs.

    **`pour_envoi=False` (le défaut) laisse les placeholders secrets intacts.** C'est le mode
    d'un brouillon, d'un aperçu, de tout ce qui est stocké ou affiché. Le défaut est le mode sûr
    délibérément : un appelant qui oublie l'argument ne fait pas fuiter un lien.

    Un placeholder dont la valeur n'est pas fournie est **laissé tel quel** et non remplacé par
    du vide : un mail qui dit « Bonjour [PRENOM] » se remarque et se corrige, un mail qui dit
    « Bonjour  » passe inaperçu.
    """
    def remplacer(correspondance):
        nom = correspondance.group(1)
        if est_secret(nom) and not pour_envoi:
            return correspondance.group(0)
        valeur = valeurs.get(nom)
        if valeur is None:
            return correspondance.group(0)
        return str(valeur)

    # Les crochets doublés sont mis de côté avant la substitution et remis après : les traiter
    # en même temps laisserait `[[LIEN]]` passer pour un placeholder secret.
    mis_de_cote = []

    def reserver(correspondance):
        mis_de_cote.append(correspondance.group(1))
        return f"\x00{len(mis_de_cote) - 1}\x00"

    travail = MOTIF_ECHAPPE.sub(reserver, texte or "")
    travail = MOTIF_PLACEHOLDER.sub(remplacer, travail)
    for indice, contenu in enumerate(mis_de_cote):
        travail = travail.replace(f"\x00{indice}\x00", f"[{contenu}]")
    return travail


def segments_sms(texte):
    """Nombre de segments facturés pour ce texte, et caractères restants dans le dernier.

    Compté ici et affiché à la saisie parce que la facturation d'un SMS est au segment : un
    texte de 161 caractères coûte deux fois celui de 160, et personne ne le devine. Le calcul
    suppose du GSM-7 ; un caractère hors de cet alphabet (emoji, certains guillemets) fait
    basculer tout le message en UCS-2 et divise la capacité par deux — signalé plutôt que
    silencieusement faux."""
    longueur = len(texte or "")
    if longueur == 0:
        return {"segments": 0, "restants": SMS_SEGMENT, "longueur": 0}
    if longueur <= SMS_SEGMENT:
        return {"segments": 1, "restants": SMS_SEGMENT - longueur, "longueur": longueur}
    segments = -(-longueur // SMS_SEGMENT_CONCATENE)  # division entière par excès
    restants = segments * SMS_SEGMENT_CONCATENE - longueur
    return {"segments": segments, "restants": restants, "longueur": longueur}


# ─────────────────────────────────────────────────────────────────────────────────────────────
# CATALOGUE
#
# Les textes par défaut sont ceux déjà envoyés aujourd'hui, repris tels quels : le but est que
# RIEN ne change pour une institution qui ne personnalise pas. Chaque entrée dit quand le
# message part et à qui, parce qu'une institution qui réécrit un texte doit le savoir.
#
# `relisible=True` = le message part vers quelqu'un d'AUTRE que celui qui agit : une fenêtre de
# relecture y a du sens. Les accusés qu'on s'envoie à soi-même en s'inscrivant sont à False.
# ─────────────────────────────────────────────────────────────────────────────────────────────

CATALOGUE = {m.cle: m for m in [

    # ── Cycle de vie des comptes ────────────────────────────────────────────────────────────
    ModeleDefaut(
        cle="COMPTE_ACTIVATION_INSTITUTIONNEL",
        libelle="Activation d'un compte institutionnel",
        quand="À l'inscription d'un compte autorité locale ou secours. Premier message que "
              "reçoit la personne.",
        sujet="Votre accès institutionnel [INSTITUTION]",
        corps=(
            "Bonjour,\n\n"
            "Votre compte institutionnel sur [INSTITUTION] a été créé.\n\n"
            "Il est encore inactif : cliquez sur le lien ci-dessous pour confirmer que vous "
            "êtes bien le propriétaire de cette adresse email et activer votre compte.\n\n"
            "- Activation du compte : [LIEN_ACTIVATION]\n\n"
            "Vous pourrez ensuite vous reconnecter à tout moment via : [LIEN_CONNEXION]\n\n"
            "Ces liens sont valables pendant 7 jours.\n\n"
            "Une fois rattaché à votre institution, vous recevrez un second email avec les "
            "instructions pour accéder à la messagerie de votre équipe.\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("INSTITUTION", "LIEN_ACTIVATION", "LIEN_CONNEXION", "SIGNATURE"),
        # L'inscrit est le destinataire : lui ouvrir un éditeur lui montrerait son propre lien.
        relisible=False,
    ),
    ModeleDefaut(
        cle="COMPTE_EN_ATTENTE_VALIDATION",
        libelle="Compte créé, en attente de validation",
        quand="À l'inscription d'un compte qui demande une validation humaine.",
        sujet="Compte créé - En attente de validation",
        corps=(
            "Bonjour [PRENOM] [NOM],\n\n"
            "Votre compte ([TYPE_COMPTE]) sur [INSTITUTION] a bien été créé.\n"
            "Cependant, il est en attente de validation par un administrateur.\n"
            "Vous recevrez un email dès que votre compte sera validé.\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "NOM", "TYPE_COMPTE", "INSTITUTION", "SIGNATURE"),
        relisible=False,
    ),
    ModeleDefaut(
        cle="COMPTE_VALIDE",
        libelle="Compte validé",
        quand="Quand un administrateur ou une mairie valide un compte en attente.",
        # Texte repris MOT POUR MOT de ce qui partait avant la migration vers les modèles :
        # une institution qui ne personnalise pas ne doit voir AUCUN changement.
        sujet="Votre compte a été validé !",
        corps=(
            "Bonjour [PRENOM] [NOM],\n\n"
            "Bonne nouvelle ! Votre compte ([TYPE_COMPTE]) a été validé.\n"
            "Vous pouvez maintenant vous connecter et accéder à toutes les fonctionnalités.\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "NOM", "TYPE_COMPTE", "SIGNATURE"),
        # Un tiers valide : la fenêtre a du sens, et le lien reste masqué pour lui.
        relisible=True,
    ),
    ModeleDefaut(
        cle="COMPTE_REFUSE",
        libelle="Demande de compte refusée",
        quand="Quand un administrateur ou une mairie refuse une demande de compte. Le motif "
              "saisi au refus est inséré.",
        sujet="Votre demande de compte a été refusée",
        corps=(
            "Bonjour [PRENOM] [NOM],\n\n"
            "Nous sommes désolés de vous informer que votre demande de compte ([TYPE_COMPTE]) "
            "n'a pas été acceptée.\n\n"
            "Raison : [MOTIF]\n\n"
            "Pour plus d'informations, vous pouvez nous contacter.\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "NOM", "TYPE_COMPTE", "MOTIF", "SIGNATURE"),
        relisible=True,
    ),
    ModeleDefaut(
        cle="MOT_DE_PASSE_OUBLIE",
        libelle="Réinitialisation de mot de passe (demandée par la personne)",
        quand="Quand quelqu'un utilise « mot de passe oublié ».",
        # Texte repris MOT POUR MOT de PasswordResetRequestView.
        sujet="Réinitialisation de votre mot de passe [INSTITUTION]",
        corps=(
            "Bonjour [PRENOM] [NOM],\n\n"
            "Vous avez demandé la réinitialisation du mot de passe de votre compte "
            "[INSTITUTION].\n\n"
            "Pour choisir un nouveau mot de passe, cliquez sur le lien suivant :\n"
            "[LIEN_REINITIALISATION]\n\n"
            "Ce lien est valable 7 jours et ne peut être utilisé qu'une seule fois. Si vous "
            "n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet email : votre "
            "mot de passe actuel reste valable.\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "NOM", "INSTITUTION", "LIEN_REINITIALISATION", "SIGNATURE"),
        relisible=False,
    ),
    ModeleDefaut(
        cle="MOT_DE_PASSE_ENVOYE_PAR_UN_TIERS",
        libelle="Réinitialisation de mot de passe (envoyée par un administrateur)",
        quand="Quand un administrateur déclenche une réinitialisation POUR quelqu'un d'autre.",
        sujet="Réinitialisation de votre mot de passe [INSTITUTION]",
        corps=(
            "Bonjour [PRENOM],\n\n"
            "Un administrateur de [INSTITUTION] a déclenché la réinitialisation de votre mot "
            "de passe.\n\n"
            "Cliquez sur ce lien pour en choisir un nouveau : [LIEN_REINITIALISATION]\n\n"
            "Ce lien est valable 7 jours.\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "INSTITUTION", "LIEN_REINITIALISATION", "SIGNATURE"),
        # LE cas qui justifie le masquage des liens : celui qui relit n'est pas le titulaire du
        # compte, et le lien lui donnerait la main dessus.
        relisible=True,
    ),

    ModeleDefaut(
        cle="BENEVOLE_ACTIVATION",
        libelle="Activation du compte d'un bénévole d'association",
        quand="À l'import des membres d'une association. Premier message que reçoit le "
              "bénévole : son lien d'activation et ce qu'on attend de lui ensuite.",
        # Distinct de COMPTE_ACTIVATION_INSTITUTIONNEL, et pas par souci de nuance : ce texte
        # parlait de « compte institutionnel » et d'un « rattachement à votre institution »,
        # ce qui ne veut rien dire pour un bénévole, et il n'emmenait nulle part. Celui-ci
        # emmène là où il reste quelque chose à faire — relire sa fiche et déposer ses pièces.
        sujet="Votre accès bénévole [INSTITUTION]",
        corps=(
            "Bonjour [PRENOM],\n\n"
            "Un compte vous a été créé sur [INSTITUTION] à partir de la liste des membres de "
            "l'association.\n\n"
            "Il est encore inactif : cliquez sur le lien ci-dessous pour confirmer votre "
            "adresse et l'activer.\n\n"
            "- Activation : [LIEN_ACTIVATION]\n\n"
            "Vous arriverez ensuite sur votre fiche de bénévole. Prenez un instant pour "
            "relire ce qu'elle contient, la compléter, et y déposer vos justificatifs "
            "(permis, diplômes, attestations de formation). Vous pourrez aussi y choisir un "
            "mot de passe — c'est facultatif : le lien reçu par email suffit pour vous "
            "connecter.\n\n"
            "Vous reconnecter à tout moment : [LIEN_CONNEXION]\n\n"
            "Ces liens sont valables 7 jours.\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "INSTITUTION", "LIEN_ACTIVATION", "LIEN_CONNEXION",
                      "SIGNATURE"),
        # Le bénévole est le destinataire : lui ouvrir la fenêtre de relecture lui montrerait
        # son propre lien d'activation.
        relisible=False,
    ),

    # ── Équipes et missions ─────────────────────────────────────────────────────────────────
    ModeleDefaut(
        cle="EQUIPE_NOUVEAU_MEMBRE",
        libelle="Ajout à une équipe",
        quand="Quand quelqu'un est ajouté à une équipe.",
        sujet="Vous rejoignez l'équipe [EQUIPE]",
        corps=(
            "Bonjour [PRENOM],\n\n"
            "Vous avez été ajouté à l'équipe « [EQUIPE] » de [INSTITUTION].\n\n"
            "Accès à l'équipe : [LIEN_EQUIPE]\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "EQUIPE", "INSTITUTION", "LIEN_EQUIPE", "SIGNATURE"),
        relisible=True,
    ),
    ModeleDefaut(
        cle="EQUIPE_INVITATION",
        libelle="Invitation à rejoindre une équipe",
        quand="Quand le bureau invite quelqu'un qui n'a pas encore de compte.",
        sujet="Invitation à rejoindre [INSTITUTION]",
        corps=(
            "Bonjour [PRENOM],\n\n"
            "Vous êtes invité à rejoindre l'équipe « [EQUIPE] » de [INSTITUTION].\n\n"
            "Pour activer votre accès : [LIEN_ACTIVATION]\n\n"
            "Ce lien est valable 7 jours.\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "EQUIPE", "INSTITUTION", "LIEN_ACTIVATION", "SIGNATURE"),
        relisible=True,
    ),

    ModeleDefaut(
        cle="CAMPAGNE_DISPONIBILITE",
        libelle="Appel à disponibilités sur une période",
        quand="Quand une association sollicite ses bénévoles pour une période à venir "
              "(campagne de disponibilité). Part à tous les bénévoles retenus par les "
              "critères, en un seul texte relu une fois.",
        sujet="[INSTITUTION] — disponibilités du [PERIODE]",
        corps=(
            "Bonjour [PRENOM],\n\n"
            "[MOTIF]\n\n"
            "[TEXTE]\n\n"
            "Nous avons besoin de savoir sur quels créneaux vous seriez disponible "
            "du [PERIODE].\n\n"
            "Indiquez-les ici : [LIEN_DISPONIBILITES]\n\n"
            "[ROTATION]\n\n"
            "Répondre « aucune disponibilité » est une réponse utile : cela nous évite de "
            "vous relancer, et nous dit sur qui compter.\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "INSTITUTION", "MOTIF", "TEXTE", "PERIODE", "ROTATION",
                      "LIEN_DISPONIBILITES", "SIGNATURE"),
        # Relisible, et c'est tout l'intérêt : le texte part à des centaines de personnes et
        # c'est un tiers qui l'écrit. La fenêtre de relecture le montre UNE fois, générique,
        # pour tout le lot (voir core/brouillons_envoi.py).
        relisible=True,
    ),

    # ── Dossiers et demandes ────────────────────────────────────────────────────────────────
    ModeleDefaut(
        cle="DOSSIER_CLOTURE",
        libelle="Clôture d'un dossier",
        quand="Quand un dossier est clôturé, au demandeur.",
        sujet="Votre dossier [NUMERO_DOSSIER] est clôturé",
        corps=(
            "Bonjour [PRENOM],\n\n"
            "Votre dossier [NUMERO_DOSSIER] a été clôturé.\n\n"
            "Suivi du dossier : [LIEN_SUIVI]\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "NUMERO_DOSSIER", "LIEN_SUIVI", "SIGNATURE"),
        relisible=True,
    ),
    ModeleDefaut(
        cle="DEMANDE_ACCUSE_DEPOT",
        libelle="Accusé de dépôt d'une demande",
        quand="Quand un citoyen dépose une demande d'aide.",
        sujet="Votre demande a bien été reçue",
        corps=(
            "Bonjour [PRENOM] [NOM],\n\n"
            "Votre demande a bien été enregistrée par [INSTITUTION].\n\n"
            "Vous pouvez en suivre l'avancement ici : [LIEN_SUIVI]\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "NOM", "INSTITUTION", "LIEN_SUIVI", "SIGNATURE"),
        relisible=False,
    ),
    ModeleDefaut(
        cle="OFFRE_ACCUSE_DEPOT",
        libelle="Accusé de dépôt d'une offre d'aide",
        quand="Quand quelqu'un propose son aide.",
        sujet="Votre proposition d'aide a bien été reçue",
        corps=(
            "Bonjour [PRENOM] [NOM],\n\n"
            "Merci : votre proposition d'aide a bien été enregistrée par [INSTITUTION].\n\n"
            "Vous pouvez la suivre ici : [LIEN_SUIVI]\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "NOM", "INSTITUTION", "LIEN_SUIVI", "SIGNATURE"),
        relisible=False,
    ),

    # ── Habitations ─────────────────────────────────────────────────────────────────────────
    ModeleDefaut(
        cle="RATTACHEMENT_HABITATION_ACCEPTE",
        libelle="Rattachement à une habitation accepté",
        quand="Quand la commune accepte un rattachement propriétaire/locataire.",
        sujet="Votre rattachement a été accepté",
        corps=(
            "Bonjour [PRENOM],\n\n"
            "Votre rattachement à « [ADRESSE] » a été accepté par [INSTITUTION].\n\n"
            "Suivi : [LIEN_SUIVI]\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "ADRESSE", "INSTITUTION", "LIEN_SUIVI", "SIGNATURE"),
        relisible=True,
    ),
    ModeleDefaut(
        cle="RATTACHEMENT_HABITATION_REFUSE",
        libelle="Rattachement à une habitation refusé",
        quand="Quand la commune refuse un rattachement. Le motif saisi est inséré.",
        sujet="Votre rattachement n'a pas été accepté",
        corps=(
            "Bonjour [PRENOM],\n\n"
            "Votre rattachement à « [ADRESSE] » n'a pas été accepté.\n\n"
            "Motif : [MOTIF]\n\n"
            "[SIGNATURE]"
        ),
        placeholders=("PRENOM", "ADRESSE", "MOTIF", "SIGNATURE"),
        relisible=True,
    ),

    # ── Alerte PCS (texte déjà saisi par l'utilisateur à chaque envoi) ──────────────────────
    ModeleDefaut(
        cle="ALERTE_PCS",
        libelle="Alerte d'activation du plan communal de sauvegarde",
        quand="Envoyée depuis la checklist PCS. Le texte est déjà modifiable à chaque envoi ; "
              "ce modèle en fournit le point de départ.",
        # `[[PCS]]` : crochets LITTÉRAUX, préfixe de sujet sur lequel des filtres de boîte mail
        # peuvent porter. Sans le doublement, ce serait lu comme un placeholder « PCS ».
        sujet="[[PCS]] Activation du plan communal de sauvegarde — [CRISE]",
        corps=(
            "[MESSAGE]\n\n"
            "---\n"
            "Pour accuser réception de cette alerte (et éviter un appel téléphonique de "
            "relance si ce n'est pas nécessaire) : [LIEN_ACCUSE_RECEPTION]\n"
        ),
        placeholders=("CRISE", "MESSAGE", "LIEN_ACCUSE_RECEPTION"),
        relisible=True,
    ),

    # ── SMS ─────────────────────────────────────────────────────────────────────────────────
    ModeleDefaut(
        cle="SMS_ALERTE_PCS",
        libelle="Alerte PCS par SMS",
        quand="Même alerte que ci-dessus, par SMS. Volontairement court : au-delà de "
              "160 caractères le message est facturé en plusieurs segments.",
        sujet="",
        corps="[INSTITUTION] : [MESSAGE] Accuse reception : [LIEN_ACCUSE_RECEPTION]",
        placeholders=("INSTITUTION", "MESSAGE", "LIEN_ACCUSE_RECEPTION"),
        relisible=True,
        canal=CanalMessage.SMS,
    ),

    # ── Interne / technique : NON personnalisable ──────────────────────────────────────────
    # Ces messages ne vont pas au public d'une institution : ils vont aux administrateurs de la
    # plateforme. Les laisser réécrire permettrait de casser le texte d'une alerte que seuls
    # ces administrateurs lisent — et qui sert à diagnostiquer une panne.
    ModeleDefaut(
        cle="INTERNE_ALERTE_ADMINISTRATEURS",
        libelle="Alerte aux administrateurs de la plateforme",
        quand="Pannes, erreurs applicatives, SOS mesh, passerelle muette.",
        sujet="[SUJET]",
        corps="[MESSAGE]",
        placeholders=("SUJET", "MESSAGE"),
        relisible=False,
        personnalisable=False,
    ),
]}


def modeles_personnalisables():
    """Ce qu'une institution peut réécrire, trié par libellé pour l'écran de personnalisation."""
    return sorted(
        (m for m in CATALOGUE.values() if m.personnalisable),
        key=lambda m: (m.canal, m.libelle),
    )


def modele(cle):
    """Le modèle par défaut, ou None. Jamais d'exception : un appelant qui passe une clé
    inconnue doit pouvoir retomber sur son texte en dur plutôt que de faire échouer l'action
    qu'il accompagne."""
    return CATALOGUE.get(cle)
