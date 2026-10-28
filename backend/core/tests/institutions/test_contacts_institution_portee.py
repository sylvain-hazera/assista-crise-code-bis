"""Qui peut lire quels contacts d'institution.

Jusqu'au 28/10/2026, `ContactInstitutionViewSet` n'avait **aucune** `permission_classes` — donc
le défaut `IsAuthenticated` — et son queryset ne filtrait que par environnement. N'importe quel
compte authentifié, y compris un citoyen venu déclarer un dégât, pouvait lister les contacts de
TOUTES les institutions de la plateforme : noms, emails, fonctions. Les cinq pages qui
consomment cet endpoint tiraient d'ailleurs la table entière pour n'afficher qu'une institution
à la fois.

Trois cercles, et c'est ce que ces tests tiennent :

1. **Administrateur** : tout, comme avant.
2. **Rôle institutionnel avec un filtre `?institution=` explicite** : les contacts de celle-là.
   C'est le besoin réel du métier — désigner le responsable d'une institution qu'on déclare
   actrice sur une crise suppose de voir ses contacts sans en être membre. La question ciblée
   reste permise ; c'est la liste en vrac qui disparaît.
3. **Tout le monde** : ses propres rattachements et ceux des institutions dont il est membre
   actif. Un citoyen sans institution ne voit donc rien.
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType, UserRole


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


def _institution(nom, code="mairie"):
    itype, _ = InstitutionType.objects.get_or_create(code=code, defaults={"libelle": code})
    institution, _ = Institution.objects.get_or_create(
        nom=nom, defaults={"type": itype, "actif": True})
    return institution


@pytest.fixture
def ma_mairie(db):
    return _institution("Mairie de Portee Test")


@pytest.fixture
def mairie_voisine(db):
    return _institution("Mairie Voisine Portee Test")


@pytest.fixture
def mon_contact(create_user, ma_mairie):
    user = create_user(username="agent-portee@test.fr", email="agent-portee@test.fr",
                       type=UserRole.LOCAL_AUTHORITY, last_name="AGENT")
    ContactInstitution.objects.create(
        institution=ma_mairie, utilisateur=user, fonction="Secrétaire", actif=True)
    return user


@pytest.fixture
def collegue(create_user, ma_mairie):
    """Un autre contact de MA mairie : je dois le voir."""
    user = create_user(username="collegue-portee@test.fr", email="collegue-portee@test.fr",
                       type=UserRole.LOCAL_AUTHORITY, last_name="COLLEGUE")
    return ContactInstitution.objects.create(
        institution=ma_mairie, utilisateur=user, fonction="Adjoint", actif=True)


@pytest.fixture
def contact_voisin(create_user, mairie_voisine):
    """Un contact d'une AUTRE institution : je ne le vois pas en vrac."""
    user = create_user(username="voisin-portee@test.fr", email="voisin-portee@test.fr",
                       type=UserRole.LOCAL_AUTHORITY, last_name="VOISIN")
    return ContactInstitution.objects.create(
        institution=mairie_voisine, utilisateur=user, fonction="Maire", actif=True)


def _noms(reponse):
    return {c["fonction"] for c in reponse.data}


class TestLeCitoyenNeVoitRien:
    def test_un_compte_simple_sans_institution_ne_voit_aucun_contact(
            self, create_user, collegue, contact_voisin):
        """LE test. Un citoyen vient déclarer un dégât : il n'a aucune raison de repartir avec
        l'annuaire nominatif des agents de toutes les mairies de la plateforme."""
        citoyen = create_user(username="citoyen-portee@test.fr",
                              email="citoyen-portee@test.fr",
                              type=UserRole.SIMPLE_USER, last_name="CITOYEN")

        reponse = _client(citoyen).get(reverse("contactinstitution-list"))

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data == []

    def test_un_compte_simple_ne_contourne_pas_avec_un_filtre(
            self, create_user, mairie_voisine, contact_voisin):
        """La question ciblée est réservée aux rôles institutionnels : sans ça, la restriction
        se contournerait en ajoutant un paramètre d'URL."""
        citoyen = create_user(username="citoyen2-portee@test.fr",
                              email="citoyen2-portee@test.fr",
                              type=UserRole.SIMPLE_USER, last_name="CITOYEN2")

        reponse = _client(citoyen).get(
            reverse("contactinstitution-list"), {"institution": str(mairie_voisine.id)})

        assert reponse.data == []

    def test_un_anonyme_na_pas_acces(self, collegue):
        reponse = APIClient().get(reverse("contactinstitution-list"))

        assert reponse.status_code in (status.HTTP_401_UNAUTHORIZED,
                                       status.HTTP_403_FORBIDDEN)


