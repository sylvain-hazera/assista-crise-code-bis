"""Qui voit quels comptes — correction d'un trou de cloisonnement (11/11/2026).

`UserViewSet` servait `User.objects.all()` à tout acteur institutionnel. Le filtre
`?institution=` existait mais était FACULTATIF, et huit écrans appelaient la liste sans lui :
une mairie quelconque voyait tous les comptes de la plateforme, bénévoles d'associations
compris.

Les quatre règles, de la plus large à la plus étroite, et le test qui garde chacune :

1. administrateur de la plateforme : tout ;
2. bureau d'une institution : tous ses membres ;
3. **encadrement d'une équipe : cette équipe et TOUTES celles en dessous** — c'est la
   hiérarchie au sens propre, et c'est ce que Sylvain a demandé ;
4. acteur institutionnel d'une institution SANS hiérarchie : ses collègues. Sans cette règle,
   cloisonner par hiérarchie ferait disparaître les collègues d'un agent de mairie.
"""
import pytest
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, EchelonEquipe, Institution, InstitutionType, Team, User,
)

URL = "/api/users/"


@pytest.fixture
def asso(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_VIS',
                                                     defaults={'libelle': 'Association'})
    return Institution.objects.create(nom="Association Visibilite", type=itype)


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(code='MAIRIE_VIS',
                                                     defaults={'libelle': 'Mairie'})
    return Institution.objects.create(nom="Mairie Visibilite", type=itype)


@pytest.fixture
def arbre(asso):
    """National → Région A → Dépt 33, et une branche sœur Région B → Dépt 74."""
    national = Team.objects.create(name="Nationale", institution=asso,
                                   echelon=EchelonEquipe.NATIONAL, territoire_code="FR")
    region_a = Team.objects.create(name="Region A", institution=asso,
                                   echelon=EchelonEquipe.REGIONAL, territoire_code="75",
                                   equipe_parente=national)
    dept_33 = Team.objects.create(name="Gironde", institution=asso,
                                  echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="33",
                                  equipe_parente=region_a)
    region_b = Team.objects.create(name="Region B", institution=asso,
                                   echelon=EchelonEquipe.REGIONAL, territoire_code="84",
                                   equipe_parente=national)
    dept_74 = Team.objects.create(name="Haute-Savoie", institution=asso,
                                  echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="74",
                                  equipe_parente=region_b)
    return national, region_a, dept_33, region_b, dept_74


def _membre(create_user, nom, institution, equipe=None, bureau=False, encadrant=False,
            type_compte='UTIL_SIMPLE'):
    u = create_user(username=f'{nom}@vis.test', email=f'{nom}@vis.test', type=type_compte)
    ContactInstitution.objects.create(institution=institution, utilisateur=u, actif=True,
                                      membre_bureau=bureau)
    if equipe is not None:
        equipe.members.add(u)
        if encadrant:
            equipe.membres_encadrement.add(u)
    return u


def _visibles(appelant):
    client = APIClient()
    client.force_authenticate(user=appelant)
    reponse = client.get(URL)
    assert reponse.status_code == 200, reponse.data
    # La vue n'est pas paginée par défaut (OptionalPageNumberPagination est opt-in) : on
    # accepte les deux formes pour que le test ne casse pas si la pagination est activée.
    donnees = reponse.data['results'] if isinstance(reponse.data, dict) else reponse.data
    return {str(l['id']) for l in donnees}


@pytest.mark.django_db
class TestCloisonnementHierarchique:

    def test_un_encadrant_departemental_voit_son_equipe(self, create_user, asso, arbre):
        _, _, dept_33, _, _ = arbre
        chef = _membre(create_user, 'chef33', asso, dept_33, encadrant=True,
                       type_compte='SECOURS')
        benevole = _membre(create_user, 'benevole33', asso, dept_33)

        assert str(benevole.id) in _visibles(chef)

    def test_un_encadrant_departemental_NE_voit_PAS_l_autre_departement(self, create_user,
                                                                        asso, arbre):
        """Le cœur de la demande : « visible seulement par leur hiérarchie »."""
        _, _, dept_33, _, dept_74 = arbre
        chef_33 = _membre(create_user, 'c33', asso, dept_33, encadrant=True,
                          type_compte='SECOURS')
        benevole_74 = _membre(create_user, 'b74', asso, dept_74)

        assert str(benevole_74.id) not in _visibles(chef_33)

    def test_l_encadrement_regional_voit_ses_departements(self, create_user, asso, arbre):
        _, region_a, dept_33, _, dept_74 = arbre
        chef_region = _membre(create_user, 'cregion', asso, region_a, encadrant=True,
                              type_compte='SECOURS')
        benevole_33 = _membre(create_user, 'b33r', asso, dept_33)
        benevole_74 = _membre(create_user, 'b74r', asso, dept_74)

        visibles = _visibles(chef_region)
        assert str(benevole_33.id) in visibles
        # Mais pas la branche sœur : la hiérarchie descend, elle ne traverse pas.
        assert str(benevole_74.id) not in visibles

    def test_le_national_voit_tout_le_monde(self, create_user, asso, arbre):
        national, _, dept_33, _, dept_74 = arbre
        chef_national = _membre(create_user, 'cnat', asso, national, encadrant=True,
                                type_compte='SECOURS')
        b33 = _membre(create_user, 'bn33', asso, dept_33)
        b74 = _membre(create_user, 'bn74', asso, dept_74)

        visibles = _visibles(chef_national)
        assert {str(b33.id), str(b74.id)} <= visibles

    def test_le_bureau_voit_tous_les_membres_de_son_institution(self, create_user, asso,
                                                                arbre):
        """Le bureau administre ses adhérents : lui cacher une partie de son propre fichier
        rendrait la page Membres inutilisable."""
        _, _, dept_33, _, dept_74 = arbre
        bureau = _membre(create_user, 'bureau', asso, bureau=True, type_compte='SECOURS')
        b33 = _membre(create_user, 'bb33', asso, dept_33)
        b74 = _membre(create_user, 'bb74', asso, dept_74)

        assert {str(b33.id), str(b74.id)} <= _visibles(bureau)


