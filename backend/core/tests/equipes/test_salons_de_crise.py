"""Un salon par crise, pour une équipe qui, elle, est permanente.

Deux règles posées le 16/11/2026 : « un salon par crise, et les messages hors crise ne suivent
pas », et « on doit pouvoir réutiliser des équipes permanentes ». C'est donc le salon, et non
l'équipe, qui est propre à la crise — et c'est le serveur qui choisit le bon."""
import pytest
from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core import matrix, salons_matrix
from core.models import Crisis, PointOperationnel, PointType, SalonMatrixEquipe, Team, TypeSalonEquipe
from core.salons_de_crise import crise_du_contexte, salon_intervenants
from core.serializers import SalonMatrixEquipeSerializer, TeamSerializer


def _crise(nom):
    return Crisis.objects.create(name=nom, type="INONDATION", location=Point(4.51, 45.47, srid=4326))


@pytest.fixture
def equipe(db):
    return Team.objects.create(name="Logistique")


@pytest.fixture
def cadre(create_user):
    user = create_user(username="cadre-salon@test.fr", email="cadre-salon@test.fr", type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def matrix_muet(monkeypatch):
    """Matrix simulé : on retient dans quel salon on lit et on écrit."""
    vus = {"lus": [], "ecrits": []}
    monkeypatch.setattr(matrix, "assurer_membre_salon", lambda *a, **k: None)
    monkeypatch.setattr(matrix, "lister_messages_salon", lambda room_id, *a, **k: vus["lus"].append(room_id) or [])
    monkeypatch.setattr(matrix, "envoyer_message_salon", lambda room_id, *a, **k: vus["ecrits"].append(room_id))
    return vus


@pytest.mark.django_db
class TestQuelSalon:
    def test_hors_crise_lequipe_parle_dans_son_salon_de_tous_les_jours(self, equipe):
        assert crise_du_contexte(equipe) is None
        assert salon_intervenants(equipe, None, "PROD").crise_id is None

    def test_engagee_dans_une_crise_ouverte_elle_parle_dans_le_salon_de_cette_crise(self, equipe):
        quotidien = salon_intervenants(equipe, None, "PROD")
        crue = _crise("Crue du Gier")
        equipe.assigned_crises.add(crue)

        salon = salon_intervenants(equipe, crise_du_contexte(equipe), "PROD")

        assert salon.crise == crue and salon.pk != quotidien.pk

    def test_a_la_cloture_elle_retrouve_son_salon_habituel_et_celui_de_la_crise_reste(self, equipe):
        quotidien = salon_intervenants(equipe, None, "PROD")
        crue = _crise("Crue du Gier")
        equipe.assigned_crises.add(crue)
        de_crise = salon_intervenants(equipe, crise_du_contexte(equipe), "PROD")

        crue.end_date = timezone.now()
        crue.save(update_fields=["end_date"])

        assert crise_du_contexte(equipe) is None
        assert salon_intervenants(equipe, crise_du_contexte(equipe), "PROD").pk == quotidien.pk
        assert SalonMatrixEquipe.objects.filter(pk=de_crise.pk).exists()   # l'archive de la crise

    def test_deux_crises_ouvertes_la_crise_nommee_lemporte_sinon_la_plus_recente(self, equipe):
        crue, tempete = _crise("Crue du Gier"), _crise("Tempête")
        equipe.assigned_crises.add(crue, tempete)

        assert crise_du_contexte(equipe) == tempete
        assert crise_du_contexte(equipe, str(crue.id)) == crue
        # Une crise où l'équipe n'est pas engagée, ou un identifiant fantaisiste, ne détourne rien.
        assert crise_du_contexte(equipe, str(_crise("Ailleurs").id)) == tempete
        assert crise_du_contexte(equipe, "nimporte-quoi") == tempete

    def test_une_equipe_engagee_par_un_point_de_la_crise_compte_aussi(self, equipe):
        crue = _crise("Crue du Gier")
        accueil = PointType.objects.get_or_create(code="HEBERGEMENT", defaults={"libelle": "Hébergement"})[0]
        PointOperationnel.objects.create(nom="Gymnase", type=accueil, crise=crue, equipe=equipe)

        assert crise_du_contexte(equipe) == crue

    def test_la_cellule_de_crise_na_pas_de_variante_elle_est_deja_propre_a_la_crise(self, db):
        crue = _crise("Crue du Gier")
        cellule = Team.objects.create(name="Cellule de crise — Crue du Gier")
        type_cellule = PointType.objects.get_or_create(code="CELLULE_CRISE", defaults={"libelle": "Cellule de crise"})[0]
        PointOperationnel.objects.create(nom="Mairie", type=type_cellule, crise=crue, equipe=cellule)
        cellule.assigned_crises.add(crue)

        assert crise_du_contexte(cellule, str(crue.id)) is None


@pytest.mark.django_db
class TestMessagerie:
    def test_lapplication_tombe_dans_le_salon_de_la_crise_sans_rien_demander(self, equipe, cadre, matrix_muet):
        """L'application mobile et la page de l'équipe ne savent rien des crises : c'est le
        serveur qui les met dans le bon salon, sinon la cellule écrirait à une équipe qui lit
        ailleurs."""
        SalonMatrixEquipe.objects.create(equipe=equipe, room_id="!quotidien:test")
        crue = _crise("Crue du Gier")
        equipe.assigned_crises.add(crue)
        SalonMatrixEquipe.objects.create(equipe=equipe, crise=crue, room_id="!crue:test")
        url = reverse("team-messagerie-unifiee", args=[equipe.id])

        assert cadre.get(url).status_code == 200
        assert cadre.post(url, {"texte": "Pont coupé"}, format="json").status_code == 200

        assert set(matrix_muet["lus"]) == {"!crue:test"} and matrix_muet["ecrits"] == ["!crue:test"]

    def test_le_salon_de_crise_nait_a_la_premiere_discussion(self, equipe, cadre, matrix_muet):
        crue = _crise("Crue du Gier")
        equipe.assigned_crises.add(crue)
        assert not SalonMatrixEquipe.objects.filter(equipe=equipe, crise=crue).exists()

        reponse = cadre.get(reverse("team-messagerie-unifiee", args=[equipe.id]), {"crise": str(crue.id)})

        assert reponse.status_code == 200
        assert SalonMatrixEquipe.objects.filter(equipe=equipe, crise=crue, type=TypeSalonEquipe.INTERVENANTS).count() == 1

    def test_hors_crise_rien_ne_change(self, equipe, cadre, matrix_muet):
        SalonMatrixEquipe.objects.create(equipe=equipe, room_id="!quotidien:test")

        cadre.post(reverse("team-messagerie-unifiee", args=[equipe.id]), {"texte": "Réunion jeudi"}, format="json")

        assert matrix_muet["ecrits"] == ["!quotidien:test"]
        assert SalonMatrixEquipe.objects.filter(equipe=equipe).count() == 1


@pytest.mark.django_db
class TestLeResteNeCassePas:
    def test_les_creations_de_salons_de_tous_les_jours_supportent_un_salon_de_crise(self, equipe, create_user, cadre):
        """Le défaut qui a fait une erreur 500 en production le 16/11/2026 : un get_or_create
        sans critère trouvait deux salons. Avec un salon par crise, il en trouverait autant
        que de crises."""
        membre = create_user(username="membre-salon@test.fr", email="membre-salon@test.fr", type="UTIL_SIMPLE")
        equipe.members.add(membre)
        crue = _crise("Crue du Gier")
        SalonMatrixEquipe.objects.create(equipe=equipe, crise=crue)

        salons_matrix.assurer_salons_equipe(equipe)
        salons_matrix.assurer_salons_equipe(equipe)
        matrix.provisionner_salons_equipe(equipe, "PROD")

        assert SalonMatrixEquipe.objects.filter(equipe=equipe, crise__isnull=True).count() == 2
        assert SalonMatrixEquipe.objects.filter(equipe=equipe, crise=crue).count() == 1

    def test_un_seul_salon_par_equipe_par_type_et_par_crise(self, equipe):
        crue = _crise("Crue du Gier")
        SalonMatrixEquipe.objects.create(equipe=equipe)
        SalonMatrixEquipe.objects.create(equipe=equipe, crise=crue)

        for doublon in ({}, {"crise": crue}):
            with pytest.raises(IntegrityError), transaction.atomic():
                SalonMatrixEquipe.objects.create(equipe=equipe, **doublon)

    def test_le_pont_recoit_un_nom_qui_distingue_le_salon_de_la_crise(self, equipe):
        crue = _crise("Crue du Gier")
        quotidien = SalonMatrixEquipe.objects.create(equipe=equipe)
        de_crise = SalonMatrixEquipe.objects.create(equipe=equipe, crise=crue)

        assert SalonMatrixEquipeSerializer(quotidien).data["equipe_nom"] == "Logistique"
        assert SalonMatrixEquipeSerializer(de_crise).data["equipe_nom"] == "Logistique — Crue du Gier"

    def test_le_salon_de_lequipe_reste_celui_de_tous_les_jours_sur_sa_fiche(self, equipe):
        crue = _crise("Crue du Gier")
        de_crise = SalonMatrixEquipe.objects.create(equipe=equipe, crise=crue, room_id="!crue:test")
        quotidien = SalonMatrixEquipe.objects.create(equipe=equipe, room_id="!quotidien:test")

        fiche = TeamSerializer(Team.objects.prefetch_related("salons_matrix").get(pk=equipe.pk)).data

        assert fiche["salon_matrix_id"] == str(quotidien.id) and fiche["salon_matrix_room_id"] == "!quotidien:test"
        libelles = [s["type_libelle"] for s in fiche["salons_matrix"]]
        assert libelles[-1].endswith("— Crue du Gier") and str(de_crise.id) in [s["id"] for s in fiche["salons_matrix"]]
