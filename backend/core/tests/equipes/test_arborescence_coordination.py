"""Arborescence de coordination territoriale, et les deux salons Matrix par équipe.

Demande du 11/11/2026 pour les Casques Jaunes (AASC nationale) : National → Zone de défense →
Régional → Départemental, chaque équipe portant deux salons Matrix — Encadrement et
Intervenants — dans lesquels les membres de l'équipe sont invités automatiquement.

Ce que ces tests verrouillent, et qui ne se devine pas à la lecture :

1. **Le salon ENCADREMENT d'une équipe contient aussi l'encadrement de ses équipes filles**, à
   toute profondeur. C'est ce qui rend l'arborescence utile : le salon d'une Coordination
   Régionale réunit l'encadrement régional ET les coordinateurs départementaux, au lieu
   d'exiger un salon par couple d'échelons. Conséquence assumée : un encadrant départemental
   apparaît dans quatre salons d'encadrement (le sien, sa région, sa zone, le national).
2. **Le salon INTERVENANTS contient toute l'équipe, encadrement compris** : un encadrant absent
   du salon de terrain de sa propre équipe ne voit pas ce qui s'y dit.
3. **Un encadrant doit être membre de l'équipe.** L'encadrement est une qualité au sein de
   l'équipe, pas une appartenance de plus — et le refus est explicite, pas un filtrage
   silencieux qui laisserait croire que la désignation a pris.
4. **`equipes_filles_recursives` ne boucle pas sur un cycle.** `equipe_parente` est libre et
   rien n'empêche en base qu'un cycle y soit introduit ; un parcours naïf tournerait
   indéfiniment dans le pont Matrix, en production.
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, EchelonEquipe, Institution, InstitutionType, SalonMatrixEquipe, Team,
    TypeSalonEquipe,
)
from core.serializers import SalonMatrixEquipeSerializer


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_ARBO',
                                                     defaults={'libelle': 'Association'})
    return Institution.objects.create(nom='Reserve Resilience Test', type=itype)


@pytest.fixture
def client_bureau(create_user, institution):
    user = create_user(username='bureau-arbo@test.fr', email='bureau-arbo@test.fr',
                       type='SECOURS', institution=institution)
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def arborescence(institution):
    """National → zone → région → département, le minimum pour éprouver la remontée."""
    national = Team.objects.create(
        name='Coordination Nationale', institution=institution,
        echelon=EchelonEquipe.NATIONAL, territoire_code='FR', territoire_libelle='France')
    zone = Team.objects.create(
        name='Coordination Zone de Défense Sud-Est', institution=institution,
        echelon=EchelonEquipe.ZONE_DEFENSE, territoire_code='ZD-SUD-EST',
        territoire_libelle='Sud-Est', equipe_parente=national)
    region = Team.objects.create(
        name='Coordination Régionale Auvergne-Rhône-Alpes', institution=institution,
        echelon=EchelonEquipe.REGIONAL, territoire_code='84',
        territoire_libelle='Auvergne-Rhône-Alpes', equipe_parente=zone)
    departement = Team.objects.create(
        name='Coordination Départementale Isère (38)', institution=institution,
        echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code='38',
        territoire_libelle='Isère', equipe_parente=region, departements=['38'])
    return national, zone, region, departement


def _membres(equipe, type_salon):
    salon = SalonMatrixEquipe.objects.create(equipe=equipe, type=type_salon)
    return {m['id'] for m in SalonMatrixEquipeSerializer(salon).data['membres']}


@pytest.mark.django_db
class TestArborescence:

    def test_les_echelons_se_trient_du_national_au_departemental(self, arborescence):
        """Le tri était l'objet de la demande du 28/10 restée en attente : « département →
        région → national »."""
        national, zone, region, departement = arborescence
        ordonnees = sorted([departement, national, region, zone], key=lambda e: e.rang_echelon)
        assert [e.echelon for e in ordonnees] == [
            EchelonEquipe.NATIONAL, EchelonEquipe.ZONE_DEFENSE,
            EchelonEquipe.REGIONAL, EchelonEquipe.DEPARTEMENTAL,
        ]

    def test_une_equipe_sans_echelon_vient_apres_et_ne_s_intercale_pas(self, institution,
                                                                       arborescence):
        national = arborescence[0]
        ordinaire = Team.objects.create(name='Équipe logistique', institution=institution)
        assert ordinaire.rang_echelon > national.rang_echelon
        assert ordinaire.rang_echelon > arborescence[3].rang_echelon

    def test_les_equipes_filles_sont_trouvees_a_toute_profondeur(self, arborescence):
        national, zone, region, departement = arborescence
        assert {e.id for e in national.equipes_filles_recursives()} == {
            zone.id, region.id, departement.id}
        assert {e.id for e in region.equipes_filles_recursives()} == {departement.id}
        assert departement.equipes_filles_recursives() == []

    def test_un_cycle_dans_l_arbre_ne_fait_pas_boucler_le_parcours(self, arborescence):
        """`equipe_parente` est libre : rien n'empêche en base qu'un cycle soit introduit à la
        main. Un parcours récursif naïf tournerait indéfiniment — dans le pont Matrix, en
        production."""
        national, zone, region, departement = arborescence
        national.equipe_parente = departement
        national.save(update_fields=['equipe_parente'])

        trouvees = national.equipes_filles_recursives()
        assert {e.id for e in trouvees} == {zone.id, region.id, departement.id}


@pytest.mark.django_db
class TestCompositionDesSalons:

    def test_le_salon_intervenants_contient_toute_l_equipe_encadrement_compris(
            self, arborescence, create_user):
        departement = arborescence[3]
        chef = create_user(username='chef-38@test.fr', email='chef-38@test.fr')
        benevole = create_user(username='benevole-38@test.fr', email='benevole-38@test.fr')
        departement.members.set([chef, benevole])
        departement.membres_encadrement.set([chef])

        assert _membres(departement, TypeSalonEquipe.INTERVENANTS) == {
            str(chef.id), str(benevole.id)}

    def test_le_salon_encadrement_ne_contient_que_l_encadrement(self, arborescence,
                                                                create_user):
        departement = arborescence[3]
        chef = create_user(username='chef2-38@test.fr', email='chef2-38@test.fr')
        benevole = create_user(username='benevole2-38@test.fr', email='benevole2-38@test.fr')
        departement.members.set([chef, benevole])
        departement.membres_encadrement.set([chef])

        assert _membres(departement, TypeSalonEquipe.ENCADREMENT) == {str(chef.id)}

    def test_le_salon_encadrement_remonte_celui_des_equipes_filles(self, arborescence,
                                                                   create_user):
        """La décision qui rend l'arborescence utile : la Coordination Régionale parle à ses
        coordinateurs départementaux dans SON salon d'encadrement."""
        national, zone, region, departement = arborescence
        chef_region = create_user(username='chef-region@test.fr', email='chef-region@test.fr')
        chef_dept = create_user(username='chef-dept@test.fr', email='chef-dept@test.fr')
        region.members.set([chef_region])
        region.membres_encadrement.set([chef_region])
        departement.members.set([chef_dept])
        departement.membres_encadrement.set([chef_dept])

        assert _membres(region, TypeSalonEquipe.ENCADREMENT) == {
            str(chef_region.id), str(chef_dept.id)}
        # Et jusqu'en haut : le national voit l'encadrement de tout le pays.
        assert _membres(national, TypeSalonEquipe.ENCADREMENT) == {
            str(chef_region.id), str(chef_dept.id)}

    def test_mais_le_salon_intervenants_ne_remonte_PAS(self, arborescence, create_user):
        """Sinon le salon « Intervenants » du national contiendrait tous les bénévoles de
        France, ce qui n'est pas un salon mais une liste de diffusion."""
        national, zone, region, departement = arborescence
        benevole = create_user(username='benevole-remonte@test.fr',
                               email='benevole-remonte@test.fr')
        departement.members.set([benevole])

        assert _membres(national, TypeSalonEquipe.INTERVENANTS) == set()

    def test_un_compte_desactive_n_est_dans_aucun_salon(self, arborescence, create_user):
        """Un compte désactivé ne doit plus rien lire : le pont l'expulserait au cycle suivant
        s'il restait dans la liste des cibles."""
        departement = arborescence[3]
        parti = create_user(username='parti@test.fr', email='parti@test.fr')
        departement.members.set([parti])
        departement.membres_encadrement.set([parti])
        parti.is_active = False
        parti.save(update_fields=['is_active'])

        assert _membres(departement, TypeSalonEquipe.INTERVENANTS) == set()
        assert _membres(departement, TypeSalonEquipe.ENCADREMENT) == set()


