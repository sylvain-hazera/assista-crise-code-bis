"""Qui a le droit de faire quoi dans le domaine radio — source unique.

Trois endroits posaient la question séparément avant le 10/11/2026 : le menu Angular (tout
acteur institutionnel voyait les pages radio), les gardes de route (idem) et
`TacheAdminMeshtasticViewSet` (toute écriture exigeait le rôle ADMINISTRATOR réel). Résultat :
une commune sans aucune radio voyait huit pages qui ne pouvaient rien lui dire, et le bénévole
qui porte un nœud ne pouvait pas régler son propre matériel.

Ce module tranche les deux questions, et rien d'autre :

1. **« Ai-je accès au domaine radio, et à quel niveau ? »** → `niveau_acces_radio`.
2. **« Puis-je écrire sur CE nœud ? »** → `peut_administrer_noeud`.

Le niveau se calcule sur les seules données de la zone PROD. La zone de démonstration ne
contient aucun matériel réel : un nœud de démonstration n'ouvre aucun droit, et une tâche
d'administration créée en DEMO n'aurait de toute façon pas d'exécutant
(TacheAdminMeshtasticViewSet.perform_create).
"""

from .models import (
    CompagnonMeshCore,
    CompagnonMeshtastic,
    ContactInstitution,
    DemandeAccesRadio,
    Environment,
    NiveauAccesRadio,
    NoeudMeshUtilisateur,
    NoeudUtilisateurMeshtastic,
    StatutDemandeAccesRadio,
    UserRole,
)

# Ordre croissant des niveaux, pour comparer sans écrire trois `or` à chaque appel.
_RANG = {
    NiveauAccesRadio.AUCUN: 0,
    NiveauAccesRadio.OPERATEUR: 1,
    NiveauAccesRadio.ADMINISTRATEUR: 2,
}


def institutions_de(user):
    """Institutions auxquelles ce compte est rattaché, par les deux chemins qui existent.

    `User.institution` est le rattachement principal (posé à l'inscription) ; les
    `ContactInstitution` actifs sont les rattachements multiples. Les deux comptent : un agent
    peut exploiter la passerelle d'une collectivité où il n'est inscrit que comme contact."""
    ids = set()
    principale = getattr(user, 'institution_id', None)
    if principale:
        ids.add(principale)
    ids.update(
        ContactInstitution.objects.filter(utilisateur=user, actif=True)
        .values_list('institution_id', flat=True)
    )
    return ids


def noeuds_personnels(user):
    """Nœuds personnels actifs du compte, les deux protocoles confondus (node_num Meshtastic,
    clé publique MeshCore). Renvoie un couple de QuerySets, jamais évalué ici."""
    meshtastic = NoeudUtilisateurMeshtastic.objects.filter(
        utilisateur=user, actif=True, environment=Environment.PROD,
    )
    meshcore = NoeudMeshUtilisateur.objects.filter(
        utilisateur=user, actif=True, environment=Environment.PROD,
    )
    return meshtastic, meshcore


def _possede_un_noeud(user):
    meshtastic, meshcore = noeuds_personnels(user)
    return meshtastic.exists() or meshcore.exists()


def _institution_possede_une_passerelle(user):
    """Une passerelle *rattachée à l'institution* du compte.

    Une passerelle dont le champ `institution` est vide n'ouvre aucun droit, volontairement :
    elle appartient alors au central, et « quelqu'un, quelque part, a une passerelle » n'est pas
    un titre à administrer un réseau. Conséquence à connaître en exploitation : renseigner
    l'institution des companions existants est ce qui rend le menu radio visible aux agents de
    cette collectivité. À défaut, le droit s'accorde nominativement (DemandeAccesRadio)."""
    ids = institutions_de(user)
    if not ids:
        return False
    return (
        CompagnonMeshtastic.objects.filter(
            institution_id__in=ids, actif=True, environment=Environment.PROD,
        ).exists()
        or CompagnonMeshCore.objects.filter(
            institution_id__in=ids, actif=True, environment=Environment.PROD,
        ).exists()
    )