@pytest.mark.django_db
class TestCloisonnementEntreInstitutions:

    def test_une_mairie_ne_voit_PAS_les_benevoles_d_une_association(self, create_user, asso,
                                                                    mairie, arbre):
        """LE TROU CORRIGÉ. Avant, tout acteur institutionnel listait tous les comptes de la
        plateforme."""
        _, _, dept_33, _, _ = arbre
        agent = _membre(create_user, 'agent', mairie, type_compte='AUT_LOCALE')
        benevole = _membre(create_user, 'bcache', asso, dept_33)

        assert str(benevole.id) not in _visibles(agent)

    def test_un_agent_de_mairie_voit_toujours_ses_collegues(self, create_user, mairie):
        """Règle 4 : sans elle, cloisonner par hiérarchie ferait disparaître les collègues
        d'une institution qui n'a aucune équipe à échelon."""
        agent = _membre(create_user, 'agent2', mairie, type_compte='AUT_LOCALE')
        collegue = _membre(create_user, 'collegue', mairie, type_compte='AUT_LOCALE')

        assert str(collegue.id) in _visibles(agent)

    def test_chacun_se_voit_toujours_lui_meme(self, create_user, asso, arbre):
        """Se masquer à soi-même ne protège personne."""
        _, _, dept_33, _, _ = arbre
        benevole = _membre(create_user, 'moi', asso, dept_33, type_compte='SECOURS')
        assert str(benevole.id) in _visibles(benevole)

    def test_un_compte_sans_aucune_institution_n_est_plus_liste(self, create_user, mairie):
        """CONSÉQUENCE ASSUMÉE du cloisonnement, verrouillée ici pour que personne ne la
        découvre par surprise : un citoyen qui s'inscrit sans rattachement n'apparaît plus dans
        `/api/users/` pour un acteur institutionnel.

        Ce n'est pas une perte de capacité, parce que les trois chemins qui en avaient besoin
        ne passent pas par là :

        - les comptes **en attente de validation** : `pending_validations` construit son propre
          queryset, il n'est pas cloisonné ;
        - **valider ou refuser** un compte : actions de détail, hors du filtre (qui ne porte que
          sur `list` et `retrieve`) ;
        - les coordonnées d'un citoyen qui a déposé une **offre ou une demande** : portées par
          l'offre elle-même, avec son propre cloisonnement par zone.

        Ce qui disparaît, c'est l'annuaire global de tous les comptes de la plateforme — ce
        qu'on cherchait précisément à fermer."""
        agent = _membre(create_user, 'agent4', mairie, type_compte='AUT_LOCALE')
        citoyen = create_user(username='citoyen@vis.test', email='citoyen@vis.test',
                              type='UTIL_SIMPLE')

        assert str(citoyen.id) not in _visibles(agent)

    def test_l_administrateur_voit_tout(self, create_user, asso, mairie, arbre):
        _, _, dept_33, _, _ = arbre
        admin = create_user(username='admin-vis@test.fr', email='admin-vis@test.fr',
                            type='ADMIN')
        b = _membre(create_user, 'bvu', asso, dept_33)
        agent = _membre(create_user, 'avu', mairie, type_compte='AUT_LOCALE')

        assert {str(b.id), str(agent.id)} <= _visibles(admin)

    def test_la_fiche_individuelle_est_cloisonnee_aussi(self, create_user, asso, mairie,
                                                        arbre):
        """Restreindre la liste en laissant la fiche accessible par son identifiant ne
        cloisonnerait rien : l'identifiant se devine dans n'importe quelle réponse qui mentionne
        un utilisateur."""
        _, _, dept_33, _, _ = arbre
        agent = _membre(create_user, 'agent3', mairie, type_compte='AUT_LOCALE')
        benevole = _membre(create_user, 'bfiche', asso, dept_33)

        client = APIClient()
        client.force_authenticate(user=agent)
        assert client.get(f"{URL}{benevole.id}/").status_code == 404
