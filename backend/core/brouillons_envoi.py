"""Fenêtre de relecture avant envoi : capture d'un message au lieu de l'expédier.

Demande du 11/11/2026 : quand quelqu'un déclenche un envoi **vers un tiers**, une fenêtre
s'ouvre avec le texte prévu, modifiable pour cet envoi.

**Aucun des 48 points d'envoi n'a été modifié**, et c'est le cœur de la conception. La capture
se fait dans `send_branded_mail` — l'entonnoir unique qui connaît l'institution — et la décision
« faut-il relire ? » se déduit de la requête :

    un utilisateur authentifié, et AUCUN destinataire n'est son adresse → il écrit à un tiers

C'est la traduction exacte du critère retenu. Les trois conséquences tombent d'elles-mêmes :

- une inscription (`request.user` anonyme) part directement — on n'ouvre pas un éditeur sur le
  mail que la personne est en train de recevoir ;
- un accusé qu'on s'envoie à soi-même part directement, puisque le destinataire est l'acteur ;
- un envoi sans requête (supervision, pont, alerte sismique) part directement, faute d'humain.

**Les liens sont masqués par VALEUR.** `build_magic_link` déclare chaque lien qu'il produit sur
la requête ; on remplace exactement ces chaînes par `[LIEN_1]`, `[LIEN_2]`… et on garde la
correspondance **chiffrée** côté serveur, jamais servie au client. Reconnaître les liens par
motif d'URL laisserait passer la première forme à laquelle on n'aurait pas pensé — et un lien
manqué dans une fenêtre de relecture, c'est un administrateur qui peut prendre la main sur le
compte d'un bénévole (cas réel : `UserViewSet.send_password_reset`).

**L'action, elle, a déjà eu lieu.** Le compte est validé, le dossier est clôturé ; seul le
message attend. Une relecture oubliée priverait donc quelqu'un de son information sans que rien
ne le signale : d'où `expedier_les_brouillons_oublies`, à lancer périodiquement, qui envoie
au-delà d'un délai en le tracant.
"""
import json
import logging

logger = logging.getLogger(__name__)

#: Au-delà de ce délai, un brouillon jamais relu part quand même (voir la commande
#: `expedier_brouillons_oublies`). Une relecture oubliée ne doit pas priver quelqu'un de son
#: information — un compte validé dont le titulaire n'est jamais prévenu est pire qu'un texte
#: non relu.
DELAI_RELECTURE_HEURES = 24


def doit_etre_relu(request, institution, destinataires):
    """Vrai si ce message doit passer par la fenêtre de relecture.

    Trois conditions, et chacune a sa raison :

    - l'institution a activé la relecture (sinon rien ne change pour les autres) ;
    - la requête porte un utilisateur authentifié (sinon personne n'est là pour relire) ;
    - aucun destinataire n'est l'adresse de cet utilisateur (sinon on lui ouvrirait un éditeur
      sur son propre accusé de réception, avec son propre lien de connexion dedans).
    """
    from .envoi_institution import configuration_envoi

    config = configuration_envoi(institution)
    if config is None or not config.relecture_avant_envoi:
        return False

    utilisateur = getattr(request, 'user', None) if request is not None else None
    if utilisateur is None or not getattr(utilisateur, 'is_authenticated', False):
        return False

    sienne = (getattr(utilisateur, 'email', '') or '').strip().lower()
    if not sienne:
        return False
    adresses = {(a or '').strip().lower() for a in destinataires}
    return sienne not in adresses


def masquer_les_liens(request, texte):
    """Remplace les liens magiques de CETTE requête par `[LIEN_n]`.

    Renvoie `(texte_masqué, {placeholder: url})`. La correspondance est destinée au stockage
    chiffré, jamais au client.

    Les liens sont triés du plus long au plus court avant remplacement : un lien peut être le
    préfixe d'un autre (le même, avec un `?next=`), et remplacer le court d'abord laisserait un
    fragment d'URL réelle dans le texte.
    """
    liens = list(getattr(request, '_liens_magiques', None) or []) if request is not None else []
    correspondance = {}
    masque = texte or ""
    for indice, url in enumerate(sorted(set(liens), key=len, reverse=True), start=1):
        if url and url in masque:
            placeholder = f"[LIEN_{indice}]"
            masque = masque.replace(url, placeholder)
            correspondance[placeholder] = url
    return masque, correspondance


def restaurer_les_liens(texte, correspondance):
    """Remet les vraies URL. Appelé au seul moment de l'envoi."""
    restaure = texte or ""
    for placeholder, url in (correspondance or {}).items():
        restaure = restaure.replace(placeholder, url)
    return restaure