class TestChacunVoitSonInstitution:
    def test_je_vois_mes_collegues(self, mon_contact, collegue):
        reponse = _client(mon_contact).get(reverse("contactinstitution-list"))

        assert "Adjoint" in _noms(reponse)
        assert "Secrétaire" in _noms(reponse)

    def test_je_ne_vois_pas_les_contacts_dune_autre_institution(
            self, mon_contact, collegue, contact_voisin):
        reponse = _client(mon_contact).get(reverse("contactinstitution-list"))

        assert "Maire" not in _noms(reponse)

    def test_un_rattachement_desactive_ne_donne_plus_acces(
            self, mon_contact, ma_mairie, collegue):
        """Un ancien membre ne doit pas garder l'annuaire de l'institution qu'il a quittée."""
        ContactInstitution.objects.filter(
            institution=ma_mairie, utilisateur=mon_contact).update(actif=False)

        reponse = _client(mon_contact).get(reverse("contactinstitution-list"))

        # Il voit encore sa PROPRE ligne (c'est la sienne), pas celles des autres.
        assert "Adjoint" not in _noms(reponse)
        assert "Secrétaire" in _noms(reponse)


class TestLaQuestionCibleeResteOuverte:
    """Le besoin métier : déclarer une institution actrice sur une crise et désigner son
    responsable, ce qui suppose de voir ses contacts sans en être membre."""

    def test_un_role_institutionnel_peut_interroger_une_autre_institution(
            self, mon_contact, mairie_voisine, contact_voisin):
        reponse = _client(mon_contact).get(
            reverse("contactinstitution-list"), {"institution": str(mairie_voisine.id)})

        assert reponse.status_code == status.HTTP_200_OK
        assert _noms(reponse) == {"Maire"}

    def test_le_filtre_borne_bien_la_reponse(
            self, mon_contact, collegue, mairie_voisine, contact_voisin):
        """Demander une institution ne doit pas rendre toutes les autres au passage."""
        reponse = _client(mon_contact).get(
            reverse("contactinstitution-list"), {"institution": str(mairie_voisine.id)})

        assert "Adjoint" not in _noms(reponse)

    def test_sans_filtre_le_meme_compte_ne_voit_que_le_sien(
            self, mon_contact, collegue, contact_voisin):
        """La différence qui fait tout : la question ciblée est permise, la liste en vrac non."""
        reponse = _client(mon_contact).get(reverse("contactinstitution-list"))

        assert "Maire" not in _noms(reponse)


class TestAdministrateur:
    def test_un_administrateur_voit_tout(self, create_user, collegue, contact_voisin):
        """Il arbitre les rattachements et doit pouvoir débloquer une institution dont le
        bureau a perdu ses accès."""
        admin = create_user(username="admin-portee@test.fr", email="admin-portee@test.fr",
                           type=UserRole.ADMINISTRATOR, last_name="ADMIN")

        reponse = _client(admin).get(reverse("contactinstitution-list"))

        assert {"Adjoint", "Maire"} <= _noms(reponse)


class TestNonRegressionDesPagesExistantes:
    """Les cinq pages qui consomment cet endpoint filtraient déjà côté client sur leur propre
    institution ou leur propre compte : le cadrage ne doit rien leur retirer."""

    def test_le_formulaire_de_declaration_retrouve_ses_rattachements(
            self, mon_contact, ma_mairie):
        """declare-crisis-form : `contacts.filter(c => c.utilisateur === me.id && c.actif)`."""
        reponse = _client(mon_contact).get(reverse("contactinstitution-list"))

        miens = [c for c in reponse.data
                 if str(c["utilisateur"]) == str(mon_contact.id)]
        assert len(miens) == 1
        assert str(miens[0]["institution"]) == str(ma_mairie.id)

    def test_le_modal_de_plan_retrouve_les_contacts_de_son_institution(
            self, mon_contact, ma_mairie, collegue):
        """plan-modal : `contacts.filter(c => c.institution === myInstitutionId)`."""
        reponse = _client(mon_contact).get(reverse("contactinstitution-list"))

        de_ma_mairie = [c for c in reponse.data
                        if str(c["institution"]) == str(ma_mairie.id)]
        assert len(de_ma_mairie) == 2
