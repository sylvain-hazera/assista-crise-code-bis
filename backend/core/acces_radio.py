"""Qui a le droit de faire quoi dans le domaine radio — source unique.

Trois endroits posaient la question séparément avant le 10/11/2026 : le menu Angular (tout
acteur institutionnel voyait les pages radio), les gardes de route (idem) et
`TacheAdminMeshtasticViewSet` (toute écriture exigeait le rôle ADMINISTRATOR réel). Résultat :
une commune sans aucune radio voyait huit pages qui ne pouvaient rien lui dire, et le bénévole
qui porte un nœud ne pouvait pas régler son propre matériel.

Ce module tranche les deux questions, et rien d'autre :

1. **« Ai-je accès au domaine radio, et à quel niveau ? »** → `niveau_acces_radio`.
2. **« Puis-je écrire sur CE nœud ? »** → `peut_administrer_noeud`.

La seconde est une question de **périmètre**, pas de grade (précision du 10/11/2026) : le droit
d'écrire suit la **propriété du matériel**. Un particulier répond de ses nœuds. Une institution
répond des nœuds de ses membres et des passerelles qu'elle a déployées — passerelle comprise,
car c'est elle qui est allée la poser et qui ira la rechercher. Personne ne répond du matériel
d'un autre, sauf l'administrateur de la plateforme.

Le niveau se calcule sur les seules données de la zone PROD. La zone de démonstration ne
contient aucun matériel réel : un nœud de démonstration n'ouvre aucun droit, et une tâche
d'administration créée en DEMO n'aurait de toute façon pas d'exécutant
(TacheAdminMeshtasticViewSet.perform_create).
"""

from django.db.models import Q

