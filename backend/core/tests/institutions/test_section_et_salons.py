"""Le bénévole arrive quelque part, et l'équipe naît avec ses salons.

Trois demandes de Sylvain du 13/11/2026, qui partagent la même idée : **ce qui est évident au
moment de la création ne doit pas demander un second geste.**

1. *« Un rattachement du bénévole par défaut à la section départementale de son département de
   résidence. »* Quelqu'un rattaché à rien n'est dans aucun salon, ne reçoit aucune campagne
   ciblée par territoire et n'apparaît sur aucune grille : il a adhéré pour rien.
2. *« La création automatique des canaux en même temps que la création de l'équipe, avec
   l'inscription des bénévoles dans les canaux leur correspondant lorsqu'ils rejoignent une
   équipe. »* Une équipe sans salon n'a aucun moyen de se parler.
3. *« Un canal où seuls les membres du bureau peuvent écrire mais qui est diffusé à l'ensemble
   des bénévoles. »* Une consigne de politesse ne tient pas en situation : c'est au salon de
   garantir le silence, pas aux gens.
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, EchelonEquipe, Institution, InstitutionType, SalonMatrixEquipe,
    SalonMatrixInstitution, Team, TypeSalonEquipe, TypeSalonInstitution, UserRole,
)


@pytest.fixture
def association(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "Association"})
    return Institution.objects.create(nom="AASC Sections", type=itype)


@pytest.fixture
def section_38(association):
    return Team.objects.create(
        name="Section Isère", institution=association, environment="PROD",
        echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="38")


@pytest.fixture
def section_73(association):
    return Team.objects.create(
        name="Section Savoie", institution=association, environment="PROD",
        echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="73")


def _membre(create_user, association, nom, bureau=False, role=UserRole.ORGANIZED_RESCUE):
    user = create_user(username=f"{nom}@test.fr", email=f"{nom}@test.fr", type=role)
    ContactInstitution.objects.create(institution=association, utilisateur=user, actif=True,
                                      membre_bureau=bureau)
    return user


def _fiche(utilisateur, departement):
    from core.models import FicheBenevole

    return FicheBenevole.objects.create(
        utilisateur=utilisateur, environment="PROD", departement_code=departement)


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestLaSectionDepartementale:
    def test_le_benevole_rejoint_la_section_de_son_departement(
            self, create_user, association, section_38, section_73):
        from core.rattachement_departemental import rattacher

        personne = _membre(create_user, association, "isere1")
        _fiche(personne, "38")

        equipe = rattacher(personne)

        assert equipe == section_38
        assert personne in section_38.members.all()
        assert personne not in section_73.members.all()

    def test_sans_section_dans_son_departement_rien_n_est_invente(
            self, create_user, association, section_38):
        """Beaucoup d'associations n'ont aucune équipe départementale : on ne va pas en créer
        une, la personne reste dans l'équipe de tête."""
        from core.rattachement_departemental import rattacher

        personne = _membre(create_user, association, "ailleurs1")
        _fiche(personne, "75")

        assert rattacher(personne) is None

    def test_sans_adresse_geocodee_on_ne_devine_pas(self, create_user, association,
                                                    section_38):
        from core.rattachement_departemental import rattacher

        personne = _membre(create_user, association, "sansadresse1")

        assert rattacher(personne) is None

    def test_un_demenagement_retire_de_l_ancienne_section(
            self, create_user, association, section_38, section_73):
        """Rester mobilisable à 700 km et figurer dans deux salons départementaux serait pire
        que ne pas être rattaché du tout."""
        from core.rattachement_departemental import rattacher

        personne = _membre(create_user, association, "demenage1")
        fiche = _fiche(personne, "38")
        rattacher(personne)

        fiche.departement_code = "73"
        fiche.save()
        rattacher(personne, retirer_les_autres=True)

        assert personne in section_73.members.all()
        assert personne not in section_38.members.all()

    def test_une_simple_adhesion_ne_retire_de_rien(self, create_user, association,
                                                   section_38, section_73):
        """Quelqu'un peut légitimement appartenir à la section d'une autre association."""
        from core.rattachement_departemental import rattacher

        personne = _membre(create_user, association, "deuxasso1")
        _fiche(personne, "38")
        section_73.members.add(personne)

        rattacher(personne)

        assert personne in section_38.members.all()
        assert personne in section_73.members.all()

    def test_le_rattachement_est_idempotent(self, create_user, association, section_38):
        from core.rattachement_departemental import rattacher

        personne = _membre(create_user, association, "idem1")
        _fiche(personne, "38")

        assert rattacher(personne) == section_38
        assert rattacher(personne) == section_38
        assert section_38.members.filter(pk=personne.pk).count() == 1


