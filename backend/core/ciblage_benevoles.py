"""Sélection en masse de bénévoles sur critères, pour une campagne de disponibilité.

Demande de Sylvain du 11/11/2026 : « La sélection doit pouvoir se faire en masse sur critères
connus : compétences, permis, à jour, X km de la crise / département / région / ZDD /
national. »

**Rien n'est inventé ici.** Les critères tombent sur des données qui existaient déjà, et c'est
ce qui rend ce module court :

| Critère | D'où il vient |
|---|---|
| compétences | `Offer.competences`, porté par la RESSOURCE du bénévole |
| permis, diplômes | `QualificationMembre.qualification` |
| « à jour » | `QualificationMembre.statut` + `date_expiration`, et `ContactInstitution.aptitude_valide_jusquau` |
| territoire | les codes dénormalisés de la ressource (`commune_code` … `region_code`) |
| zone de défense | `core/zones_defense.py`, qui donne ses départements |
| rayon autour de la crise | PostGIS, `Distance` sur `Crisis.location` |
| branche de l'arborescence | `Team.equipe_parente`, descendu par `visibilite_membres` |

**La sélection tourne sur la ressource** (l'offre « Bénévolat » interne) et non sur `User` : la
ressource porte les compétences, le point géocodé et le secteur. Un bénévole sans ressource
n'est pas sélectionnable — et c'est juste : il n'a pas de fiche, donc on ne sait ni où il est ni
ce qu'il sait faire.

**Un critère que l'on ne peut pas appliquer est une ERREUR, jamais un silence.** Demander « à
30 km de la crise » sans crise rattachée, ou « zone de défense ZD-INCONNUE », ne doit pas
renvoyer tout le monde : on écrirait à 400 personnes en croyant en viser 30.
"""
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db.models import Count, Q
from django.utils import timezone


class CritereInapplicable(Exception):
    """Un critère demandé ne peut pas être appliqué (donnée manquante, code inconnu).

    Levée plutôt qu'ignorée : un filtre silencieusement sans effet élargit la cible au lieu de
    la restreindre, et personne ne s'en aperçoit avant que le message soit parti."""


def ressources_de_l_institution(institution, environnement):
    """Les ressources « Bénévolat » internes de cette institution, membres actifs seulement.

    Un membre sorti ou en congé n'est pas mobilisable : le sollicliter serait au mieux inutile,
    au pire blessant pour quelqu'un en arrêt."""
    from .fiches_benevoles import TYPE_OFFRE_BENEVOLE
    from .models import ContactInstitution, Offer, VisibiliteOffre

    actifs = ContactInstitution.objects.filter(
        institution=institution, actif=True,
        statut=ContactInstitution.StatutMembre.ACTIF,
    ).values_list("utilisateur_id", flat=True)

    return Offer.objects.filter(
        institution=institution,
        visibilite=VisibiliteOffre.INTERNE,
        offer_type__type=TYPE_OFFRE_BENEVOLE,
        environment=environnement,
        actif=True,
        author_id__in=actifs,
    ).select_related("author")


def _filtre_territoire(queryset, echelon, territoire_code, crise, rayon_km):
    """Applique l'étendue géographique. Voir `EchelonCiblage`."""
    from .models import EchelonCiblage

    if echelon == EchelonCiblage.NATIONAL:
        return queryset

    if echelon == EchelonCiblage.RAYON_CRISE:
        if crise is None or crise.location is None:
            raise CritereInapplicable(
                "Un ciblage par rayon demande une crise rattachée et localisée."
            )
        if not rayon_km:
            raise CritereInapplicable("Un ciblage par rayon demande une distance en km.")
        return queryset.annotate(
            distance_crise=Distance("location", crise.location),
        ).filter(distance_crise__lte=D(km=rayon_km))

    if not territoire_code:
        raise CritereInapplicable(
            f"Un ciblage « {echelon} » demande le code du territoire visé."
        )

    if echelon == EchelonCiblage.COMMUNE:
        return queryset.filter(commune_code=territoire_code)
    if echelon == EchelonCiblage.DEPARTEMENT:
        return queryset.filter(departement_code=territoire_code)
    if echelon == EchelonCiblage.REGION:
        return queryset.filter(region_code=territoire_code)

    if echelon == EchelonCiblage.ZONE_DEFENSE:
        from .zones_defense import departements_de_zone

        # `departements_de_zone` rend des COUPLES `(code, libellé)` et non des codes : les
        # passer tels quels à un `__in` ne lève pas, ne filtre rien et rend zéro ligne. Piège
        # rencontré en écrivant ce module, et attrapé par un test — c'est exactement le genre
        # de filtre muet contre lequel `CritereInapplicable` existe, à ceci près qu'ici il
        # restreint à néant au lieu d'élargir.
        departements = [code for code, _libelle in departements_de_zone(territoire_code)]
        if not departements:
            # Un code de zone inconnu rendrait un filtre vide, donc personne — ou, si on
            # l'ignorait, tout le monde. Les deux sont faux : on le dit.
            raise CritereInapplicable(
                f"Zone de défense inconnue : « {territoire_code} »."
            )
        return queryset.filter(departement_code__in=departements)

    raise CritereInapplicable(f"Échelon de ciblage inconnu : « {echelon} ».")


