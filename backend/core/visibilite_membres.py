"""Qui peut voir quels comptes dans les listes d'utilisateurs.

**Corrige un trou constaté le 11/11/2026** : `UserViewSet` servait `User.objects.all()` à tout
acteur institutionnel. Le filtre `?institution=` existait mais était facultatif, et huit écrans
appelaient la liste sans lui — une mairie quelconque voyait donc tous les comptes de la
plateforme, bénévoles d'associations compris.

Quatre règles, de la plus large à la plus étroite :

1. **Administrateur de la plateforme** : tout. C'est lui qui débloque une institution dont le
   bureau a perdu ses accès, et la page Utilisateurs lui est réservée.
2. **Bureau d'une institution** : tous ses membres. Le bureau administre ses adhérents — lui
   cacher une partie de son propre fichier rendrait la page Membres inutilisable.
3. **Encadrement d'une équipe** : les membres de cette équipe et de **toutes celles en
   dessous**. C'est la hiérarchie au sens propre : un coordinateur régional voit ses
   départements, le national voit tout le monde, un coordinateur de Gironde ne voit pas la
   Haute-Savoie.
4. **Acteur institutionnel sans hiérarchie** (le cas d'une mairie) : les membres de ses
   institutions. Sans cette règle, cloisonner par hiérarchie ferait disparaître les collègues
   d'un agent de mairie, dont l'institution n'a aucune équipe à échelon.

Et dans tous les cas : **son propre compte**. Se masquer à soi-même ne protège personne.

La descente de l'arbre est faite en Python sur une seule requête : `equipe_parente` est libre,
un arbre national fait 125 équipes, et une requête récursive par appel coûterait plus cher que
de le parcourir en mémoire. Ensemble des vus pour qu'un cycle introduit à la main ne fasse pas
boucler.
"""
from django.db.models import Q


def _equipes_descendantes(ids_racines):
    """Les équipes données et toutes celles en dessous, à toute profondeur.

    Une seule requête pour tout l'arbre, puis parcours en mémoire. Ensemble des vus :
    `equipe_parente` n'empêche pas un cycle en base, et un parcours naïf tournerait
    indéfiniment."""
    from .models import Team

    if not ids_racines:
        return set()

    enfants = {}
    for enfant_id, parent_id in Team.objects.exclude(equipe_parente_id=None).values_list(
        'id', 'equipe_parente_id'
    ):
        enfants.setdefault(parent_id, []).append(enfant_id)

    vus = set(ids_racines)
    a_voir = list(ids_racines)
    while a_voir:
        courant = a_voir.pop()
        for enfant in enfants.get(courant, ()):
            if enfant not in vus:
                vus.add(enfant)
                a_voir.append(enfant)
    return vus


def filtre_utilisateurs_visibles(utilisateur, est_administrateur=False):
    """Un `Q` à appliquer sur `User`, ou None quand tout est visible (administrateur).

    Rendre un `Q` plutôt qu'un queryset : l'appelant compose avec ses propres filtres
    (`?institution=`, recherche) sans qu'on ait à les connaître ici."""
    from .models import ContactInstitution, Team

    if est_administrateur:
        return None

    # Toujours soi-même, quelles que soient les autres règles.
    visible = Q(pk=utilisateur.pk)

    rattachements = list(
        ContactInstitution.objects.filter(utilisateur=utilisateur, actif=True)
        .values_list('institution_id', 'membre_bureau')
    )
    institutions_bureau = {i for i, bureau in rattachements if bureau}
    institutions_membre = {i for i, _ in rattachements}

    # Règle 2 : le bureau voit tous les membres de son institution.
    if institutions_bureau:
        visible |= Q(institutions__institution_id__in=institutions_bureau,
                     institutions__actif=True)

    # Règle 3 : l'encadrement voit son équipe et tout ce qui est en dessous.
    equipes_encadrees = list(
        Team.objects.filter(membres_encadrement=utilisateur).values_list('id', flat=True)
    )
    if equipes_encadrees:
        visible |= Q(teams__id__in=_equipes_descendantes(equipes_encadrees))

    # Règle 4 : dans une institution SANS hiérarchie, on voit ses collègues. Appliquée aux
    # seules institutions concernées : l'ajouter partout annulerait le cloisonnement
    # hiérarchique qu'on vient de poser.
    institutions_sans_hierarchie = {
        i for i in institutions_membre - institutions_bureau
        if not Team.objects.filter(institution_id=i).exclude(echelon='').exists()
    }
    if institutions_sans_hierarchie:
        visible |= Q(institutions__institution_id__in=institutions_sans_hierarchie,
                     institutions__actif=True)

    return visible
