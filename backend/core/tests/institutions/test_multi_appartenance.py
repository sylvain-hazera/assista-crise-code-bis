"""Une personne, plusieurs institutions : une mairie ET une association.

Avertissement de Sylvain du 13/11/2026 : *« attention, un utilisateur peut être membre de
plusieurs institutions. Une mairie et une asso. »* — et, dans le même échange, *« fais gaffe,
car à terme je pourrais avoir des milliers d'institutions. »*

Deux questions à ne jamais confondre, et c'est tout l'objet de ces tests :

- **« De qui est-il membre ? »** → `ContactInstitution`, une table de liaison : autant de
  lignes que d'appartenances. C'est la vérité.
- **« Pour qui travaille-t-il en ce moment ? »** → `User.institution`, un champ unique. C'est
  un **contexte**, qui pilote le périmètre territorial.

Lire le second pour répondre à la première donne une réponse fausse dès qu'une personne a deux
appartenances — et laquelle des deux dépendrait de l'ordre de ses inscriptions.
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.institution_courante import (
    definir_institution_active, est_membre, institution_courante, institutions_de,
)
from core.models import ContactInstitution, Institution, InstitutionType, UserRole


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie de Saint-Étienne", type=itype,
                                      commune_code="42218")


@pytest.fixture
def association(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "Association"})
    return Institution.objects.create(nom="Casques Jaunes Loire", type=itype)


@pytest.fixture
def polyvalent(create_user, mairie, association):
    """Agent de la mairie ET adhérent de l'association. Le cas courant, pas l'exception."""
    user = create_user(username="polyvalent@test.fr", email="polyvalent@test.fr",
                       type=UserRole.LOCAL_AUTHORITY)
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    ContactInstitution.objects.create(institution=association, utilisateur=user, actif=True)
    return user


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestLAppartenanceEstUneListe:
    def test_une_personne_peut_etre_dans_deux_institutions(self, polyvalent, mairie,
                                                           association):
        noms = {i.nom for i in institutions_de(polyvalent)}

        assert noms == {mairie.nom, association.nom}

    def test_la_contrainte_n_interdit_pas_la_multi_appartenance(self, polyvalent, mairie,
                                                                association):
        """La contrainte porte sur (institution, utilisateur) : deux institutions
        DIFFÉRENTES font deux paires différentes. C'est la confusion qu'il fallait écarter."""
        assert ContactInstitution.objects.filter(utilisateur=polyvalent).count() == 2

    def test_le_meme_rattachement_deux_fois_est_refuse(self, polyvalent, mairie):
        """Un doublon fausse tout comptage d'effectif et fait apparaître la personne deux
        fois dans un annuaire. Il y en avait 4 en production."""
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ContactInstitution.objects.create(
                    institution=mairie, utilisateur=polyvalent, actif=True)

    def test_est_membre_repond_pour_les_deux(self, polyvalent, mairie, association):
        """La seule façon correcte de répondre : `User.institution` dirait « non » pour la
        seconde institution."""
        assert est_membre(polyvalent, mairie.id) is True
        assert est_membre(polyvalent, association.id) is True

    def test_un_rattachement_desactive_n_est_plus_une_appartenance(self, polyvalent,
                                                                   association):
        ContactInstitution.objects.filter(
            utilisateur=polyvalent, institution=association).update(actif=False)

        assert est_membre(polyvalent, association.id) is False
        assert [i.id for i in institutions_de(polyvalent)] != []


class TestLeContexteDeTravail:
    def test_on_peut_basculer_entre_ses_institutions(self, polyvalent, mairie, association):
        polyvalent.institution = mairie
        polyvalent.save()

        institution, erreur = definir_institution_active(polyvalent, association.id)

        assert erreur is None
        polyvalent.refresh_from_db()
        assert polyvalent.institution_id == association.id

    def test_on_ne_bascule_pas_sur_une_institution_dont_on_n_est_pas_membre(
            self, create_user, mairie, association):
        """Ce champ décide d'un périmètre territorial : sans ce contrôle, n'importe qui
        s'attribuerait la zone de n'importe quelle institution."""
        etranger = create_user(username="etranger@test.fr", email="etranger@test.fr",
                               type=UserRole.LOCAL_AUTHORITY)

        institution, erreur = definir_institution_active(etranger, mairie.id)

        assert institution is None
        assert "pas membre" in erreur
        etranger.refresh_from_db()
        assert etranger.institution_id is None

    def test_l_api_liste_mes_institutions_et_bascule(self, polyvalent, mairie, association):
        client = _client(polyvalent)

        etat = client.get(reverse("institution_active"))
        assert len(etat.data["institutions"]) == 2

        reponse = client.post(reverse("institution_active"),
                              {"institution": str(association.id)}, format="json")
        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["active"] == str(association.id)

    def test_l_api_refuse_une_institution_etrangere(self, create_user, mairie):
        etranger = create_user(username="etranger2@test.fr", email="etranger2@test.fr",
                               type=UserRole.LOCAL_AUTHORITY)

        reponse = _client(etranger).post(reverse("institution_active"),
                                         {"institution": str(mairie.id)}, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST

    def test_une_seule_appartenance_sert_de_repli(self, create_user, mairie):
        """Un compte rattaché une seule fois n'a aucune raison d'être aveugle à sa commune
        parce qu'un chemin de création ancien a oublié de poser le raccourci."""
        simple = create_user(username="simple@test.fr", email="simple@test.fr",
                             type=UserRole.LOCAL_AUTHORITY)
        ContactInstitution.objects.create(institution=mairie, utilisateur=simple, actif=True)
        simple.institution = None
        simple.save()

        assert institution_courante(simple) == mairie

    def test_avec_plusieurs_appartenances_on_ne_devine_pas(self, polyvalent):
        """Choisir à la place de quelqu'un son périmètre territorial serait pire que de lui
        demander."""
        polyvalent.institution = None
        polyvalent.save()

        assert institution_courante(polyvalent) is None


class TestLaPageTientALEchelle:
    def test_la_recherche_se_fait_cote_serveur(self, polyvalent, mairie, association):
        """Sinon il faudrait d'abord tout charger — exactement ce qu'on veut éviter avec des
        milliers d'institutions."""
        reponse = _client(polyvalent).get(
            reverse("contactinstitution-list"), {"search": "Casques", "page": 1})

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["count"] == 1
        assert reponse.data["results"][0]["institution_nom"] == association.nom

    def test_la_pagination_s_active_sur_demande(self, polyvalent):
        reponse = _client(polyvalent).get(
            reverse("contactinstitution-list"), {"page": 1, "page_size": 1})

        assert reponse.data["count"] == 2
        assert len(reponse.data["results"]) == 1
        assert reponse.data["next"] is not None

    def test_sans_page_le_contrat_des_anciens_appelants_ne_change_pas(self, polyvalent):
        """Cinq pages attendent un tableau brut : la pagination est opt-in pour ne pas les
        casser."""
        reponse = _client(polyvalent).get(reverse("contactinstitution-list"))

        assert isinstance(reponse.data, list)

    def test_le_nom_de_l_institution_est_servi_avec_le_rattachement(self, polyvalent):
        """C'est ce qui permet de ne plus charger le catalogue des institutions ni tous les
        comptes pour afficher une colonne."""
        reponse = _client(polyvalent).get(reverse("contactinstitution-list"))

        ligne = reponse.data[0]
        assert ligne["institution_nom"]
        assert "utilisateur_nom" in ligne