class TestLesSalonsNaissentAvecLEquipe:
    def test_creer_une_equipe_cree_ses_deux_salons(self, create_user, association):
        acteur = _membre(create_user, association, "chef1", role=UserRole.ORGANIZED_RESCUE)

        reponse = _client(acteur).post(reverse("team-list"), {
            "name": "Équipe avec salons", "institution": str(association.id)}, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        equipe = Team.objects.get(name="Équipe avec salons")
        types = set(SalonMatrixEquipe.objects.filter(equipe=equipe)
                    .values_list("type", flat=True))
        assert types == {TypeSalonEquipe.INTERVENANTS, TypeSalonEquipe.ENCADREMENT}

    def test_le_salon_reste_a_provisionner_cote_synapse(self, create_user, association):
        """`room_id` vide : c'est le pont qui crée le salon, puis y inscrit les membres **en
        continu** — ce qui règle du même coup l'inscription de ceux qui rejoindront demain."""
        acteur = _membre(create_user, association, "chef2")

        _client(acteur).post(reverse("team-list"), {
            "name": "Équipe à provisionner", "institution": str(association.id)},
            format="json")

        salon = SalonMatrixEquipe.objects.get(
            equipe__name="Équipe à provisionner", type=TypeSalonEquipe.INTERVENANTS)
        assert not salon.room_id

    def test_provisionner_a_la_main_reste_sans_effet(self, create_user, association):
        """Idempotence : l'action manuelle existait avant, elle ne doit pas créer de doublon."""
        from core.matrix import provisionner_salons_equipe

        acteur = _membre(create_user, association, "chef3")
        reponse = _client(acteur).post(reverse("team-list"), {
            "name": "Équipe idempotente", "institution": str(association.id)}, format="json")
        equipe = Team.objects.get(pk=reponse.data["id"])

        provisionner_salons_equipe(equipe, "PROD")

        assert SalonMatrixEquipe.objects.filter(equipe=equipe).count() == 2


class TestLeSalonDAnnonces:
    def _salons(self, association, acteur):
        return _client(acteur).post(
            reverse("institution-provisionner-salons-matrix", args=[association.id]))

    def test_l_institution_a_un_salon_d_annonces(self, create_user, association):
        acteur = _membre(create_user, association, "bureau1", bureau=True,
                         role=UserRole.ORGANIZED_RESCUE)

        reponse = self._salons(association, acteur)

        assert reponse.status_code == status.HTTP_200_OK
        assert SalonMatrixInstitution.objects.filter(
            institution=association, type=TypeSalonInstitution.ANNONCES).exists()

    def test_il_touche_aussi_ceux_que_rien_ne_mobilise(self, create_user, association):
        """La différence avec « Bénévoles mobilisés » : une convocation d'assemblée générale
        ne s'adresse pas qu'à ceux qui sont déjà engagés."""
        from core.serializers import SalonMatrixInstitutionSerializer

        acteur = _membre(create_user, association, "bureau2", bureau=True)
        dormant = _membre(create_user, association, "dormant1")
        self._salons(association, acteur)

        salon = SalonMatrixInstitution.objects.get(
            institution=association, type=TypeSalonInstitution.ANNONCES)
        membres = SalonMatrixInstitutionSerializer(salon).data["membres"]

        assert str(dormant.id) in {m["id"] for m in membres}

    def test_seul_le_bureau_y_est_redacteur(self, create_user, association):
        from core.matrix import matrix_user_id
        from core.serializers import SalonMatrixInstitutionSerializer

        acteur = _membre(create_user, association, "bureau3", bureau=True)
        simple = _membre(create_user, association, "simple1")
        self._salons(association, acteur)

        salon = SalonMatrixInstitution.objects.get(
            institution=association, type=TypeSalonInstitution.ANNONCES)
        donnees = SalonMatrixInstitutionSerializer(salon).data

        assert donnees["lecture_seule"] is True
        assert matrix_user_id(acteur) in donnees["redacteurs"]
        assert matrix_user_id(simple) not in donnees["redacteurs"]

    def test_un_salon_ordinaire_n_est_pas_en_lecture_seule(self, create_user, association):
        """La diffusion ne remplace pas la conversation, elle la décharge."""
        from core.serializers import SalonMatrixInstitutionSerializer

        acteur = _membre(create_user, association, "bureau4", bureau=True)
        self._salons(association, acteur)

        salon = SalonMatrixInstitution.objects.get(
            institution=association, type=TypeSalonInstitution.BENEVOLES)
        donnees = SalonMatrixInstitutionSerializer(salon).data

        assert donnees["lecture_seule"] is False
        assert donnees["redacteurs"] == []

    def test_un_simple_membre_ne_peut_pas_publier_une_annonce(self, create_user,
                                                              association):
        """Le contrôle est répété côté web parce que le relais écrit avec le compte du bot,
        qui est administrateur du salon : sans ce garde-fou, l'interface contournerait la
        restriction posée dans Matrix."""
        acteur = _membre(create_user, association, "bureau5", bureau=True)
        simple = _membre(create_user, association, "simple2")
        self._salons(association, acteur)
        salon = SalonMatrixInstitution.objects.get(
            institution=association, type=TypeSalonInstitution.ANNONCES)
        salon.room_id = "!faux:matrix.test"
        salon.save()

        reponse = _client(simple).post(
            reverse("institution-salon-matrix-messages",
                    args=[association.id, "ANNONCES"]),
            {"texte": "coucou"}, format="json")

        assert reponse.status_code == status.HTTP_403_FORBIDDEN
        assert "bureau" in reponse.data["error"].lower()
