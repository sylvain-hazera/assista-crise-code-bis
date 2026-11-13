"""Rattacher un bénévole à la section départementale de son domicile.

Demande de Sylvain du 13/11/2026 : « un rattachement du bénévole par défaut à la section
départementale de son département de résidence ».

**Ce que « section départementale » veut dire ici.** C'est une `Team` de l'association portant
`echelon = DEPARTEMENTAL` et `territoire_code = <code INSEE du département>` — l'arborescence
déjà en place pour les Casques Jaunes (national → zone de défense → région → département). On
ne crée pas un second concept : une section EST une équipe départementale, avec son salon
Matrix, son encadrement et ses disponibilités.

**Pourquoi un défaut, et pas une question posée.** Un bénévole qui s'inscrit ne connaît pas
l'organigramme de l'association ; lui demander de choisir sa section produit soit un choix au
hasard, soit un champ laissé vide. Or quelqu'un rattaché à rien n'est dans aucun salon, ne
reçoit aucune campagne ciblée par territoire, et n'apparaît sur aucune grille : il a adhéré
pour rien. L'adresse, elle, est déjà connue et déjà géocodée.

**C'est un défaut, pas une assignation définitive.** L'encadrement déplace qui il veut, et le
rattachement suit ensuite l'adresse : quelqu'un qui déménage de Gironde en Savoie quitte la
section girondine — rester mobilisable à 700 km et figurer dans deux salons départementaux
serait pire que ne pas être rattaché du tout.

**Le silence est volontaire quand il n'y a pas de section.** Beaucoup d'associations n'ont
aucune équipe départementale ; on ne va pas en inventer une. La personne reste alors dans
l'équipe de tête de l'institution, comme avant.
"""
import logging

logger = logging.getLogger(__name__)


def institutions_du_benevole(utilisateur):
    """Les associations dont la personne est membre actif."""
    from .models import ContactInstitution

    return list(
        ContactInstitution.objects.filter(utilisateur=utilisateur, actif=True)
        .values_list("institution_id", flat=True)
    )


def departement_de(utilisateur):
    """Le département de résidence, d'après la fiche de bénévole.

    Passe par `departement_de_la_fiche`, qui préfère le géocodage au code postal : un code
    postal n'est pas un code commune (la Corse partage `20xxx`, l'outre-mer demande trois
    chiffres), et se tromper ici rattache quelqu'un à la mauvaise section."""
    from .fiches_benevoles import departement_de_la_fiche
    from .models import FicheBenevole

    fiche = FicheBenevole.objects.filter(utilisateur=utilisateur).first()
    if fiche is None:
        return None
    code, _origine, _motif = departement_de_la_fiche(fiche)
    return code


def section_departementale(institution_ids, departement):
    """L'équipe départementale correspondante, ou None.

    `institution_ids` plutôt qu'une institution unique : quelqu'un peut adhérer à deux
    associations, et chacune a sa propre section dans le même département."""
    from .models import EchelonEquipe, Team

    if not departement or not institution_ids:
        return None
    return Team.objects.filter(
        institution_id__in=list(institution_ids), actif=True,
        echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code=departement,
    ).first()


def rattacher(utilisateur, institution_ids=None, departement=None, request=None,
              retirer_les_autres=False):
    """Place la personne dans la section de son département. Renvoie l'équipe, ou None.

    `retirer_les_autres` sert au déménagement : on ne reste pas membre de son ancienne section.
    À l'inverse, lors d'une simple adhésion, rien n'est retiré — la personne peut légitimement
    appartenir à l'équipe départementale d'une autre association.

    Idempotent : rappeler cette fonction sur quelqu'un déjà bien placé ne fait rien et
    n'écrit aucune ligne d'audit. Elle est appelée à chaque rattachement, un journal qui
    répéterait « déjà rattaché » serait illisible.
    """
    from .models import EchelonEquipe, Team
    from .audit import audit_log

    institution_ids = (institutions_du_benevole(utilisateur) if institution_ids is None
                       else list(institution_ids))
    departement = departement or departement_de(utilisateur)
    cible = section_departementale(institution_ids, departement)
    if cible is None:
        return None

    if retirer_les_autres:
        anciennes = Team.objects.filter(
            institution_id__in=institution_ids, echelon=EchelonEquipe.DEPARTEMENTAL,
            members=utilisateur,
        ).exclude(pk=cible.pk)
        for equipe in anciennes:
            equipe.members.remove(utilisateur)
            audit_log(
                request=request, action_code="MODIFICATION", objet_type="Team",
                objet_id=equipe.id,
                commentaire=f"{utilisateur.email} retiré : déménagement vers le département "
                            f"{departement}.",
            )

    if not cible.members.filter(pk=utilisateur.pk).exists():
        cible.members.add(utilisateur)
        audit_log(
            request=request, action_code="MODIFICATION", objet_type="Team", objet_id=cible.id,
            commentaire=f"{utilisateur.email} rattaché à la section départementale "
                        f"{departement} d'après son adresse.",
        )
    return cible


def rattacher_sans_echouer(utilisateur, institution_ids=None, request=None):
    """Variante best-effort, pour les chemins de rattachement qui ne doivent jamais échouer.

    Une adhésion réussie ne doit pas se transformer en erreur à l'écran parce que la fiche
    n'est pas encore géocodée ou qu'aucune section n'existe. Le rattachement se rejouera au
    prochain enregistrement de la fiche."""
    try:
        return rattacher(utilisateur, institution_ids=institution_ids, request=request)
    except Exception:
        logger.exception("Rattachement départemental impossible pour %s", utilisateur)
        return None