def _filtre_equipe(queryset, equipe):
    """Limite à une branche de l'arborescence : l'équipe et toutes celles en dessous.

    C'est ce qui permet à un coordinateur départemental de solliciter son département sans
    écrire à la France entière."""
    from .models import Team
    from .visibilite_membres import _equipes_descendantes

    if equipe is None:
        return queryset
    ids = _equipes_descendantes([equipe.id])
    membres = Team.objects.filter(id__in=ids).values_list("members__id", flat=True)
    return queryset.filter(author_id__in=[m for m in membres if m])


def _filtre_competences(queryset, competences):
    """AU MOINS UNE des compétences demandées.

    « Ou » et non « et », délibérément : demander « électricien ET infirmier » ne décrit
    personne, alors que « électricien OU infirmier » décrit exactement ce qu'on cherche quand on
    arme un centre d'accueil. Les titres exigés, eux, se cumulent (voir plus bas) — un permis C
    n'est pas interchangeable avec un PSE1."""
    if not competences:
        return queryset
    return queryset.filter(competences__in=competences).distinct()


def _filtre_qualifications(queryset, qualifications, a_jour, environnement):
    """TOUS les titres demandés, et « à jour » si demandé.

    Le cumul se vérifie par un compte et non par des `filter()` enchaînés : deux `filter()` sur
    la même relation inverse se satisfont de DEUX lignes différentes, donc quelqu'un qui a le
    permis deux fois passerait pour quelqu'un qui a le permis et le PSE1. Erreur classique de
    l'ORM, et ici elle enverrait des gens sur le terrain sans le titre requis."""
    from .models import QualificationMembre, StatutQualification

    if not qualifications:
        return queryset

    ids = [q.id for q in qualifications]
    aujourdhui = timezone.localdate()

    titres = QualificationMembre.objects.filter(
        qualification_id__in=ids, environment=environnement,
    )
    if a_jour:
        titres = titres.filter(
            statut=StatutQualification.VERIFIEE,
        ).filter(
            # Sans échéance = sans péremption : un titre permanent est à jour par nature.
            Q(date_expiration__isnull=True) | Q(date_expiration__gte=aujourdhui)
        )

    porteurs = (
        titres.values("utilisateur_id")
        .annotate(combien=Count("qualification_id", distinct=True))
        .filter(combien=len(set(ids)))
        .values_list("utilisateur_id", flat=True)
    )
    return queryset.filter(author_id__in=list(porteurs))


def _filtre_aptitude(queryset, institution, a_jour):
    """Aptitude médicale échue = pas de terrain. Appliqué seulement avec « à jour »."""
    from .models import ContactInstitution

    if not a_jour:
        return queryset
    aujourdhui = timezone.localdate()
    aptes = ContactInstitution.objects.filter(
        institution=institution, actif=True,
    ).filter(
        Q(aptitude_valide_jusquau__isnull=True) | Q(aptitude_valide_jusquau__gte=aujourdhui)
    ).values_list("utilisateur_id", flat=True)
    return queryset.filter(author_id__in=list(aptes))


def cibler(institution, environnement, *, echelon, territoire_code="", crise=None,
           rayon_km=None, competences=None, qualifications=None, titres_a_jour=True,
           equipe=None):
    """Les ressources retenues par ces critères. Renvoie un queryset d'`Offer`.

    Un queryset et non une liste : l'écran a besoin du COMPTE avant l'envoi (« 87 bénévoles
    retenus »), et compter 400 lignes en mémoire pour en afficher un nombre serait du
    gaspillage. L'appelant matérialise quand il veut la liste.
    """
    queryset = ressources_de_l_institution(institution, environnement)
    queryset = _filtre_territoire(queryset, echelon, territoire_code, crise, rayon_km)
    queryset = _filtre_equipe(queryset, equipe)
    queryset = _filtre_competences(queryset, competences)
    queryset = _filtre_qualifications(queryset, qualifications, titres_a_jour, environnement)
    queryset = _filtre_aptitude(queryset, institution, titres_a_jour)
    return queryset


def cibler_pour_campagne(campagne):
    """Applique les critères FIGÉS d'une campagne."""
    return cibler(
        campagne.institution, campagne.environment,
        echelon=campagne.echelon,
        territoire_code=campagne.territoire_code,
        crise=campagne.crise,
        rayon_km=campagne.rayon_km,
        competences=list(campagne.competences.all()),
        qualifications=list(campagne.qualifications.all()),
        titres_a_jour=campagne.titres_a_jour,
        equipe=campagne.equipe,
    )
