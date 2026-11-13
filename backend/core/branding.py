"""Résolution de marque blanche -- voir mémoire de conception "assista-crise-marque-blanche"
(décision du 2026-09-23 : base partagée, branding par domaine d'origine / institution qui
traite, jamais de déploiement séparé). Première implémentation réelle, générique (pas
spécifique à un seul partenaire) : Réserve Résilience / Casques Jaunes est la première
institution à utiliser ce mécanisme via InstitutionWebDomaine (voir core/models.py), mais
n'importe quelle institution peut en recevoir un.

Deux usages distincts :
- `resolve_institution_branding(request)` : résout l'institution depuis le Host HTTP de la
  requête (voir InstitutionWebDomaine) -- pour la page publique (inscription) et l'API
  `/api/branding/`.
- `get_mail_branding(institution)`/`send_branded_mail(...)` : pour le CONTENU des emails,
  prennent directement une Institution déjà connue par le code appelant (ex: l'institution d'un
  dossier/d'une crise) -- pas nécessairement celle du Host de la requête courante (un email de
  suivi peut partir d'un contexte différent de celui où la page a été chargée, voir la mémoire
  de conception : "le partenaire doit pouvoir traiter des demandes déposées via
  assista-crise.fr")."""
from dataclasses import dataclass
from typing import Optional

DEFAULT_NOM_AFFICHAGE = "Assista-Crise"
DEFAULT_SIGNATURE = "L'équipe Assista-Crise"


@dataclass
class Branding:
    nom_affichage: str
    logo_url: Optional[str]
    couleur_primaire: str
    couleur_secondaire: str
    police_titre: str
    police_texte: str
    reserve_active: bool
    institution_id: Optional[str] = None


DEFAULT_BRANDING = Branding(
    nom_affichage=DEFAULT_NOM_AFFICHAGE,
    logo_url=None,
    couleur_primaire="#2563eb",
    couleur_secondaire="#1d4ed8",
    police_titre="",
    police_texte="",
    reserve_active=False,
)


def resolve_institution_branding(request):
    """Institution dont le branding s'applique à CETTE requête, résolue depuis le Host HTTP
    (voir InstitutionWebDomaine) -- None si aucune correspondance (site généraliste
    assista-crise.fr), auquel cas tout le reste du code doit retomber sur les valeurs
    Assista-Crise par défaut. Volontairement basé sur request.get_host() côté serveur (le Host
    transmis par nginx, voir proxy/nginx.conf `proxy_set_header Host $host`) -- jamais un
    paramètre fourni par le client, qui serait trivialement falsifiable."""
    from .models import InstitutionWebDomaine

    host = request.get_host().split(":")[0].lower()
    domaine = (
        InstitutionWebDomaine.objects.select_related("institution")
        .filter(hostname=host, institution__actif=True)
        .first()
    )
    return domaine.institution if domaine else None


def branding_satellite() -> Optional[Branding]:
    """La charte de l'institution propriétaire d'un SATELLITE, figée à l'enrôlement.

    Demande de Sylvain du 13/11/2026. Un satellite déployé par une association doit porter SA
    charte : on y arrive par l'IP locale (`http://192.168.1.50`), donc `InstitutionWebDomaine`
    ne correspond à rien et tout retombait sur « Assista-Crise ». Sur un dispositif déployé au
    nom de l'association, en crise, c'est précisément la cohérence visuelle qui fait
    reconnaître l'outil comme le sien.

    **Figée à l'enrôlement, et assumée comme telle** : les valeurs sont écrites dans le `.env`
    du satellite par `installer.sh`, à partir de ce que le central a renvoyé. Un changement de
    logo côté central n'arrive donc ici qu'à la prochaine mise à jour (`git pull` +
    `./installer.sh demarrer`). C'est le choix de Sylvain : pas de rafraîchissement continu
    tant que le besoin n'est pas là.

    **Mono-institution, et c'est structurel** : un satellite appartient à une institution et à
    une seule (voir `Satellite.institution`). Un satellite mutualisé entre deux associations
    n'est pas prévu, et cette fonction le fige.

    Les valeurs viennent du SERVEUR (son environnement), jamais du client : même garantie que
    `resolve_institution_branding`, dont le docstring explique pourquoi un paramètre fourni par
    le navigateur serait trivialement falsifiable.
    """
    from django.conf import settings

    if not settings.INSTANCE_SATELLITE_LOCALE:
        return None
    nom = (settings.SATELLITE_BRANDING_NOM or "").strip()
    if not nom:
        # Satellite enrôlé avant cette fonctionnalité, ou institution sans charte : on ne
        # fabrique pas une identité à partir de rien, on retombe sur Assista-Crise.
        return None
    return Branding(
        nom_affichage=nom,
        logo_url=(settings.SATELLITE_BRANDING_LOGO or "").strip() or None,
        couleur_primaire=(settings.SATELLITE_BRANDING_COULEUR_PRIMAIRE
                          or DEFAULT_BRANDING.couleur_primaire),
        couleur_secondaire=(settings.SATELLITE_BRANDING_COULEUR_SECONDAIRE
                            or DEFAULT_BRANDING.couleur_secondaire),
        police_titre=settings.SATELLITE_BRANDING_POLICE_TITRE or "",
        police_texte=settings.SATELLITE_BRANDING_POLICE_TEXTE or "",
        reserve_active=settings.SATELLITE_BRANDING_RESERVE_ACTIVE,
    )


