"""Verrouille les optimisations select_related/prefetch_related trouvées en creusant une
lenteur signalée sur /admin/dashboard — évite qu'un futur changement de serializer les
fasse regresser silencieusement en réintroduisant du N+1."""
import uuid

import pytest
from django.contrib.gis.geos import Point
from django.test.utils import CaptureQueriesContext
from django.db import connection

from core.models import (
    AffectationRoleOperationnel, Besoin, Crisis, Dossier, ImplicationInstitution, Information,
    InformationType, Institution, InstitutionType, MaterielCatalogue, MaterielPoint, Offer,
    OfferType, PointOperationnel, PointType, Request, RequestType, RoleOperationnel, Team,
    TypeImplication, User,
)
from core.serializers import (
    CrisisSerializer, DossierSerializer, InstitutionSerializer, PointOperationnelSerializer,
    TeamSerializer,
)
from core.views import (
    CrisisViewSet, DossierViewSet, InstitutionViewSet, OfferViewSet, PointOperationnelViewSet,
    RequestViewSet, TeamViewSet,
)


def _make_institution(nom, code):
    itype, _ = InstitutionType.objects.get_or_create(code=code, defaults={'libelle': 'Test'})
    return Institution.objects.create(nom=nom, type=itype)


def _query_count(queryset, serializer_class, n=5):
    with CaptureQueriesContext(connection) as ctx:
        objs = list(queryset.all()[:n])
        assert len(objs) == n, f"besoin de {n} objets pour un test de requêtes significatif, {len(objs)} trouvé(s)"
        data = serializer_class(objs, many=True).data
        list(data)
    return len(ctx)


@pytest.mark.django_db
class TestPointOperationnelQueryCount:

    def test_query_count_does_not_scale_with_object_count(self, point_type_fixture=None):
        institution = _make_institution('Mairie Perf A', 'PERF_A')
        team = Team.objects.create(name='Equipe Perf A', institution=institution)
        ptype = PointType.objects.create(code='PERF_TEST', libelle='Perf test', actif=True)
        for i in range(5):
            point = PointOperationnel.objects.create(nom=f'Point Perf {i}', type=ptype)
            point.equipes_gestion.add(team)

        count_5 = _query_count(PointOperationnelViewSet.queryset, PointOperationnelSerializer, n=5)

        for i in range(5, 10):
            point = PointOperationnel.objects.create(nom=f'Point Perf {i}', type=ptype)
            point.equipes_gestion.add(team)

        count_10 = _query_count(PointOperationnelViewSet.queryset, PointOperationnelSerializer, n=10)

        # Avant le fix : ~16 requêtes/objet (198 requêtes mesurées pour 12 points DEMO). Après :
        # ~2/objet marginal (personnes_presentes + civils_accueillis, deux .aggregate() par
        # point — légitimes, pas du N+1 à corriger), plus le reste en O(1) (select_related/
        # prefetch_related). Marge à 3/objet pour absorber ce coût légitime sans retomber dans
        # l'ancien comportement (qui aurait ajouté ~16 requêtes/objet supplémentaire).
        marginal = count_10 - count_5
        assert marginal <= 3 * 5, (
            f"{count_5} requêtes pour 5 points, {count_10} pour 10 (marginal {marginal} pour "
            "5 points en plus) : le coût par objet ne doit pas rester aussi élevé qu'avant le fix"
        )


@pytest.mark.django_db
class TestTeamQueryCount:

    def test_vehicules_count_does_not_query_per_team(self):
        """Mesure le coût MARGINAL, et non un total absolu.

        Il mesurait un total (« moins de 10 requêtes pour 5 équipes ») : ce seuil confondait le
        coût CONSTANT des préchargements — un `prefetch_related` vaut une requête, quel que soit
        le nombre d'équipes, et c'est précisément ce qui ÉVITE le N+1 — avec le coût par objet,
        seul en cause ici. Ajouter deux préchargements légitimes le faisait donc échouer
        (constaté le 11/11/2026 en ajoutant `salons_matrix` et `membres_encadrement`), ce qui
        poussait à gonfler le seuil et à perdre un peu plus de sens à chaque fois.

        Il compare désormais 5 équipes à 10, comme le fait déjà
        `test_salon_matrix_does_not_query_per_team` juste en dessous."""
        institution = _make_institution('Mairie Perf B', 'PERF_B')
        author = User.objects.create_user(
            username='perf-b-offreur@test.fr', email='perf-b-offreur@test.fr', type='UTIL_SIMPLE'
        )
        transport_type, _ = OfferType.objects.get_or_create(type='Transport', defaults={'description': ''})

        def equiper(indices):
            for i in indices:
                team = Team.objects.create(name=f'Equipe Perf B {i}', institution=institution)
                camion = Offer.objects.create(
                    title=f'Camion {i}', first_name_offer='O', last_name_offer='Ffreur',
                    email_offer=author.email, status='DISPONIBLE', offer_type=transport_type,
                    author=author,
                )
                team.assigned_offers.add(camion)

        equiper(range(5))
        requetes = TeamViewSet.queryset.filter(institution=institution)
        count_5 = _query_count(requetes, TeamSerializer, n=5)
        # Le résultat est bien calculé, et pas seulement compté : un sérialiseur qui rendrait 0
        # partout passerait n'importe quel budget de requêtes.
        assert all(
            t['vehicules_count'] == 1
            for t in TeamSerializer(list(requetes.all()[:5]), many=True).data
        )

        equiper(range(5, 10))
        count_10 = _query_count(requetes, TeamSerializer, n=10)

        # Avant le fix : get_vehicules_count faisait un .filter().count() par équipe, ignorant
        # le prefetch_related('assigned_offers') — une requête de plus par équipe, soit +5 ici.
        marginal = count_10 - count_5
        assert marginal <= 2 * 5, (
            f"{count_5} requêtes pour 5 équipes, {count_10} pour 10 (marginal {marginal}) : "
            "vehicules_count ne doit pas requêter une fois par équipe"
        )

    def test_salon_matrix_does_not_query_per_team(self):
        """salon_matrix_id/salon_matrix_room_id/salons_matrix (TeamSerializer) déréférencent la
        relation `salons_matrix` -- oubliée dans select_related lors de l'ajout de la
        fonctionnalité Matrix le 24/09 (contrairement à canal_meshcore/canal_meshtastic, ajoutés
        au même endroit pour la même raison), retrouvée en creusant une lenteur signalée sur la
        vue équipe.

        Le risque a AUGMENTÉ le 11/11/2026 : la relation est devenue un ForeignKey (deux salons
        par équipe) et le sérialiseur la parcourt trois fois. D'où le choix d'une boucle Python
        sur `salons_matrix.all()` dans `TeamSerializer._salon` plutôt que d'un `.filter()`, qui
        contournerait le préchargement et rejouerait une requête par équipe ET par type."""
        institution = _make_institution('Mairie Perf Matrix', 'PERF_MATRIX')
        for i in range(5):
            Team.objects.create(name=f'Equipe Perf Matrix {i}', institution=institution)

        count_5 = _query_count(TeamViewSet.queryset.filter(institution=institution), TeamSerializer, n=5)

        for i in range(5, 10):
            Team.objects.create(name=f'Equipe Perf Matrix {i}', institution=institution)

        count_10 = _query_count(TeamViewSet.queryset.filter(institution=institution), TeamSerializer, n=10)

        marginal = count_10 - count_5
        assert marginal <= 3 * 5, (
            f"{count_5} requêtes pour 5 équipes, {count_10} pour 10 (marginal {marginal}) : "
            "salons_matrix ne doit pas requêter une fois par équipe"
        )


