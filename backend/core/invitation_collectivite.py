"""« Rejoindre votre collectivité » : inviter les mairies et intercommunalités d'un département
délégué à ouvrir leurs comptes, puis à compléter ce qui prépare la gestion de crise (21/11/2026).

Demande de Sylvain : « On doit pouvoir inviter tout ce beau monde facilement à créer son
institution sur la plateforme puis à compléter les éléments pour préparer la gestion de crise. »

La collectivité existe déjà (créée par l'amorçage, sans doublon) : l'invitation y rattache des
personnes, elle ne crée jamais d'institution. Elle part à l'adresse officielle ; un compte créé
par le lien est inactif jusqu'à l'activation par courriel, et signalé à l'adresse officielle.
"""
import datetime

from django.conf import settings
from django.utils import timezone

DUREE_JOURS = 30


def lien(invitation) -> str:
    return f"{settings.SERVER_URL.rstrip('/')}/rejoindre-collectivite/{invitation.jeton}"


def inviter(institution, delegation, request):
    """Envoie (ou renvoie) l'invitation d'une collectivité. Rend 'envoyee', 'sans_email' ou
    'deja_membre'. Une invitation encore valable est relancée avec le même lien, prolongée."""
    from .branding import branding_for_institution, send_branded_mail
    from .models import ContactInstitution, InvitationCollectivite

    from .models import ReferentCollectivite

    if ContactInstitution.objects.filter(institution=institution, actif=True).exists():
        return "deja_membre"
    # La personne référente indiquée (par le conseil départemental, l'AASC) en priorité : c'est
    # souvent elle qui répond, pas l'adresse officielle (21/11/2026).
    referent = ReferentCollectivite.objects.filter(institution=institution).first()
    destinataire = (referent.email if referent and referent.email else None) or institution.email
    if not destinataire:
        return "sans_email"
    maintenant = timezone.now()
    invitation = (InvitationCollectivite.objects.filter(institution=institution, actif=True)
                  .order_by("-date_envoi").first())
    if invitation is not None and invitation.utilisable:
        invitation.date_relance = maintenant
        invitation.email = destinataire
        invitation.date_expiration = timezone.localdate() + datetime.timedelta(days=DUREE_JOURS)
        invitation.save(update_fields=["date_relance", "email", "date_expiration"])
    else:
        invitation = InvitationCollectivite.objects.create(
            institution=institution, delegation=delegation, email=destinataire,
            invite_par=request.user, environment=institution.environment,
            date_expiration=timezone.localdate() + datetime.timedelta(days=DUREE_JOURS))
    aasc = delegation.aasc if delegation else None
    nom_aasc = branding_for_institution(aasc).nom_affichage if aasc else "La plateforme"
    salutation = f"Bonjour {referent.nom}," if referent and referent.nom and destinataire == referent.email else "Bonjour,"
    message = (
        f"{salutation}\n\n"
        f"{nom_aasc} exploite la plateforme de gestion de crise pour votre département, dans le cadre "
        f"de la convention signée avec le conseil départemental. L'espace de {institution.nom} y est "
        "prêt : coordonnées officielles, risques de la commune, adresses et sites sensibles ont déjà "
        "été récupérés.\n\n"
        "Pour l'ouvrir, chaque personne concernée (maire, adjoints, secrétariat, services) crée son "
        "compte avec ce lien, puis complète ce qui prépare la gestion de crise : organisation, "
        "annuaire, lieux d'accueil, moyens d'alerte.\n\n"
        f"- Rejoindre {institution.nom} : {lien(invitation)}\n\n"
        f"Ce lien est valable {DUREE_JOURS} jours et sert à {InvitationCollectivite.MAX_COMPTES} comptes au plus. "
        "Chaque compte créé vous est signalé à cette adresse.\n\n{signature}"
    )
    send_branded_mail(request, aasc or institution, subject=f"Votre espace {institution.nom} est prêt",
                      message=message, recipient_list=[destinataire], fail_silently=True)
    return "envoyee"


def trouver(jeton):
    from .crypto_fields import empreinte_jeton
    from .models import InvitationCollectivite
    if not jeton:
        return None
    invitation = (InvitationCollectivite.objects.select_related("institution", "delegation__aasc")
                  .filter(jeton_empreinte=empreinte_jeton(jeton)).first())
    return invitation if invitation is not None and invitation.utilisable else None


def rejoindre(invitation, donnees, request):
    """Crée le compte (inactif, autorité locale, rattaché à la collectivité), accepte au besoin
    la convention de sous-traitance, envoie le lien d'activation — qui mène à « Mon plan de
    sauvegarde » — et signale le nouveau compte à l'adresse officielle."""
    from rest_framework.exceptions import ValidationError

    from .branding import send_branded_mail
    from .crypto_fields import blind_index
    from .institution_attachment import _get_or_create_contact_institution, grant_institution_and_demo_access
    from .models import User, UserRole
    from .views import _traiter_acceptation_convention, build_magic_link

    institution = invitation.institution
    email = (donnees.get("email") or "").strip().lower()
    prenom = (donnees.get("prenom") or "").strip()[:150]
    nom = (donnees.get("nom") or "").strip()[:150]
    if "@" not in email or not prenom or not nom:
        raise ValidationError({"error": "Prénom, nom et courriel sont obligatoires."})

    existant = User.objects.filter(email_bidx=blind_index(email)).first()
    if existant is not None:
        user = existant
    else:
        user = User.objects.create_user(
            username=email, email=email, password=None, type=UserRole.LOCAL_AUTHORITY,
            first_name=prenom, last_name=nom, phone_number=(donnees.get("telephone") or "").strip()[:30] or None,
            institution=institution, enabled=False, is_active=False)
    _traiter_acceptation_convention(request, institution, user)
    _get_or_create_contact_institution(institution, user, (donnees.get("fonction") or "").strip()[:120] or "Collectivité")
    grant_institution_and_demo_access(user, institution, request)
    invitation.comptes_crees += 1
    invitation.save(update_fields=["comptes_crees"])

    action = "magic-login" if existant is not None and existant.is_active else "activate-account"
    lien_acces = build_magic_link(request, user, action, next_url="/admin/plans")
    send_branded_mail(
        request, invitation.delegation.aasc if invitation.delegation else institution,
        subject=f"Votre compte pour {institution.nom}",
        message=(f"Bonjour {prenom},\n\nVotre compte pour {institution.nom} est prêt. Ce lien l'active et "
                 f"vous mène à « Mon plan de sauvegarde », où l'encadré « Ce qui reste à compléter » vous "
                 f"guide :\n\n{lien_acces}\n\nCe lien est valable 7 jours.\n\n{{signature}}"),
        recipient_list=[email], fail_silently=True)
    if invitation.email and invitation.email.lower() != email:
        send_branded_mail(
            request, invitation.delegation.aasc if invitation.delegation else institution,
            subject=f"Nouveau compte pour {institution.nom}",
            message=(f"Bonjour,\n\n{prenom} {nom} ({email}) vient de créer un compte pour {institution.nom} "
                     "avec le lien d'invitation. Si ce n'est pas une personne de votre collectivité, "
                     "signalez-le en répondant à ce message.\n\n{signature}"),
            recipient_list=[invitation.email], fail_silently=True)
    return user