def branding_for_institution(institution) -> Branding:
    """Construit l'objet Branding d'affichage pour une institution (ou les valeurs par défaut
    si None/pas de branding configuré) -- utilisé par la vue /api/branding/."""
    if institution is None:
        # Sur un satellite, « aucun domaine ne correspond » ne veut pas dire « site
        # généraliste » : cela veut dire qu'on y accède par son IP locale. La charte de son
        # institution prend donc le pas sur le défaut Assista-Crise.
        return branding_satellite() or DEFAULT_BRANDING
    return Branding(
        nom_affichage=institution.nom_affichage or institution.nom,
        logo_url=institution.logo.url if institution.logo else None,
        couleur_primaire=institution.couleur_primaire or DEFAULT_BRANDING.couleur_primaire,
        couleur_secondaire=institution.couleur_secondaire or DEFAULT_BRANDING.couleur_secondaire,
        police_titre=institution.police_titre,
        police_texte=institution.police_texte,
        reserve_active=institution.reserve_active,
        institution_id=str(institution.id),
    )


def get_mail_branding(institution):
    """{nom_expediteur, signature, reply_to} pour LE CONTENU d'un email -- défauts
    Assista-Crise si institution est None ou n'a pas de branding configuré (nom_affichage
    vide)."""
    if institution is None or not institution.nom_affichage:
        return {
            "nom_expediteur": DEFAULT_NOM_AFFICHAGE,
            "signature": DEFAULT_SIGNATURE,
            "reply_to": None,
        }
    return {
        "nom_expediteur": institution.nom_affichage,
        "signature": f"L'équipe {institution.nom_affichage}",
        "reply_to": institution.email_reply_to or None,
    }


def send_branded_mail(request, institution, subject, message, recipient_list, **kwargs):
    """Variante de send_mail_logged (core/audit.py) qui personnalise le sujet/la signature/le
    Reply-To selon l'institution fournie -- `message` doit se terminer par un marqueur
    "{signature}" que cette fonction remplace (voir les appelants) plutôt que de supposer où la
    signature se trouve dans le texte.

    **Depuis le 11/11/2026, l'envoi passe par l'API de l'institution quand elle en a une**
    (`ConfigurationEnvoiInstitution`, Brevo) : le message part alors de SON adresse, et
    Assista-Crise n'apparaît nulle part. C'est la levée de la limite de la v1, qui disait ici
    même « compte SMTP unique Assista-Crise, `reply_to` est le seul levier de personnalisation
    de l'adresse pour l'instant ».

    Sans configuration, ou si l'API échoue, on retombe sur le SMTP Assista-Crise
    (`from_email=None`) **en gardant le texte de l'institution** — voir
    core/envoi_institution.py pour ce qui est assumé dans ce repli. L'envoi reste journalisé en
    main courante dans les deux cas : `send_mail_logged` pour le SMTP, un `audit_log` explicite
    pour l'API, qui ne passe pas par Django."""
    from .audit import audit_log, send_mail_logged
    from .brouillons_envoi import capturer, doit_etre_relu
    from .envoi_institution import envoyer_email_pour_institution

    branding = get_mail_branding(institution)
    message_final = message.replace("{signature}", f"Cordialement,\n{branding['signature']}")
    reply_to = [branding["reply_to"]] if branding["reply_to"] else None

    # RELECTURE AVANT ENVOI : capturé en brouillon au lieu de partir, quand l'institution l'a
    # activée et que le message va vers un TIERS (voir core/brouillons_envoi.py). Placé ici et
    # non dans les 25 endpoints concernés : aucun n'a eu à changer de contrat.
    if doit_etre_relu(request, institution, list(recipient_list)):
        brouillon = capturer(request, institution, subject, message_final,
                             list(recipient_list), reply_to=branding["reply_to"])
        audit_log(
            request=request, action_code="ENVOI_EMAIL", objet_type="BrouillonEnvoi",
            objet_id=brouillon.id,
            commentaire=f'"{subject}" retenu pour relecture avant envoi à '
                        f'{", ".join(recipient_list)}',
            succes=True,
        )
        # 1 : même convention de retour que django.core.mail.send_mail. L'appelant a fait son
        # travail, et le message partira — après relecture, ou au bout du délai.
        return 1

    envoye, detail = envoyer_email_pour_institution(
        request, institution, subject, message_final, list(recipient_list),
        reply_to=branding["reply_to"],
    )
    if envoye:
        # Journalisé ici parce que cet envoi ne traverse pas send_mail_logged : sans cela,
        # passer une institution à l'API ferait DISPARAÎTRE ses emails de la main courante —
        # exactement le trou que send_mail_logged avait été écrit pour fermer.
        audit_log(
            request=request, action_code="ENVOI_EMAIL", objet_type="Email",
            commentaire=f'Envoi "{subject}" à {", ".join(recipient_list)} '
                        f'via l\'API de « {institution.nom} »',
            succes=True,
        )
        # 1 : même convention de retour que django.core.mail.send_mail (nombre de messages
        # pris en charge), pour que les appelants n'aient pas à distinguer les deux chemins.
        return 1

    if detail and detail != "non configuré":
        # Le repli est tracé À PART du succès de l'envoi SMTP qui suit : une clé révoquée doit
        # se voir dans la main courante même si le message est finalement parti.
        audit_log(
            request=request, action_code="ENVOI_EMAIL", objet_type="Email",
            commentaire=f'Repli SMTP pour « {institution.nom} » après échec de son API : {detail}',
            succes=False,
        )

    return send_mail_logged(
        request, subject=subject, message=message_final, from_email=None,
        recipient_list=recipient_list, reply_to=reply_to, **kwargs,
    )


