"""Rejoindre une association agréée de sécurité civile (AASC).

Une AASC est une association AGRÉÉE : son existence sur la plateforme est un acte
administratif. Le rattachement faisait pourtant un `get_or_create` sur le nom saisi à
l'inscription, si bien qu'un bénévole tapant « Casques jaunes » au lieu de « Réserve
Résilience - Casques Jaunes » fabriquait une seconde association et s'y retrouvait
« Créateur », contact principal et responsable. Même famille de défaut que pour les mairies
créées depuis l'annuaire officiel (voir test_institution_depuis_annuaire.py), avec une
conséquence pire : des droits de gouvernance sur une association fantôme.

Trois règles tenues ici :
1. on rejoint une association existante, on ne la fabrique pas en la nommant ;
2. un membre tout juste accepté est « Intervenant », pas régulateur de crise ;
3. le bureau d'une association valide ses propres candidats, où qu'ils habitent — une AASC
   recrute à l'échelle d'un département, pas d'un village.
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.institution_attachment import attach_secours_user_to_institution, trouver_aasc
from core.models import (
    AffectationRoleOperationnel, ContactInstitution, Institution, InstitutionType, User,
    UserRole,
)

NOM_REEL = "Réserve Résilience - Casques Jaunes"


@pytest.fixture
def aasc(db):
    """La vraie association, semée par la migration 0199 avec son branding et ses deux
    hostnames — `Institution.nom` étant unique, on la reprend au lieu d'en créer une seconde,
    ce qui est précisément la règle que ce fichier teste."""
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    # Portée nationale : pas de commune (voir le docstring de la migration 0199).
    institution, _ = Institution.objects.get_or_create(
        nom=NOM_REEL, defaults={"type": itype, "actif": True})
    if institution.type_id != itype.pk or not institution.actif:
        institution.type = itype
        institution.actif = True
        institution.save(update_fields=["type", "actif"])
    return institution


@pytest.fixture
def candidat(create_user, db):
    user = create_user(username="benevole@test.fr", email="benevole@test.fr",
                       type=UserRole.ORGANIZED_RESCUE, last_name="BENEVOLE")
    user.pending_institution_type = "aasc"
    user.pending_institution_name = NOM_REEL
    user.save(update_fields=["pending_institution_type", "pending_institution_name"])
    return user


class TestTrouverLAssociation:
    def test_le_nom_exact(self, aasc):
        assert trouver_aasc(NOM_REEL).pk == aasc.pk

    def test_casse_accents_et_espaces_sont_ignores(self, aasc):
        """Les variantes de frappe désignent la même association."""
        for variante in ("reserve resilience - casques jaunes",
                         "RÉSERVE RÉSILIENCE - CASQUES JAUNES",
                         "  Réserve  Résilience -   Casques Jaunes  "):
            assert trouver_aasc(variante).pk == aasc.pk, variante

    def test_un_nom_reellement_different_ne_correspond_pas(self, aasc):
        """La normalisation rattrape une faute de frappe, pas un autre nom : c'est au lien
        d'invitation et à la liste des associations de faire CHOISIR plutôt que saisir."""
        assert trouver_aasc("Casques Jaunes") is None

    def test_une_association_desactivee_nest_pas_proposee(self, aasc):
        aasc.actif = False
        aasc.save(update_fields=["actif"])

        assert trouver_aasc(NOM_REEL) is None

    def test_un_nom_vide(self, aasc):
        assert trouver_aasc("") is None
        assert trouver_aasc(None) is None


class TestRattachement:
    def test_le_benevole_rejoint_lassociation_existante(self, aasc, candidat):
        institution = attach_secours_user_to_institution(candidat)

        assert institution.pk == aasc.pk
        assert Institution.objects.filter(type__code__iexact="aasc").count() == 1
        candidat.refresh_from_db()
        assert candidat.institution_id == aasc.pk

    def test_aucune_association_nest_fabriquee_par_une_faute_de_frappe(self, aasc, candidat):
        """LE test. Une AASC est une association agréée : la nommer de travers ne doit pas en
        créer une seconde, et surtout pas en faire son responsable."""
        candidat.pending_institution_name = "Casques Jaunes"
        candidat.save(update_fields=["pending_institution_name"])

        institution = attach_secours_user_to_institution(candidat)

        assert institution is None
        assert Institution.objects.filter(type__code__iexact="aasc").count() == 1
        candidat.refresh_from_db()
        assert candidat.institution_id is None
        assert not AffectationRoleOperationnel.objects.filter(utilisateur=candidat).exists()

    def test_les_informations_declarees_sont_conservees(self, aasc, candidat):
        """Pour qu'un rattachement manuel reste possible : les effacer laissait un compte actif
        sans institution et sans plus aucune trace de ce qu'il avait déclaré."""
        candidat.pending_institution_name = "Casques Jaunes"
        candidat.save(update_fields=["pending_institution_name"])

        attach_secours_user_to_institution(candidat)

        candidat.refresh_from_db()
        assert candidat.pending_institution_name == "Casques Jaunes"
        assert candidat.pending_institution_type == "aasc"

    def test_un_membre_accepte_est_intervenant_pas_regulateur(self, aasc, candidat):
        """Le défaut d'assign_default_institution_role est « RESPONSABLE si personne d'autre,
        REGULATEUR sinon » : les deux sont absurdes pour quelqu'un qui vient d'être accepté.
        C'est au bureau d'élever ce niveau quand la personne est formée."""
        attach_secours_user_to_institution(candidat)

        roles = AffectationRoleOperationnel.objects.filter(
            utilisateur=candidat, institution=aasc)
        assert [r.role.code for r in roles] == ["INTERVENANT"]

    def test_il_nest_pas_contact_principal(self, aasc, candidat):
        """« Créateur » et contact principal étaient posés dès que l'institution venait d'être
        créée — donc à chaque faute de frappe."""
        attach_secours_user_to_institution(candidat)

        contact = ContactInstitution.objects.get(institution=aasc, utilisateur=candidat)
        assert contact.contact_principal is False
        assert contact.membre_bureau is False
        assert contact.fonction == "Membre"