from .models import (
    CompagnonMeshCore,
    CompagnonMeshtastic,
    ContactInstitution,
    DemandeAccesRadio,
    Environment,
    Institution,
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


def passerelles_de_mes_institutions(user, ids=None):
    """Passerelles rattachées aux institutions du compte, les deux protocoles.

    Une passerelle dont le champ `institution` est vide n'appartient à personne au sens de ce
    module : elle est au central, et « quelqu'un, quelque part, a une passerelle » n'est pas un
    titre à administrer un réseau. Conséquence à connaître en exploitation : renseigner
    l'institution des companions existants est ce qui donne à une collectivité la main sur son
    propre matériel. À défaut, le droit s'accorde nominativement (DemandeAccesRadio)."""
    ids = institutions_de(user) if ids is None else ids
    if not ids:
        return (CompagnonMeshtastic.objects.none(), CompagnonMeshCore.objects.none())
    return (
        CompagnonMeshtastic.objects.filter(
            institution_id__in=ids, actif=True, environment=Environment.PROD,
        ),
        CompagnonMeshCore.objects.filter(
            institution_id__in=ids, actif=True, environment=Environment.PROD,
        ),
    )


def noeuds_de_mes_institutions(user, ids=None):
    """Nœuds personnels portés par les MEMBRES des institutions du compte.

    C'est la règle posée le 10/11/2026 : **une institution a les droits sur ses nœuds.** Le nœud
    d'un agent n'est pas sa propriété privée quand il lui a été remis par sa collectivité, et
    l'agent qui part en congés ne doit pas emporter avec lui la possibilité de le reconfigurer.

    Le rattachement se lit par les deux chemins qui existent (`User.institution` et les
    `ContactInstitution` actifs), comme `institutions_de` pour le compte lui-même."""
    ids = institutions_de(user) if ids is None else ids
    if not ids:
        return NoeudUtilisateurMeshtastic.objects.none()
    return NoeudUtilisateurMeshtastic.objects.filter(
        actif=True, environment=Environment.PROD,
    ).filter(
        Q(utilisateur__institution_id__in=ids)
        | Q(utilisateur__institutions__institution_id__in=ids,
            utilisateur__institutions__actif=True)
    ).distinct()


def _institution_possede_du_materiel(user):
    """Une institution du compte exploite-t-elle de la radio ? Passerelle OU nœud d'un membre.

    Le nœud compte autant que la passerelle : une commune dont trois agents portent un nœud
    *a* un réseau radio, même si elle n'a pas encore posé de passerelle, et elle doit pouvoir
    le voir et le régler."""
    ids = institutions_de(user)
    if not ids:
        return False
    meshtastic, meshcore = passerelles_de_mes_institutions(user, ids)
    return (
        meshtastic.exists()
        or meshcore.exists()
        or noeuds_de_mes_institutions(user, ids).exists()
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

    if _possede_un_noeud(user) or _institution_possede_du_materiel(user):
        return NiveauAccesRadio.OPERATEUR
    return accorde


def a_acces_radio(user):
    return niveau_acces_radio(user) != NiveauAccesRadio.AUCUN


def peut_administrer_noeud(user, node_num_cible, compagnon=None):
    """« Ce compte peut-il ÉCRIRE sur ce nœud ? »

    Trois périmètres, et un seul principe : **on répond du matériel dont on est responsable.**

    1. `ADMINISTRATEUR` écrit partout. C'est le recours quand une institution a perdu la main
       sur son propre matériel, ou quand le companion n'a pas d'institution renseignée.
    2. Un nœud personnel du compte : son porteur le règle.
    3. Le matériel d'une institution du compte — nœud d'un membre, ou passerelle déployée par
       elle. **La passerelle comprise** (règle du 10/11/2026) : c'est l'institution qui est
       allée la poser, c'est elle qui ira la rechercher si elle devient muette, et faire
       dépendre son réglage d'un administrateur de plateforme n'ajoute aucune sécurité — il
       ignore où elle est.

    `node_num_cible` vide désigne **la passerelle qui exécutera la tâche** : le droit se lit
    alors sur `compagnon.institution`, et non sur un node_num. Sans `compagnon`, la réponse est
    non : une écriture sur « la passerelle » sans savoir laquelle n'est pas vérifiable.

    Rappel de ce que l'erreur coûte, qui est la raison pour laquelle ce périmètre est étroit :
    une région ou un rapport cyclique faux rend un nœud muet, et **le nœud qui n'émet plus ne
    peut plus recevoir l'ordre inverse** — il faut aller le chercher à la main, souvent sur un
    point haut."""
    niveau = niveau_acces_radio(user)
    if niveau == NiveauAccesRadio.ADMINISTRATEUR:
        return True
    if niveau == NiveauAccesRadio.AUCUN:
        return False

    ids = institutions_de(user)

    if node_num_cible is None:
        # La passerelle elle-même : seule l'institution qui l'a déployée en répond.
        institution_id = getattr(compagnon, 'institution_id', None)
        return bool(institution_id and institution_id in ids)

    meshtastic, _ = noeuds_personnels(user)
    if meshtastic.filter(node_num=node_num_cible).exists():
        return True

    if not ids:
        return False
    if noeuds_de_mes_institutions(user, ids).filter(node_num=node_num_cible).exists():
        return True
    # Une passerelle visée par son node_num, et non comme exécutante de la tâche : même droit.
    passerelles, _ = passerelles_de_mes_institutions(user, ids)
    return passerelles.filter(node_num=node_num_cible).exists()


def etat_acces_radio(user):
    """Ce que la page /admin/radio doit pouvoir dire sans deviner : le niveau, ce qui l'ouvre,
    sur quoi il porte, et où en est une éventuelle demande.

    `motifs` est la liste des titres effectivement constatés, en clair. Sans elle, un compte à
    qui l'accès est refusé n'a aucun moyen de savoir ce qui lui manque -- et un compte qui l'a
    ne sait pas à quel titre, donc ne sait pas ce qu'il perdrait en désactivant son nœud.

    `perimetre_ecriture` dit sur QUOI il peut écrire, en toutes lettres. Cette liste est
    construite ici et non dans l'interface : la règle de périmètre est déjà difficile à tenir à
    un endroit, la recopier dans un second langage garantirait qu'elle divergerait -- et une
    interface qui promet une écriture que le serveur refuse se découvre par un 403."""
    niveau = niveau_acces_radio(user)
    motifs = []
    perimetre = []

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

    ids = institutions_de(user)
    passerelles_mt, passerelles_mc = passerelles_de_mes_institutions(user, ids)
    nombre_passerelles = passerelles_mt.count() + passerelles_mc.count()
    noeuds_institution = noeuds_de_mes_institutions(user, ids)
    nombre_noeuds_institution = noeuds_institution.count()
    noms_institutions = list(
        Institution.objects.filter(id__in=ids, actif=True).values_list('nom', flat=True)
    ) if ids else []

    if nombre_passerelles:
        motifs.append(
            f"Votre institution exploite {nombre_passerelles} passerelle active."
            if nombre_passerelles == 1
            else f"Votre institution exploite {nombre_passerelles} passerelles actives."
        )
    if nombre_noeuds_institution:
        motifs.append(
            f"{nombre_noeuds_institution} nœud rattaché aux membres de votre institution."
            if nombre_noeuds_institution == 1
            else f"{nombre_noeuds_institution} nœuds rattachés aux membres de votre institution."
        )

    accorde = _niveau_accorde(user)
    if accorde != NiveauAccesRadio.AUCUN:
        motifs.append(f"Droit accordé nominativement : {NiveauAccesRadio(accorde).label}.")

    if niveau == NiveauAccesRadio.ADMINISTRATEUR:
        perimetre.append(
            "N'importe quel nœud du réseau, passerelles comprises — y compris celles d'une "
            "institution qui aurait perdu la main sur son propre matériel."
        )
    elif niveau == NiveauAccesRadio.OPERATEUR:
        if nombre_noeuds:
            perimetre.append("Vos propres nœuds.")
        if noms_institutions and (nombre_passerelles or nombre_noeuds_institution):
            portee = "Les nœuds et les passerelles de " + ", ".join(sorted(noms_institutions)) + "."
            perimetre.append(portee)
            perimetre.append(
                "Une passerelle est de la responsabilité de l'institution qui l'a déployée : "
                "c'est elle qui ira la rechercher si un réglage la rend muette."
            )
        if not perimetre:
            # Niveau accordé nominativement, sans matériel identifié : rien à écrire, et il
            # vaut mieux le dire que de le laisser découvrir par un 403.
            perimetre.append(
                "Aucun matériel ne vous est rattaché pour l'instant : vous pouvez tout lire et "
                "simuler, mais aucune écriture n'aboutira avant qu'un nœud ou une passerelle "
                "ne vous soit rattaché."
            )

    derniere = (
        DemandeAccesRadio.objects.filter(utilisateur=user)
        .order_by('-date_demande')
        .first()
    )
    return {
        "niveau": niveau,
        "niveau_libelle": NiveauAccesRadio(niveau).label,
        "motifs": motifs,
        "perimetre_ecriture": perimetre,
        "nombre_noeuds_personnels": nombre_noeuds,
        "nombre_noeuds_institution": nombre_noeuds_institution,
        "nombre_passerelles_institution": nombre_passerelles,
        "demande": derniere,
    }
