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


def peut_lancer_campagne(utilisateur, institution, equipe=None):
    """Le bureau pour toute l'association, l'encadrement pour SA branche.

    Décision de Sylvain du 11/11/2026. Le motif de laisser l'encadrement lancer : sinon la
    coordination nationale est le seul goulot pour une crise départementale, et une sollicitation
    qui doit partir dans l'heure attend une validation à Paris.

    L'encadrement est tenu à une `equipe` : un coordinateur de Gironde qui lancerait une
    campagne nationale écrirait à des gens dont il n'a pas la charge."""
    from .models import ContactInstitution, Team, UserRole

    if getattr(utilisateur, "type", None) == UserRole.ADMINISTRATOR:
        return True

    if ContactInstitution.objects.filter(
        institution=institution, utilisateur=utilisateur, actif=True, membre_bureau=True,
    ).exists():
        return True

    if equipe is None:
        # Pas au bureau et aucune équipe nommée : la campagne viserait toute l'association.
        return False

    if equipe.institution_id != institution.id:
        return False

    # Encadrant de cette équipe, ou d'une équipe AU-DESSUS : un coordinateur régional peut
    # solliciter un de ses départements.
    from .visibilite_membres import _equipes_descendantes

    encadrees = Team.objects.filter(
        institution=institution, membres_encadrement=utilisateur,
    ).values_list("id", flat=True)
    return equipe.id in _equipes_descendantes(list(encadrees))


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
    if campagne.effectif_cible <= 0:
        return ("Nous ne vous engageons à rien : il s'agit de savoir sur qui nous pouvons "
                "compter.")
    return (f"L'organisation se fera par tours de {campagne.duree_rotation_jours} jour(s), "
            f"avec au moins {campagne.repos_min_jours} jour(s) de repos entre deux tours : "
            f"personne ne doit rester mobilisé toute la période.")


def constituer_les_cibles(campagne):
    """Fige la liste des destinataires d'après les critères. Idempotent.

    Les cibles déjà contactées ne sont jamais retirées : on ne peut pas « dé-écrire » à
    quelqu'un, et le suivi doit rester celui des gens à qui on a réellement écrit."""
    from .ciblage_benevoles import cibler_pour_campagne
    from .models import CibleCampagne, EtatCible

    retenues = list(cibler_pour_campagne(campagne).values_list("id", "author_id"))
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
            "total": CibleCampagne.objects.filter(campagne=campagne).count()}


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

    envoyes, echecs = 0, 0
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
            send_modele_mail(
                request, campagne.institution, "CAMPAGNE_DISPONIBILITE",
                {
                    # nom-reel-assume: le prénom du destinataire, dans un message qui lui est
                    # adressé.
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

    return {"envoyes": envoyes, "echecs": echecs}


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
    return cible


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