@pytest.mark.django_db
class TestCoutDeLaRemonteeEncadrement:
    """Le pont relit TOUS les salons toutes les 30 secondes.

    Le parcours de l'arbre par `Team.equipes_filles_recursives()` coûte une requête par niveau
    de profondeur ; appelé par salon, il coûterait des centaines de requêtes à chaque passage dès
    que l'arborescence complète a ses salons. `SalonMatrixEquipeSerializer` mémorise donc l'arbre
    entier en UNE requête pour toute la réponse — ce test est ce qui empêche quelqu'un de
    revenir à un `.filter()` par salon sans s'en apercevoir."""

    def test_le_cout_ne_croit_pas_avec_le_nombre_de_salons(self, institution, arborescence):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        national, zone, region, departement = arborescence
        # Un sous-arbre plus large, pour que la mémorisation ait quelque chose à économiser.
        for i in range(8):
            Team.objects.create(
                name=f'Coordination Départementale {i}', institution=institution,
                echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code=f'D{i}',
                equipe_parente=region)

        equipes = list(Team.objects.all())
        for equipe in equipes:
            SalonMatrixEquipe.objects.create(equipe=equipe,
                                             type=TypeSalonEquipe.ENCADREMENT)

        salons = list(SalonMatrixEquipe.objects.select_related('equipe').all())
        with CaptureQueriesContext(connection) as ctx:
            donnees = SalonMatrixEquipeSerializer(salons, many=True).data
            list(donnees)

        # Une requête d'arbre mémorisée + une requête de membres et une d'expulsion par salon.
        # Sans mémorisation, le parcours seul en ajouterait une par salon ET par niveau.
        assert len(ctx) <= 2 * len(salons) + 3, (
            f"{len(ctx)} requêtes pour {len(salons)} salons : l'arbre doit être lu une seule "
            "fois pour toute la réponse"
        )