def send_branded_mail_env_aware(request, institution, subject, message, recipient_list, **kwargs):
    """Combine send_branded_mail (signature/Reply-To personnalisés) et le redirect DEMO de
    send_mail_env_aware (core/permissions.py) -- nécessaire parce que la plupart des emails
    "opérationnels" qui ont un contexte d'institution (clôture de dossier, affectation à une
    équipe...) utilisaient déjà send_mail_env_aware, pas send_mail_logged directement ; les
    faire passer par send_branded_mail seul aurait silencieusement perdu la protection
    anti-spam de la zone DEMO (voir l'incident évité par send_mail_env_aware à l'origine). Même
    périmètre qu'elle : jamais pour un email de cycle de vie de compte."""
    from .models import Environment
    from .permissions import get_active_environment

    if get_active_environment(request) == Environment.DEMO and getattr(request.user, "is_authenticated", False):
        recipient_list = [request.user.email]
        subject = f"[DEMO] {subject}"
    return send_branded_mail(request, institution, subject, message, recipient_list, **kwargs)


def send_modele_mail(request, institution, cle, valeurs, recipient_list, **kwargs):
    """Envoie un message du catalogue, avec le texte de l'institution s'il existe.

    Enveloppe de `send_branded_mail` qui ajoute la seule chose que celle-ci ne fait pas :
    résoudre le modèle. Le reste du chemin est inchangé — relecture avant envoi, API de
    l'institution, repli SMTP, journalisation.

    `valeurs` est un dictionnaire `{PLACEHOLDER: valeur}`. `[SIGNATURE]` est fourni d'office,
    depuis le branding : les appelants n'ont pas à le connaître, et c'est le seul placeholder
    qui ne dépend pas de l'appel.

    **Rendu avec `pour_envoi=True`**, donc les liens sont résolus ici. C'est voulu et ce n'est
    pas une fuite : la capture du brouillon qui a lieu ensuite les masque par valeur, puisque
    `build_magic_link` les a déclarés (voir core/brouillons_envoi.py). Rendre sans les liens
    produirait un mail qui dit « cliquez sur [LIEN_ACTIVATION] ».

    Retombe sur rien si la clé est inconnue (renvoie None) : l'appelant garde alors son texte en
    dur. C'est ce qui permet de migrer les 48 points d'envoi par lots plutôt qu'en un commit où
    la casse serait silencieuse.
    """
    from .brouillons_envoi import resoudre_modele
    from .modeles_messages import rendre

    sujet_modele, corps_modele, _ = resoudre_modele(institution, cle)
    if sujet_modele is None and corps_modele is None:
        return None

    branding = get_mail_branding(institution)
    toutes = {
        "SIGNATURE": f"Cordialement,\n{branding['signature']}",
        "INSTITUTION": branding["nom_expediteur"],
        **valeurs,
    }
    sujet = rendre(sujet_modele, toutes, pour_envoi=True)
    corps = rendre(corps_modele, toutes, pour_envoi=True)

    return send_branded_mail(request, institution, subject=sujet, message=corps,
                             recipient_list=recipient_list, **kwargs)
