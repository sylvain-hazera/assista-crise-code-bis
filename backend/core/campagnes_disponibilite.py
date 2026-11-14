"""Envoi d'une campagne de disponibilité, et suivi des réponses.

Séparé des vues parce que trois choses s'y décident et qu'aucune n'est du ressort d'un
`ViewSet` : qui a le droit de solliciter, ce que le message dit, et comment une réponse est
reconnue.

**L'envoi passe par `send_modele_mail`**, donc par le chemin unique de la marque blanche : API
de l'institution, repli SMTP, journalisation, et surtout **relecture par lots** — un texte
générique validé une fois pour N destinataires, chacun repersonnalisé à l'envoi. Écrire un
second chemin d'envoi pour les campagnes ferait exactement ce que la fenêtre de relecture
existe pour empêcher : des centaines de messages partis sans qu'un humain ait lu le texte.
"""
import logging

logger = logging.getLogger(__name__)

#: Phrase d'accroche par motif. Le motif est TYPÉ (voir `MotifCampagne`), donc le ton peut
#: l'être aussi : on n'écrit pas de la même façon avant, pendant et après.
ACCROCHES = {
    "CRISE_A_VENIR": "Une situation à risque est annoncée sur notre territoire et nous "
                     "préparons notre dispositif.",
    "CRISE_EN_COURS": "Nous sommes engagés sur une crise en cours et devons organiser la "
                      "relève.",
    "RETABLISSEMENT": "La phase d'urgence est passée, mais le rétablissement va demander une "
                      "présence sur la durée.",
    "EXERCICE": "Nous organisons un exercice et avons besoin de connaître vos disponibilités.",
}


def _est_association(institution):
    from .institution_attachment import CODE_TYPE_AASC

    type_ = getattr(institution, "type", None)
    return bool(type_ and (type_.code or "").lower() == CODE_TYPE_AASC)


def _pilote_toute_l_institution(utilisateur, institution):
    """Peut solliciter TOUTE l'institution, sans se limiter à une équipe.

    - **Le bureau**, quelle que soit l'institution : c'est le drapeau de gouvernance du
      rattachement.
    - **Dans une institution qui n'est pas une association** (mairie, intercommunalité…), le
      compte institutionnel qui y est rattaché. Demande de Sylvain du 14/11/2026 : « ces
      campagnes peuvent être utilisées aussi par des municipalités ». Une mairie n'a pas de
      bureau ; ceux qui y décident sont ses agents et élus, c'est-à-dire ses comptes
      « autorité locale » ou « secours ». Dans une association ce critère ne suffit PAS : un
      simple adhérent promu « secours » n'administre pas l'association.

    L'appartenance se lit dans `ContactInstitution`, jamais dans `User.institution`, qui est
    un contexte et non une appartenance (voir `core/institution_courante.py`)."""
    from .models import ContactInstitution, UserRole

    rattachement = ContactInstitution.objects.filter(
        institution=institution, utilisateur=utilisateur, actif=True,
    ).first()
    if rattachement is None:
        return False
    if rattachement.membre_bureau:
        return True
    if _est_association(institution):
        return False
    return getattr(utilisateur, "type", None) in (
        UserRole.LOCAL_AUTHORITY, UserRole.ORGANIZED_RESCUE,
    )


def peut_lancer_campagne(utilisateur, institution, equipe=None):
    """Les responsables pour toute l'institution, l'encadrement pour SA branche.

    Décision de Sylvain du 11/11/2026. Le motif de laisser l'encadrement lancer : sinon la
    coordination nationale est le seul goulot pour une crise départementale, et une sollicitation
    qui doit partir dans l'heure attend une validation à Paris.

    L'encadrement est tenu à une `equipe` : un coordinateur de Gironde qui lancerait une
    campagne nationale écrirait à des gens dont il n'a pas la charge.

    Une équipe d'une AUTRE institution est refusée à tout le monde, administrateur compris :
    ce n'est pas un droit qui manque, c'est une campagne incohérente — elle écrirait au nom de
    l'une aux membres de l'autre."""
    from .models import Team, UserRole

    if equipe is not None and equipe.institution_id != institution.id:
        return False

    if getattr(utilisateur, "type", None) == UserRole.ADMINISTRATOR:
        return True

    if _pilote_toute_l_institution(utilisateur, institution):
        return True

    if equipe is None:
        # Ni responsable ni équipe nommée : la campagne viserait toute l'institution.
        return False

    # Encadrant de cette équipe, ou d'une équipe AU-DESSUS : un coordinateur régional peut
    # solliciter un de ses départements.
    from .visibilite_membres import _equipes_descendantes

    encadrees = Team.objects.filter(
        institution=institution, membres_encadrement=utilisateur,
    ).values_list("id", flat=True)
    return equipe.id in _equipes_descendantes(list(encadrees))


