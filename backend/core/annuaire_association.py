"""Annuaire enrichi d'une association, pour l'arborescence des équipes.

Demande de Sylvain du 12/11/2026 : l'onglet « Équipes et justificatifs » montrait un nom et
rien d'autre. Il faut pouvoir, sans quitter l'arbre, voir **la fonction dans l'équipe, les
compétences, les coordonnées**, puis trier, chercher sur tous ces critères, sélectionner
plusieurs personnes et les affecter à une équipe d'intervention terrain.

**Rien n'est inventé ici non plus** — même parti pris que `core/ciblage_benevoles.py`, et les
deux lisent délibérément les mêmes sources, pour qu'une personne trouvée par une recherche dans
l'arbre soit exactement celle qu'une campagne ciblerait :

| Information | D'où elle vient |
|---|---|
| nom, fonction, statut, bureau | `ContactInstitution` |
| email, téléphone | `User` (chiffrés au repos) |
| commune, département, métier | `FicheBenevole` |
| compétences | `Offer.competences`, porté par la RESSOURCE du bénévole |
| titres et péremptions | `QualificationMembre` |
| a-t-il déclaré ses créneaux | `DisponibiliteOffre`, le moteur unique |

**Deux cercles de lecture, et c'est le point sensible de ce module.** La page est ouverte à
tout membre d'une AASC (voir `membresAssociationGuard`), pas seulement à son bureau. Or un
numéro de téléphone, une commune de résidence et un métier ne sont pas des informations
d'annuaire ouvert : ce sont les coordonnées personnelles que l'avertissement d'inscription
promet de ne rendre visibles qu'à l'association **qui décide de la mobilisation**. On les
réserve donc au bureau et aux administrateurs, exactement comme
`ContactInstitutionSerializer.CHAMPS_SUIVI_ASSOCIATIF` le fait déjà pour l'aptitude. Un membre
ordinaire voit l'effectif, les rôles et les compétences — de quoi lire une arborescence, pas de
quoi constituer un fichier.

Les champs restreints sont **absents** de la réponse, et non mis à `null` : afficher « — »
affirmerait qu'il n'y a rien, alors qu'on n'a simplement pas le droit de savoir.
"""
from django.utils import timezone


def coordonnees_visibles(utilisateur, institution):
    """Qui a le droit de voir téléphone, commune et métier des membres.

    Le bureau de CETTE association, et les administrateurs. Volontairement le même test que
    `recrutement_association.peut_instruire` : celui qui instruit une candidature voit déjà ces
    éléments dans le dossier, lui les refuser ici n'aurait protégé personne."""
    from .recrutement_association import peut_instruire

    return peut_instruire(utilisateur, institution)


def _competences_par_utilisateur(utilisateurs, institution, environnement):
    """Les compétences déclarées, prises sur la ressource de chaque membre.

    Une seule requête pour tout l'effectif. La ressource est retrouvée par
    `(author, institution, type)` comme partout ailleurs — jamais par son titre, qui n'a aucune
    raison d'être stable (voir `fiches_benevoles.ressource_du_benevole`)."""
    from .fiches_benevoles import TYPE_OFFRE_BENEVOLE
    from .models import Offer

    ressources = Offer.objects.filter(
        author_id__in=utilisateurs, institution=institution,
        offer_type__type=TYPE_OFFRE_BENEVOLE, environment=environnement,
    ).prefetch_related("competences")

    par_utilisateur = {}
    offres = {}
    for offre in ressources:
        offres[offre.author_id] = offre.id
        par_utilisateur[offre.author_id] = sorted(
            ({"id": str(c.id), "nom": c.nom} for c in offre.competences.all()),
            key=lambda c: c["nom"].lower(),
        )
    return par_utilisateur, offres


def _ont_declare(offres_par_utilisateur, aujourdhui):
    """Qui a touché à sa grille de créneaux, à partir d'aujourd'hui.

    « Pas de ligne = indisponible » est la règle du moteur unique : une grille vierge et une
    grille entièrement décochée sont identiques en base. Ce drapeau est donc la seule chose qui
    distingue le silence du refus, et c'est lui qui dit qui relancer."""
    from .models import DisponibiliteOffre

    if not offres_par_utilisateur:
        return set()
    inverse = {offre_id: utilisateur_id
               for utilisateur_id, offre_id in offres_par_utilisateur.items()}
    declarants = set()
    for offre_id in DisponibiliteOffre.objects.filter(
            offer_id__in=inverse.keys(), date__gte=aujourdhui,
    ).values_list("offer_id", flat=True).distinct():
        utilisateur_id = inverse.get(offre_id)
        if utilisateur_id is not None:
            declarants.add(utilisateur_id)
    return declarants


def _titres_par_utilisateur(utilisateurs, environnement, aujourdhui):
    """Nombre de titres détenus, vérifiés et périmés, par personne.

    Trois compteurs et non un, parce qu'ils ne disent pas la même chose : un titre **déclaré**
    est une affirmation de son titulaire, un titre **périmé** vaut un titre absent le jour du
    départ. Les confondre ferait partir quelqu'un sur la foi d'une case qu'il a cochée lui-même
    il y a quatre ans."""
    from .models import QualificationMembre, StatutQualification

    compteurs = {}
    for utilisateur_id, statut, expiration in QualificationMembre.objects.filter(
            utilisateur_id__in=utilisateurs, environment=environnement,
    ).values_list("utilisateur_id", "statut", "date_expiration"):
        ligne = compteurs.setdefault(
            utilisateur_id, {"titres": 0, "titres_verifies": 0, "titres_perimes": 0})
        ligne["titres"] += 1
        if statut == StatutQualification.VERIFIEE:
            ligne["titres_verifies"] += 1
        if expiration is not None and expiration < aujourdhui:
            ligne["titres_perimes"] += 1
    return compteurs