class TestValidationParLeBureau:
    """Une AASC recrute à l'échelle d'un département : exiger que le validateur ait le même
    code postal que le candidat rendait le recrutement impossible dès le deuxième village."""

    @pytest.fixture
    def membre_bureau(self, aasc, create_user):
        user = create_user(username="bureau@test.fr", email="bureau@test.fr",
                           type=UserRole.LOCAL_AUTHORITY, last_name="BUREAU")
        user.postal_code = "29000"
        user.save(update_fields=["postal_code"])
        ContactInstitution.objects.create(
            institution=aasc, utilisateur=user, fonction="Président",
            membre_bureau=True, actif=True)
        return user

    @pytest.fixture
    def candidat_ailleurs(self, candidat):
        candidat.postal_code = "29800"
        candidat.enabled = False
        candidat.is_active = False
        candidat.save(update_fields=["postal_code", "enabled", "is_active"])
        return candidat

    def _approuver(self, validateur, candidat):
        client = APIClient()
        client.force_authenticate(user=validateur)
        return client.post(reverse("user-approve-account", args=[candidat.id]))

    def test_le_bureau_valide_un_candidat_dun_autre_code_postal(
            self, membre_bureau, candidat_ailleurs):
        reponse = self._approuver(membre_bureau, candidat_ailleurs)

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        candidat_ailleurs.refresh_from_db()
        assert candidat_ailleurs.is_active is True

    def test_un_membre_simple_ne_valide_pas(self, aasc, candidat_ailleurs, create_user):
        """Être membre ne suffit pas : c'est le bureau qui recrute."""
        simple = create_user(username="simple@test.fr", email="simple@test.fr",
                            type=UserRole.LOCAL_AUTHORITY, last_name="SIMPLE")
        simple.postal_code = "29000"
        simple.save(update_fields=["postal_code"])
        ContactInstitution.objects.create(
            institution=aasc, utilisateur=simple, fonction="Membre", actif=True)

        reponse = self._approuver(simple, candidat_ailleurs)

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_le_bureau_dune_AUTRE_association_ne_valide_pas(
            self, candidat_ailleurs, create_user, db):
        """Le contrôle territorial n'est pas remplacé par « au bureau de n'importe quoi »."""
        itype, _ = InstitutionType.objects.get_or_create(
            code="aasc", defaults={"libelle": "AASC"})
        autre, _ = Institution.objects.get_or_create(
            nom="Protection Civile 56", defaults={"type": itype, "actif": True})
        intrus = create_user(username="intrus@test.fr", email="intrus@test.fr",
                             type=UserRole.LOCAL_AUTHORITY, last_name="INTRUS")
        intrus.postal_code = "56000"
        intrus.save(update_fields=["postal_code"])
        ContactInstitution.objects.create(
            institution=autre, utilisateur=intrus, fonction="Président",
            membre_bureau=True, actif=True)

        reponse = self._approuver(intrus, candidat_ailleurs)

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_le_controle_territorial_des_mairies_est_intact(
            self, candidat_ailleurs, create_user):
        """Une autorité locale sans lien avec l'association reste bornée à son territoire."""
        mairie = create_user(username="mairie@test.fr", email="mairie@test.fr",
                             type=UserRole.LOCAL_AUTHORITY, last_name="MAIRIE")
        mairie.postal_code = "75001"
        mairie.save(update_fields=["postal_code"])

        reponse = self._approuver(mairie, candidat_ailleurs)

        assert reponse.status_code == status.HTTP_403_FORBIDDEN