def perimetre_de_pilotage(utilisateur):
    """Où cette personne peut mener des campagnes : `(institutions, equipes)`.

    `institutions` : celles qu'elle peut solliciter en entier. `equipes` : les branches qu'elle
    encadre ailleurs (l'équipe et tout ce qui est dessous). C'est le périmètre de LECTURE comme
    d'écriture : avant le 14/11/2026 tout membre actif lisait les campagnes de son institution
    — donc leur texte, parfois antérieur à l'annonce publique, et la liste nominative de qui
    avait répondu quoi. Un adhérent n'a à connaître que la campagne qui lui est adressée, et
    elle lui arrive par son message.

    Ne sert pas à l'administrateur, qui n'a pas de périmètre : il choisit son institution."""
    from .models import ContactInstitution, Team
    from .visibilite_membres import _equipes_descendantes

    institutions = set()
    for rattachement in ContactInstitution.objects.filter(
        utilisateur=utilisateur, actif=True, institution__actif=True,
    ).select_related("institution__type"):
        if _pilote_toute_l_institution(utilisateur, rattachement.institution):
            institutions.add(rattachement.institution_id)

    encadrees = list(Team.objects.filter(
        membres_encadrement=utilisateur, institution__actif=True,
    ).exclude(institution_id__in=institutions).values_list("id", flat=True))
    return institutions, _equipes_descendantes(encadrees)


def institutions_proposees(utilisateur, recherche="", limite=50):
    """Les institutions où cette personne peut se placer pour mener une campagne.

    Chaque ligne dit sa PORTÉE : `toute` l'institution, ou seulement les `equipes` encadrées.

    **L'administrateur** les a toutes, mais par recherche et sans qu'aucune ne soit choisie à
    sa place (demande du 14/11/2026 : « ce doit être choisi et précis »). La page prenait la
    première association de la liste : un administrateur composait donc une campagne pour une
    institution qu'il n'avait pas désignée, et pouvait écrire à ses membres en croyant
    s'adresser à d'autres."""
    from .models import Institution, Team, UserRole

    def ligne(institution, portee):
        return {
            "id": str(institution.id),
            "nom": institution.nom_affichage or institution.nom,
            "type": institution.type.libelle if institution.type_id else "",
            "portee": portee,
        }

    if getattr(utilisateur, "type", None) == UserRole.ADMINISTRATOR:
        qs = Institution.objects.filter(actif=True).select_related("type").order_by("nom")
        recherche = (recherche or "").strip()
        if recherche:
            qs = qs.filter(nom__icontains=recherche)
        total = qs.count()
        return {
            "administrateur": True, "total": total,
            "institutions": [ligne(i, "toute") for i in qs[:limite]],
        }

    institutions, equipes = perimetre_de_pilotage(utilisateur)
    par_equipe = set(Team.objects.filter(id__in=equipes).values_list(
        "institution_id", flat=True)) - institutions
    lignes = [ligne(i, "toute") for i in Institution.objects.filter(
        id__in=institutions).select_related("type").order_by("nom")]
    lignes += [ligne(i, "equipes") for i in Institution.objects.filter(
        id__in=par_equipe, actif=True).select_related("type").order_by("nom")]
    return {"administrateur": False, "total": len(lignes), "institutions": lignes}


def _periode_lisible(campagne):
    """« 12 au 26 janvier 2027 » — et non deux dates ISO : le message est lu par un humain."""
    debut, fin = campagne.periode_debut, campagne.periode_fin
    mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
            "septembre", "octobre", "novembre", "décembre"]
    if debut == fin:
        return f"{debut.day} {mois[debut.month - 1]} {debut.year}"
    if (debut.month, debut.year) == (fin.month, fin.year):
        return f"{debut.day} au {fin.day} {mois[fin.month - 1]} {fin.year}"
    return (f"{debut.day} {mois[debut.month - 1]} au {fin.day} {mois[fin.month - 1]} "
            f"{fin.year}")