def _roles_dans_les_equipes(institution):
    """Pour chaque personne, sa place dans chaque équipe de l'association.

    Rendu par `(équipe, utilisateur)` et calculé ici plutôt que côté navigateur : la même
    personne peut être cadre dans une équipe et simple intervenant dans une autre, et un rôle
    déduit d'une liste d'identifiants recopiée dans le navigateur finirait par diverger de ce
    que le serveur retient réellement.

    L'ordre des tests est l'ordre de préséance : on est d'abord chef d'équipe, puis régulateur,
    puis cadre, puis intervenant."""
    from .models import Team

    roles = {}
    equipes = Team.objects.filter(institution=institution, actif=True).prefetch_related(
        "members", "membres_encadrement")
    for equipe in equipes:
        encadrement = {m.id for m in equipe.membres_encadrement.all()}
        for membre in equipe.members.all():
            if equipe.leader_id == membre.id:
                role = "CHEF"
            elif equipe.regulateur_id == membre.id:
                role = "REGULATEUR"
            elif membre.id in encadrement:
                role = "CADRE"
            else:
                role = "INTERVENANT"
            roles.setdefault(str(equipe.id), {})[str(membre.id)] = role
    return roles


LIBELLES_ROLE_EQUIPE = {
    "CHEF": "Chef d'équipe",
    "REGULATEUR": "Régulateur",
    "CADRE": "Cadre",
    "INTERVENANT": "Intervenant",
}


def annuaire(institution, request):
    """L'effectif de l'association, enrichi de tout ce que l'arbre doit pouvoir montrer.

    Les membres SORTIS n'y figurent pas : sortir quelqu'un désactive son rattachement (règle
    tenue au modèle), et `actif=True` les écarte donc de lui-même. C'est voulu et cohérent avec
    la grille de disponibilités — on n'affecte pas un ancien. L'annuaire ordinaire
    (`/api/contacts-institutions/`) reste la vue qui montre qui était là.

    Renvoie `{"membres": [...], "coordonnees_visibles": bool, "roles_par_equipe": {...}}`.
    """
    from .models import ContactInstitution, FicheBenevole
    from .permissions import get_active_environment, nom_affichable

    environnement = get_active_environment(request)
    aujourdhui = timezone.localdate()
    complet = coordonnees_visibles(request.user, institution)

    rattachements = list(
        ContactInstitution.objects.filter(institution=institution, actif=True)
        .select_related("utilisateur")
    )
    utilisateurs = [c.utilisateur_id for c in rattachements]

    competences, offres = _competences_par_utilisateur(
        utilisateurs, institution, environnement)
    declarants = _ont_declare(offres, aujourdhui)
    titres = _titres_par_utilisateur(utilisateurs, environnement, aujourdhui)
    fiches = {
        f.utilisateur_id: f
        for f in FicheBenevole.objects.filter(
            utilisateur_id__in=utilisateurs, environment=environnement)
    }

    membres = []
    for contact in rattachements:
        compteurs = titres.get(contact.utilisateur_id,
                               {"titres": 0, "titres_verifies": 0, "titres_perimes": 0})
        fiche = fiches.get(contact.utilisateur_id)
        ligne = {
            "utilisateur": str(contact.utilisateur_id),
            "contact": str(contact.id),
            "nom": nom_affichable(contact.utilisateur, request)
                   or contact.utilisateur.email,
            "fonction": contact.fonction or "",
            "membre_bureau": bool(contact.membre_bureau),
            "statut": contact.statut,
            "competences": competences.get(contact.utilisateur_id, []),
            "a_declare": contact.utilisateur_id in declarants,
            "a_ressource": contact.utilisateur_id in offres,
            "a_fiche": fiche is not None,
            "fiche_complete": bool(fiche and fiche.est_complete),
            **compteurs,
        }
        if complet:
            # Les coordonnées, et elles seules, sont derrière ce test. Voir l'en-tête du
            # module : la page est ouverte à tout membre, pas seulement au bureau.
            ligne.update({
                "email": contact.utilisateur.email,
                "telephone": contact.utilisateur.phone_number or "",
                "ville": (fiche.ville if fiche else "") or "",
                "commune_code": (fiche.commune_code if fiche else None),
                "departement_code": (fiche.departement_code if fiche else None),
                "metier": (fiche.metier if fiche else "") or "",
                "aptitude_valide_jusquau": contact.aptitude_valide_jusquau,
                "adhesion_valide_jusquau": contact.adhesion_valide_jusquau,
            })
        membres.append(ligne)

    membres.sort(key=lambda m: (m["nom"] or "").lower())
    return {
        "institution": str(institution.id),
        "institution_nom": institution.nom,
        "membres": membres,
        "coordonnees_visibles": complet,
        "roles_par_equipe": _roles_dans_les_equipes(institution),
    }
