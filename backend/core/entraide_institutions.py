"""Proposer son aide à une institution qui fait face à une crise.

Demande de Sylvain du 12/11/2026 : « il faut qu'une institution déclarée sur la plateforme, de
l'association à la collectivité territoriale, puisse contacter une institution se trouvant en
situation de crise pour proposer son aide ».

**Presque tout existait déjà, et c'est ce qui a guidé la forme.** Une institution se déclare
acteur sur une crise (`ImplicationInstitution`, `type_implication = ACTEUR`) ; si elle n'est pas
une collectivité, sa déclaration reste `EN_ATTENTE` jusqu'à ce qu'un régulateur de la
collectivité l'accepte — c'est le mandat exigé d'une association qui n'intervient pas sur
délégation. Les crises, elles, sont publiques : la liste n'est pas filtrée par zone, précisément
« pour permettre à une institution de candidater n'importe où ».

Il manquait deux choses, et seulement deux :

1. **un geste** — on construisait une implication à la main depuis le formulaire, avec ses
   thèmes et son type, là où l'intention est « nous proposons notre aide » ;
2. **savoir à qui parler.** Proposer son aide à une organisation dont on ne peut joindre
   personne ne mène nulle part, et la fiche d'une institution ne devrait pas avoir à être
   ouverte au hasard pour trouver un numéro.

`referents_de_la_crise` répond au second point **sans ouvrir l'annuaire** : il ne rend que les
institutions déjà engagées sur CETTE crise, leurs coordonnées d'organisation (celles qui
figurent sur leur papier à en-tête), et le nom du responsable qu'elles ont désigné pour cette
crise. Jamais les coordonnées personnelles de ce responsable : qui veut le joindre passe par
le standard de son institution, comme au téléphone.
"""


def referents_de_la_crise(crise, environnement):
    """Les institutions à qui s'adresser pour cette crise, et comment.

    Les collectivités d'abord : ce sont elles qui acceptent une offre d'aide, et donc elles
    qu'il faut joindre. Les autres acteurs suivent — savoir qui est déjà sur place évite de
    proposer ce qui est couvert."""
    from .atouts import besoins_couverts
    from .models import ImplicationInstitution, StatutImplication, TypeImplication
    from .views import _institution_est_autorite_locale

    implications = (
        ImplicationInstitution.objects
        .filter(crise=crise, actif=True, statut=StatutImplication.VALIDEE,
                environment=environnement)
        .select_related("institution", "institution__type", "responsable")
    )

    referents = []
    for implication in implications:
        institution = implication.institution
        autorite = _institution_est_autorite_locale(institution)
        referents.append({
            "institution": institution.id,
            "nom": institution.nom_affichage or institution.nom,
            "type": getattr(institution.type, "libelle", None),
            "autorite_locale": autorite,
            "role_sur_la_crise": implication.get_type_implication_display(),
            # Coordonnées de l'ORGANISATION, pas d'une personne : c'est le standard qu'on
            # appelle quand on propose son aide, pas le portable du responsable.
            # Ce que cette institution a déclaré pouvoir apporter (core/atouts.py) : savoir
            # qu'il y a déjà une cuisine sur place évite d'en proposer une seconde.
            "peut_apporter": besoins_couverts(institution.atouts),
            "telephone": institution.telephone or None,
            "email": institution.email or None,
            # Le nom du responsable désigné, pour demander la bonne personne — sans ses
            # coordonnées propres.
            "responsable_nom": (
                f"{implication.responsable.first_name} {implication.responsable.last_name}".strip()
                or None
            ) if implication.responsable_id else None,
        })

    # Les collectivités en tête : ce sont elles qui décident.
    referents.sort(key=lambda r: (not r["autorite_locale"], (r["nom"] or "").lower()))
    return referents