def _phrase_rotation(campagne):
    """Ce que le bénévole doit savoir des rotations, ou rien.

    Rien plutôt qu'une phrase vide : « par tranches de 0 jour » n'informe personne, et une
    ligne de remplissage dans un message qu'on veut voir lu est une ligne de trop."""
    if not campagne.tours_de_garde:
        return ("Nous ne vous engageons à rien : il s'agit de savoir sur qui nous pouvons "
                "compter.")
    return (f"L'organisation se fera par tours de {campagne.duree_rotation_jours} jour(s), "
            f"avec au moins {campagne.repos_min_jours} jour(s) de repos entre deux tours : "
            f"personne ne doit rester mobilisé toute la période.")


def constituer_les_cibles(campagne):
    """Fige la liste des destinataires d'après les critères. Idempotent.

    Les cibles déjà contactées ne sont jamais retirées : on ne peut pas « dé-écrire » à
    quelqu'un, et le suivi doit rester celui des gens à qui on a réellement écrit.

    Avec `ciblage_large`, s'y ajoutent les membres dont le dossier ne permet pas de vérifier
    les critères (voir `ciblage_benevoles.cibler_large`) ; `a_completer` dit combien."""
    from .ciblage_benevoles import cibler_large, cibler_pour_campagne
    from .models import CibleCampagne, EtatCible

    stricts = list(cibler_pour_campagne(campagne).values_list("id", "author_id"))
    if campagne.ciblage_large:
        retenues = cibler_large(campagne)
        connus = {utilisateur_id for _o, utilisateur_id in stricts}
        # Ceux que seul le ciblage large retient : leur dossier ne permet pas de vérifier les
        # critères. Compté pour être DIT avant l'envoi, pas pour être caché dans le total.
        a_completer = sum(1 for _o, utilisateur_id in retenues if utilisateur_id not in connus)
    else:
        retenues = stricts
        a_completer = 0
    existantes = dict(
        CibleCampagne.objects.filter(campagne=campagne).values_list("utilisateur_id", "id")
    )

    creees = 0
    for offre_id, utilisateur_id in retenues:
        if utilisateur_id in existantes:
            continue
        CibleCampagne.objects.create(
            campagne=campagne, utilisateur_id=utilisateur_id, ressource_id=offre_id,
            environment=campagne.environment,
        )
        creees += 1

    # Celles qui ne correspondent plus ET qui n'ont pas été contactées : la liste d'un
    # brouillon doit suivre ses critères.
    retenus_ids = {utilisateur_id for _o, utilisateur_id in retenues}
    retirees = CibleCampagne.objects.filter(
        campagne=campagne, etat=EtatCible.A_CONTACTER,
    ).exclude(utilisateur_id__in=retenus_ids).delete()[0]

    return {"creees": creees, "retirees": retirees,
            "total": CibleCampagne.objects.filter(campagne=campagne).count(),
            "a_completer": a_completer}