def capturer(request, institution, sujet, message, destinataires, reply_to=None):
    """Enregistre un brouillon à relire et le déclare sur la requête.

    Renvoie le brouillon. L'identifiant est déposé sur `request._brouillons_envoi` : un
    middleware le pose ensuite en en-tête de réponse, ce qui permet à l'interface d'ouvrir la
    fenêtre **sans qu'aucun des 25 endpoints concernés ne change de contrat**.
    """
    from .models import BrouillonEnvoi, Environment
    from .permissions import get_active_environment

    masque, correspondance = masquer_les_liens(request, message)
    sujet_masque, correspondance_sujet = masquer_les_liens(request, sujet)
    correspondance.update(correspondance_sujet)

    brouillon = BrouillonEnvoi.objects.create(
        institution=institution,
        cree_par=request.user,
        canal=BrouillonEnvoi.Canal.EMAIL,
        sujet=sujet_masque,
        corps=masque,
        destinataires=list(destinataires),
        reply_to=reply_to or "",
        liens_masques=json.dumps(correspondance) if correspondance else "",
        environment=get_active_environment(request) if request is not None else Environment.PROD,
    )

    try:
        files = getattr(request, '_brouillons_envoi', None)
        if files is None:
            files = []
            request._brouillons_envoi = files
        files.append(str(brouillon.id))
    except Exception:
        logger.debug("Brouillon non déclaré sur la requête : la fenêtre ne s'ouvrira pas "
                     "d'elle-même, le brouillon reste dans la liste à relire.")

    return brouillon


def resoudre_modele(institution, cle):
    """Le texte à employer pour ce message : la version de l'institution, ou le défaut.

    Renvoie `(sujet, corps, personnalise)`. Un champ laissé vide côté institution retombe sur le
    défaut pour CE champ seulement : une institution qui veut changer le corps sans toucher au
    sujet n'a pas à recopier le sujet.

    Jamais d'exception sur une clé inconnue : l'appelant retombe sur son texte en dur plutôt que
    de faire échouer l'action que le message accompagne.
    """
    from .modeles_messages import modele as modele_defaut
    from .models import ModeleMessage

    defaut = modele_defaut(cle)
    if defaut is None:
        return None, None, False
    if institution is None or not defaut.personnalisable:
        return defaut.sujet, defaut.corps, False

    propre = ModeleMessage.objects.filter(
        institution=institution, cle=cle, actif=True,
    ).first()
    if propre is None:
        return defaut.sujet, defaut.corps, False

    return (propre.sujet or defaut.sujet,
            propre.corps or defaut.corps,
            bool(propre.sujet or propre.corps))


def envoyer_brouillon(request, brouillon, sujet=None, corps=None, statut_final=None):
    """Envoie un brouillon relu, en restaurant les vrais liens au dernier moment.

    `sujet`/`corps` : les versions relues. Absents = le texte capturé tel quel.

    Renvoie `(True, "")` ou `(False, motif)`. Ne lève pas : l'appelant est une vue, qui doit
    rendre un statut HTTP plutôt qu'un 500.
    """
    import json as _json

    from django.utils import timezone

    from .audit import send_mail_logged
    from .envoi_institution import envoyer_email_pour_institution
    from .models import BrouillonEnvoi

    if brouillon.statut != BrouillonEnvoi.Statut.A_RELIRE:
        return False, f"Ce brouillon est déjà au statut « {brouillon.get_statut_display()} »."

    sujet_final = sujet if sujet is not None else brouillon.sujet
    corps_final = corps if corps is not None else brouillon.corps

    # LES VRAIS LIENS SONT REMIS ICI, ET NULLE PART AILLEURS. Ni le brouillon stocké, ni la
    # réponse d'API, ni l'écran de relecture ne les ont vus.
    try:
        correspondance = _json.loads(brouillon.liens_masques) if brouillon.liens_masques else {}
    except ValueError:
        correspondance = {}
    sujet_final = restaurer_les_liens(sujet_final, correspondance)
    corps_final = restaurer_les_liens(corps_final, correspondance)

    destinataires = list(brouillon.destinataires or [])
    if not destinataires:
        return False, "Aucun destinataire."

    envoye, detail = envoyer_email_pour_institution(
        request, brouillon.institution, sujet_final, corps_final, destinataires,
        reply_to=brouillon.reply_to or None,
    )
    if not envoye:
        # Même repli que pour un envoi direct : le message part par le SMTP Assista-Crise en
        # gardant le texte de l'institution (voir core/envoi_institution.py).
        try:
            send_mail_logged(
                request, subject=sujet_final, message=corps_final, from_email=None,
                recipient_list=destinataires,
                reply_to=[brouillon.reply_to] if brouillon.reply_to else None,
            )
        except Exception as erreur:
            brouillon.erreur = str(erreur)[:500]
            brouillon.save(update_fields=['erreur'])
            return False, str(erreur)

    brouillon.statut = statut_final or BrouillonEnvoi.Statut.ENVOYE
    brouillon.date_traitement = timezone.now()
    brouillon.traite_par = getattr(request, 'user', None) if request is not None else None
    if brouillon.traite_par is not None and not getattr(brouillon.traite_par, 'is_authenticated', False):
        brouillon.traite_par = None
    brouillon.modifie_par_relecteur = (
        sujet is not None and sujet != brouillon.sujet
    ) or (corps is not None and corps != brouillon.corps)
    brouillon.erreur = ""
    brouillon.save(update_fields=['statut', 'date_traitement', 'traite_par',
                                  'modifie_par_relecteur', 'erreur'])
    return True, ""