@pytest.mark.django_db
class TestDefinirEncadrement:

    def test_le_bureau_designe_l_encadrement_de_son_equipe(self, client_bureau, arborescence,
                                                           create_user):
        client, _ = client_bureau
        departement = arborescence[3]
        chef = create_user(username='designe@test.fr', email='designe@test.fr')
        departement.members.set([chef])

        reponse = client.post(
            reverse('team-definir-encadrement', args=[departement.id]),
            {'membres_encadrement': [str(chef.id)]}, format='json',
        )
        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert set(departement.membres_encadrement.values_list('id', flat=True)) == {chef.id}

    def test_designer_quelqu_un_qui_n_est_pas_de_l_equipe_est_refuse(self, client_bureau,
                                                                     arborescence, create_user):
        """Refus explicite et non filtrage silencieux : ignorer l'identifiant ferait croire que
        l'encadrement a été posé."""
        client, _ = client_bureau
        departement = arborescence[3]
        etranger = create_user(username='etranger@test.fr', email='etranger@test.fr')

        reponse = client.post(
            reverse('team-definir-encadrement', args=[departement.id]),
            {'membres_encadrement': [str(etranger.id)]}, format='json',
        )
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert str(etranger.id) in reponse.data['hors_equipe']
        assert not departement.membres_encadrement.exists()

    def test_une_liste_vide_retire_tout_l_encadrement(self, client_bureau, arborescence,
                                                      create_user):
        """`set` plutôt qu'un ajout : l'appel est idempotent et retirer quelqu'un ne demande pas
        une action de retrait séparée."""
        client, _ = client_bureau
        departement = arborescence[3]
        chef = create_user(username='retire@test.fr', email='retire@test.fr')
        departement.members.set([chef])
        departement.membres_encadrement.set([chef])

        reponse = client.post(
            reverse('team-definir-encadrement', args=[departement.id]),
            {'membres_encadrement': []}, format='json',
        )
        assert reponse.status_code == status.HTTP_200_OK
        assert not departement.membres_encadrement.exists()

    def test_le_champ_manquant_est_refuse_et_ne_vide_pas_l_encadrement(self, client_bureau,
                                                                       arborescence, create_user):
        """Un corps vide ne doit pas être lu comme « retire tout » : la différence entre
        « je n'ai rien envoyé » et « je veux une liste vide » décide de qui lit un salon."""
        client, _ = client_bureau
        departement = arborescence[3]
        chef = create_user(username='garde@test.fr', email='garde@test.fr')
        departement.members.set([chef])
        departement.membres_encadrement.set([chef])

        reponse = client.post(
            reverse('team-definir-encadrement', args=[departement.id]), {}, format='json')
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert departement.membres_encadrement.count() == 1

    def test_un_compte_etranger_a_l_institution_ne_peut_pas_designer(self, create_user,
                                                                     arborescence):
        departement = arborescence[3]
        intrus = create_user(username='intrus-arbo@test.fr', email='intrus-arbo@test.fr',
                             type='AUT_LOCALE')
        client = APIClient()
        client.force_authenticate(user=intrus)

        reponse = client.post(
            reverse('team-definir-encadrement', args=[departement.id]),
            {'membres_encadrement': []}, format='json',
        )
        assert reponse.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestProvisionnementDesDeuxSalons:

    def test_provisionner_cree_les_deux_salons(self, client_bureau, arborescence):
        """Provisionner le seul salon général laisserait l'encadrement sans endroit pour se
        parler, et il faudrait un second geste que personne ne devinerait."""
        client, _ = client_bureau
        departement = arborescence[3]

        reponse = client.post(
            reverse('team-provisionner-salon-matrix', args=[departement.id]), {}, format='json')
        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert {s['type'] for s in reponse.data} == {'INTERVENANTS', 'ENCADREMENT'}

    def test_le_provisionnement_est_idempotent(self, client_bureau, arborescence):
        client, _ = client_bureau
        departement = arborescence[3]
        url = reverse('team-provisionner-salon-matrix', args=[departement.id])

        client.post(url, {}, format='json')
        client.post(url, {}, format='json')
        assert SalonMatrixEquipe.objects.filter(equipe=departement).count() == 2

    def test_une_equipe_ne_peut_pas_avoir_deux_salons_du_meme_type(self, arborescence):
        """Contrainte en base, et non seulement dans le code : un second salon du même type
        ferait deux conversations parallèles pour les mêmes personnes, et le pont en créerait
        deux côté Synapse."""
        from django.db import IntegrityError

        departement = arborescence[3]
        SalonMatrixEquipe.objects.create(equipe=departement,
                                         type=TypeSalonEquipe.INTERVENANTS)
        with pytest.raises(IntegrityError):
            SalonMatrixEquipe.objects.create(equipe=departement,
                                             type=TypeSalonEquipe.INTERVENANTS)