def envoyer_campagne(campagne, request):
    """Écrit à toutes les cibles restant à contacter. Renvoie un bilan.

    Une cible par message, mais **un seul texte** : `send_modele_mail` capture les brouillons
    et la fenêtre de relecture les regroupe en lot (même texte générique), de sorte que
    l'association valide une fois ce qui part à 87 personnes.
    """
    from django.utils import timezone

    from .branding import send_modele_mail
    from .models import CibleCampagne, EtatCible, StatutCampagne
    from .views import build_magic_link

    periode = _periode_lisible(campagne)
    accroche = ACCROCHES.get(campagne.motif, "")
    rotation = _phrase_rotation(campagne)

    from .canaux_campagne import (
        CANAL_APPLICATION, CANAL_EMAIL, CANAL_MATRIX, CANAL_MOBIMEL, CANAL_SMS,
    )
    from .models import GenreNotification
    from .notifications_application import notifier

    canaux = campagne.canaux_effectifs
    envoyes, echecs = 0, 0
    # Un compte par canal : « 87 envoyés » ne dit pas si les SMS sont partis, et c'est
    # pourtant eux qui coûtent.
    par_canal = {code: 0 for code in canaux}
    a_contacter = CibleCampagne.objects.filter(
        campagne=campagne, etat=EtatCible.A_CONTACTER,
    ).select_related("utilisateur")

    for cible in a_contacter:
        try:
            # Le lien emmène sur la grille POSITIONNÉE sur la période demandée : c'est la
            # réponse à « et pas seulement un texte libre dans le mail ». Sans le paramètre de
            # campagne, le bénévole arriverait sur ses quinze prochains jours et répondrait à
            # une autre question que celle posée.
            lien = build_magic_link(
                request, cible.utilisateur, "magic-login",
                next_url=f"/ma-fiche-benevole?campagne={campagne.id}",
            )
            atteint = False
            # L'application d'abord : elle ne coûte rien, et c'est elle qui dira si le
            # message a été reçu. Pas de lien dans le texte — l'application ouvre elle-même
            # la grille sur la période demandée.
            if CANAL_APPLICATION in canaux:
                notification = notifier(
                    cible.utilisateur, GenreNotification.CAMPAGNE,
                    _titre_application(campagne, periode),
                    "\n\n".join(p for p in (accroche, campagne.texte or "", rotation) if p),
                    urgent=campagne.motif == "CRISE_EN_COURS",
                    institution=campagne.institution, campagne=campagne,
                )
                if notification is not None:
                    par_canal[CANAL_APPLICATION] += 1
                    atteint = True
            if CANAL_EMAIL in canaux and cible.utilisateur.email:
                send_modele_mail(
                    request, campagne.institution, "CAMPAGNE_DISPONIBILITE",
                    {
                        # nom-reel-assume: le prénom du destinataire, dans un message qui lui
                        # est adressé.
                        "PRENOM": cible.utilisateur.first_name or "",
                        "MOTIF": accroche,
                        "TEXTE": campagne.texte or "",
                        "PERIODE": periode,
                        "ROTATION": rotation,
                        "LIEN_DISPONIBILITES": lien,
                    },
                    recipient_list=[cible.utilisateur.email],
                    fail_silently=False,
                )
                par_canal[CANAL_EMAIL] += 1
                atteint = True

            # Le SMS porte le MÊME lien, mais pas le même texte : 160 caractères, au-delà
            # desquels l'opérateur facture un second message. On dit l'essentiel — qui
            # demande, pour quand, et où répondre.
            if {CANAL_SMS, CANAL_MOBIMEL} & set(canaux) and cible.utilisateur.phone_number:
                from .envoi_sms import envoyer_sms_pour_institution

                parti, _motif = envoyer_sms_pour_institution(
                    campagne.institution, cible.utilisateur.phone_number,
                    _texte_sms(campagne, periode, lien),
                )
                if parti:
                    code = CANAL_SMS if CANAL_SMS in canaux else CANAL_MOBIMEL
                    par_canal[code] += 1
                    atteint = True

            if CANAL_MATRIX in canaux:
                from .matrix import envoyer_dm

                # Silencieux si la personne ne s'est jamais connectée à la messagerie : c'est
                # le comportement d'`envoyer_dm`, et c'est pourquoi Matrix est annoncé comme
                # une estimation haute à l'écran.
                envoyer_dm(cible.utilisateur, _texte_sms(campagne, periode, lien))
                par_canal[CANAL_MATRIX] += 1

            if not atteint and CANAL_MATRIX not in canaux:
                raise RuntimeError(
                    "Aucun canal retenu ne permet de joindre cette personne "
                    "(ni application, ni adresse email, ni numéro de téléphone selon les "
                    "canaux choisis)."
                )
            cible.etat = EtatCible.CONTACTE
            cible.date_envoi = timezone.now()
            cible.erreur = ""
            envoyes += 1
        except Exception as erreur:  # noqa: BLE001 — on nomme l'échec, on ne l'avale pas
            # Nommé par destinataire : une campagne « partie » dont dix messages n'ont pas
            # abouti ferait compter dix personnes qui n'ont jamais été prévenues.
            logger.warning("Campagne %s : envoi impossible pour %s (%s)",
                           campagne.id, cible.utilisateur_id, erreur)
            cible.etat = EtatCible.INJOIGNABLE
            cible.erreur = str(erreur)[:255]
            echecs += 1
        cible.save(update_fields=["etat", "date_envoi", "erreur"])

    if envoyes and campagne.statut == StatutCampagne.BROUILLON:
        campagne.statut = StatutCampagne.ENVOYEE
        campagne.date_envoi = timezone.now()
        campagne.save(update_fields=["statut", "date_envoi"])

    return {"envoyes": envoyes, "echecs": echecs, "par_canal": par_canal}