def _niveau_accorde(user):
    """Plus haut niveau effectivement accordé par une demande instruite."""
    niveaux = DemandeAccesRadio.objects.filter(
        utilisateur=user, statut=StatutDemandeAccesRadio.ACCORDEE,
    ).values_list('niveau_accorde', flat=True)
    meilleur = NiveauAccesRadio.AUCUN
    for niveau in niveaux:
        if niveau and _RANG.get(niveau, 0) > _RANG[meilleur]:
            meilleur = niveau
    return meilleur


def niveau_acces_radio(user):
    """Niveau d'accès radio d'un compte (voir NiveauAccesRadio pour ce que chacun ouvre).

    Le rôle ADMINISTRATOR est pris au sens **réel** et non effectif, comme pour les secrets
    radio (permissions.EstComptePont) et la supervision technique : un `demo_role=ADMIN` prêté
    le temps d'une démonstration ne doit pas donner la main sur du matériel qui émet."""
    if not (user and getattr(user, 'is_authenticated', False)):
        return NiveauAccesRadio.AUCUN
    if user.type == UserRole.ADMINISTRATOR:
        return NiveauAccesRadio.ADMINISTRATEUR

    accorde = _niveau_accorde(user)
    if accorde == NiveauAccesRadio.ADMINISTRATEUR:
        return NiveauAccesRadio.ADMINISTRATEUR

    if _possede_un_noeud(user) or _institution_possede_une_passerelle(user):
        return NiveauAccesRadio.OPERATEUR
    return accorde


def a_acces_radio(user):
    return niveau_acces_radio(user) != NiveauAccesRadio.AUCUN


def peut_administrer_noeud(user, node_num_cible):
    """« Ce compte peut-il ÉCRIRE sur ce nœud ? »

    `node_num_cible` vide désigne la passerelle elle-même : réservée au niveau
    ADMINISTRATEUR. Ce n'est pas une précaution de principe. Une passerelle est l'infrastructure
    de tout un réseau, une région ou un rapport cyclique faux la rend muette, et le nœud qui
    n'émet plus ne peut plus recevoir l'ordre inverse -- il faut aller le chercher à la main.

    Pour un nœud nommé, le niveau OPERATEUR suffit s'il s'agit d'un nœud personnel du compte.
    On compare sur `node_num` et non sur l'identité du porteur : c'est l'appareil que le
    firmware autorise, et c'est l'appareil que son propriétaire a le droit de régler."""
    niveau = niveau_acces_radio(user)
    if niveau == NiveauAccesRadio.ADMINISTRATEUR:
        return True
    if niveau == NiveauAccesRadio.AUCUN or node_num_cible is None:
        return False
    meshtastic, _ = noeuds_personnels(user)
    return meshtastic.filter(node_num=node_num_cible).exists()


def etat_acces_radio(user):
    """Ce que la page /admin/radio doit pouvoir dire sans deviner : le niveau, ce qui l'ouvre,
    et où en est une éventuelle demande.

    `motifs` est la liste des titres effectivement constatés, en clair. Sans elle, un compte à
    qui l'accès est refusé n'a aucun moyen de savoir ce qui lui manque -- et un compte qui l'a
    ne sait pas à quel titre, donc ne sait pas ce qu'il perdrait en désactivant son nœud."""
    niveau = niveau_acces_radio(user)
    motifs = []
    if user.type == UserRole.ADMINISTRATOR:
        motifs.append("Administrateur de la plateforme.")

    meshtastic, meshcore = noeuds_personnels(user)
    nombre_noeuds = meshtastic.count() + meshcore.count()
    if nombre_noeuds:
        motifs.append(
            f"{nombre_noeuds} nœud personnel actif rattaché à ce compte."
            if nombre_noeuds == 1
            else f"{nombre_noeuds} nœuds personnels actifs rattachés à ce compte."
        )
    if _institution_possede_une_passerelle(user):
        motifs.append("Votre institution exploite au moins une passerelle radio active.")

    accorde = _niveau_accorde(user)
    if accorde != NiveauAccesRadio.AUCUN:
        motifs.append(f"Droit accordé nominativement : {NiveauAccesRadio(accorde).label}.")

    derniere = (
        DemandeAccesRadio.objects.filter(utilisateur=user)
        .order_by('-date_demande')
        .first()
    )
    return {
        "niveau": niveau,
        "niveau_libelle": NiveauAccesRadio(niveau).label,
        "motifs": motifs,
        "nombre_noeuds_personnels": nombre_noeuds,
        "demande": derniere,
    }