@pytest.mark.django_db
class TestDossierQueryCount:

    def test_query_count_does_not_scale_with_object_count(self):
        institution = _make_institution('Mairie Perf C', 'PERF_C')
        crisis = Crisis.objects.create(name='Crise Perf C', location=Point(5.7, 45.2, srid=4326))
        request_type, _ = RequestType.objects.get_or_create(type='ZZ Perf Type', defaults={'description': ''})
        author = User.objects.create_user(
            username='perf-c@test.fr', email='perf-c@test.fr', type='UTIL_SIMPLE'
        )

        def make_dossier():
            demande = Request.objects.create(
                title='Demande perf', first_name_request='D', last_name_request='Emande',
                email_request=author.email, status='NON_TRAITEE', request_type=request_type,
                author=author, crisis=crisis,
            )
            return Dossier.objects.create(
                crise=crisis, demande=demande, numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
            )

        for _ in range(5):
            make_dossier()
        count_5 = _query_count(DossierViewSet.queryset, DossierSerializer, n=5)

        for _ in range(5):
            make_dossier()
        count_10 = _query_count(DossierViewSet.queryset, DossierSerializer, n=10)

        # Avant le fix : ~5 requêtes/objet (372 requêtes mesurées pour 76 dossiers DEMO) rien
        # que pour les FK non préchargées.
        assert count_10 < count_5 + 10, (
            f"{count_5} requêtes pour 5 dossiers, {count_10} pour 10 : "
            "le coût par objet ne doit pas rester aussi élevé qu'avant le fix"
        )


@pytest.mark.django_db
class TestCrisisHasResponsableActif:

    def test_does_not_query_per_crisis(self, create_user):
        institution = _make_institution('Mairie Perf D', 'PERF_D')
        responsable = create_user(username='perf-d-resp@test.fr', email='perf-d-resp@test.fr', type='AUT_LOCALE')
        for i in range(5):
            crisis = Crisis.objects.create(name=f'Crise Perf D {i}', location=Point(5.7, 45.2, srid=4326))
            ImplicationInstitution.objects.create(
                crise=crisis, institution=institution, responsable=responsable,
                type_implication=TypeImplication.ACTEUR, actif=True,
            )

        # Isolé de get_commune() (champ à part, appelle le reverse-géocodage DB-backed —
        # coût légitime et déjà couvert par test_geo_lookup_db_cache.py, hors sujet ici) en
        # n'exerçant que le champ has_responsable_actif directement.
        serializer = CrisisSerializer()
        with CaptureQueriesContext(connection) as ctx:
            crises = list(CrisisViewSet.queryset.filter(name__startswith='Crise Perf D'))
            results = [serializer.get_has_responsable_actif(c) for c in crises]
            assert all(results)

        # Avant le fix : get_has_responsable_actif faisait un .filter().exists() par crise,
        # ignorant le prefetch_related('implications') — une requête de plus par crise. Ici,
        # 2 requêtes fixes attendues (le SELECT des crises + le prefetch_related
        # ('implications')), jamais 2 + 1 par crise.
        assert len(ctx) <= 2, f"{len(ctx)} requêtes pour 5 crises : has_responsable_actif ne doit pas requêter par crise"


@pytest.mark.django_db
class TestInstitutionQueryCount:

    def test_type_is_select_related(self):
        for i in range(3):
            _make_institution(f'Mairie Perf E {i}', f'PERF_E_{i}')

        with CaptureQueriesContext(connection) as ctx:
            institutions = list(InstitutionViewSet.queryset.filter(nom__startswith='Mairie Perf E'))
            data = InstitutionSerializer(institutions, many=True).data
            list(data)

        # 1 requête (+ éventuellement le count de pagination) suffit avec select_related('type').
        assert len(ctx) <= 2, f"{len(ctx)} requêtes pour 3 institutions : type doit être select_related"