def _titre_application(campagne, periode):
    """Ce qui s'affiche sur l'écran verrouillé : qui demande, et pour quand.

    Rien du motif ni du texte : une notification se lit par-dessus l'épaule, et le « pourquoi »
    d'une campagne décrit parfois une situation qui n'est pas encore publique."""
    nom = campagne.institution.nom_affichage or campagne.institution.nom
    return f"{nom} : êtes-vous disponible du {periode} ?"


def _texte_sms(campagne, periode, lien):
    """Le texte court, pour le SMS et la messagerie d'équipe.

    Volontairement sec : au-delà de 160 caractères l'opérateur facture un second message, et
    une campagne à quatre cents personnes paierait deux fois. On garde ce qui décide quelqu'un
    à cliquer — qui demande, pour quand, et le lien."""
    nom = campagne.institution.nom_affichage or campagne.institution.nom
    return f"{nom} : disponibilités demandées du {periode}. Répondez ici : {lien}"


def enregistrer_la_reponse(campagne, utilisateur):
    """Marque qu'une personne a répondu, et compte ses créneaux SUR LA PÉRIODE.

    Appelée quand le bénévole enregistre des créneaux alors qu'une campagne est en cours pour
    lui. **Zéro créneau est une réponse** : « je ne suis pas disponible » n'est pas un silence,
    et les confondre fait relancer quelqu'un qui a déjà répondu non.
    """
    from django.utils import timezone

    from .models import CibleCampagne, DisponibiliteOffre, EtatCible

    cible = CibleCampagne.objects.filter(
        campagne=campagne, utilisateur=utilisateur,
    ).first()
    if cible is None:
        return None

    combien = DisponibiliteOffre.objects.filter(
        offer__author=utilisateur, offer__institution=campagne.institution,
        date__gte=campagne.periode_debut, date__lte=campagne.periode_fin,
    ).count()

    cible.etat = EtatCible.A_REPONDU
    cible.date_reponse = timezone.now()
    cible.creneaux_declares = combien
    cible.save(update_fields=["etat", "date_reponse", "creneaux_declares"])

    from .notifications_application import noter_la_reponse

    noter_la_reponse(campagne, utilisateur)
    return cible


def repondre_indisponible(campagne, utilisateur):
    """« Je ne suis pas disponible sur cette période » : une réponse, dite en un geste.

    Jusqu'ici, répondre non voulait dire ne rien cocher — c'est-à-dire, pour le suivi, ne pas
    répondre : la personne était relancée pour avoir dit non en silence. Demande de Sylvain du
    14/11/2026 : « une réponse négative est une réponse ».

    Les créneaux déjà posés sur la période sont RETIRÉS, pour l'institution qui demande : le
    moteur n'a qu'une règle, « pas de ligne = indisponible », et laisser des créneaux cochés à
    quelqu'un qui vient de dire non ferait partir une garde sur lui."""
    from .models import DisponibiliteOffre

    DisponibiliteOffre.objects.filter(
        offer__author=utilisateur, offer__institution=campagne.institution,
        date__gte=campagne.periode_debut, date__lte=campagne.periode_fin,
    ).delete()
    return enregistrer_la_reponse(campagne, utilisateur)


def couverture(campagne):
    """Combien de personnes déclarées par jour et par créneau, sur la période.

    C'est le chiffre qui dit si la garde est armée — et le seul qui compte vraiment dans le
    suivi d'une campagne. Un taux de réponse de 80 % ne dit rien si les répondants sont tous
    disponibles le même jour."""
    from collections import defaultdict

    from .models import CibleCampagne, DisponibiliteOffre

    ressources = list(
        CibleCampagne.objects.filter(campagne=campagne, ressource__isnull=False)
        .values_list("ressource_id", flat=True)
    )
    par_jour = defaultdict(lambda: defaultdict(int))
    if ressources:
        for date_jour, creneau in DisponibiliteOffre.objects.filter(
            offer_id__in=ressources,
            date__gte=campagne.periode_debut, date__lte=campagne.periode_fin,
        ).values_list("date", "creneau"):
            par_jour[date_jour][creneau] += 1

    creneaux = campagne.creneaux_effectifs
    jours = []
    date_jour = campagne.periode_debut
    while date_jour <= campagne.periode_fin:
        jours.append({
            "date": date_jour,
            "creneaux": {c: par_jour[date_jour].get(c, 0) for c in creneaux},
        })
        date_jour = date_jour.fromordinal(date_jour.toordinal() + 1)
    return {"creneaux": creneaux, "jours": jours}
