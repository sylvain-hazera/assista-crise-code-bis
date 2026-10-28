"""Qui voit la page « Membres association » (`UserSerializer.acces_membres_association`).

Demande du 28/10/2026 : « une institution non asso ne doit pas voir cette page ». Jusque-là
l'entrée était visible de tout rôle institutionnel et la page se fermait d'elle-même, ce qui la
faisait paraître **cassée** à une mairie plutôt qu'absente.

Les trois critères sont calculés côté serveur parce qu'aucun n'est vérifiable depuis le
navigateur — le troisième surtout, qui est un attribut du rattachement et non du compte.
"""
import pytest

from core.models import ContactInstitution, Institution, InstitutionType
from core.serializers import UserSerializer


@pytest.fixture
def type_aasc(db):
    return InstitutionType.objects.create(code="AASC", libelle="Association agréée")


@pytest.fixture
def type_mairie(db):
    return InstitutionType.objects.create(code="MAIRIE_ACCES_TEST", libelle="Mairie")


@pytest.fixture
def association(db, type_aasc):
    return Institution.objects.create(nom="AASC acces test", type=type_aasc)


@pytest.fixture
def mairie(db, type_mairie):
    return Institution.objects.create(
        nom="Mairie acces test", type=type_mairie, commune_code="29026")


def _acces(user):
    return UserSerializer(user).data["acces_membres_association"]


@pytest.mark.django_db
class TestAccesMembresAssociation:
    def test_un_compte_rattache_a_une_aasc_voit_la_page(self, create_user, association):
        user = create_user(username="aasc@test.fr", email="aasc@test.fr", type="SECOURS")
        user.institution = association
        user.save()

        assert _acces(user) is True

    def test_une_mairie_ne_voit_pas_la_page(self, create_user, mairie):
        """Le cœur de la demande : cette page ne parle que d'associations."""
        user = create_user(username="mairie-acces@test.fr", email="mairie-acces@test.fr",
                           type="AUT_LOCALE")
        user.institution = mairie
        user.save()

        assert _acces(user) is False

    def test_un_membre_du_bureau_rattache_ailleurs_voit_la_page(
        self, create_user, mairie, association
    ):
        """Un agent de mairie peut très bien être au bureau de l'association locale : le
        critère du seul rattachement le priverait de la page dont il a la charge."""
        user = create_user(username="double-casquette@test.fr",
                           email="double-casquette@test.fr", type="AUT_LOCALE")
        user.institution = mairie
        user.save()
        ContactInstitution.objects.create(
            institution=association, utilisateur=user, actif=True, membre_bureau=True)

        assert _acces(user) is True

    def test_un_simple_membre_de_l_association_ne_suffit_pas(
        self, create_user, mairie, association
    ):
        """Être adhérent n'est pas être au bureau. Le rattachement existe, mais sans le drapeau
        bureau il n'ouvre pas la gestion de l'effectif."""
        user = create_user(username="adherent@test.fr", email="adherent@test.fr",
                           type="AUT_LOCALE")
        user.institution = mairie
        user.save()
        ContactInstitution.objects.create(
            institution=association, utilisateur=user, actif=True, membre_bureau=False)

        assert _acces(user) is False

    def test_un_rattachement_inactif_ne_compte_pas(self, create_user, mairie, association):
        user = create_user(username="ancien-bureau@test.fr", email="ancien-bureau@test.fr",
                           type="AUT_LOCALE")
        user.institution = mairie
        user.save()
        ContactInstitution.objects.create(
            institution=association, utilisateur=user, actif=False, membre_bureau=True)

        assert _acces(user) is False

    def test_une_association_fusionnee_ne_rouvre_pas_la_page(
        self, create_user, mairie, association
    ):
        """Une institution fusionnée est conservée comme pierre tombale (actif=False, voir la
        commande fusionner_institutions). Elle ne doit pas donner d'accès : il n'y a plus
        d'effectif à gérer."""
        user = create_user(username="bureau-fusionnee@test.fr",
                           email="bureau-fusionnee@test.fr", type="AUT_LOCALE")
        user.institution = mairie
        user.save()
        ContactInstitution.objects.create(
            institution=association, utilisateur=user, actif=True, membre_bureau=True)
        association.actif = False
        association.save(update_fields=["actif"])

        assert _acces(user) is False

    def test_un_compte_rattache_a_une_aasc_desactivee_ne_voit_pas_la_page(
        self, create_user, association
    ):
        user = create_user(username="aasc-morte@test.fr", email="aasc-morte@test.fr",
                           type="SECOURS")
        user.institution = association
        user.save()
        association.actif = False
        association.save(update_fields=["actif"])

        assert _acces(user) is False

    def test_l_administrateur_voit_toujours_la_page(self, create_user):
        """Il doit pouvoir débloquer une association dont le bureau a perdu ses accès (voir
        recrutement_association.peut_instruire) — y compris sans aucun rattachement."""
        admin = create_user(username="admin-asso@test.fr", email="admin-asso@test.fr",
                            type="ADMIN")

        assert _acces(admin) is True

    def test_un_compte_sans_institution_ne_voit_pas_la_page(self, create_user):
        citoyen = create_user(username="citoyen-asso@test.fr", email="citoyen-asso@test.fr",
                              type="UTIL_SIMPLE")

        assert _acces(citoyen) is False

    def test_le_code_du_type_est_compare_sans_casse(self, create_user, db):
        """Les lignes de catalogue existent en « AASC » comme en « aasc » selon la façon dont
        elles ont été créées — comparer brutalement fermerait la page à la moitié d'entre
        elles."""
        # get_or_create : une ligne de code « aasc » est deja seedee par les migrations, et
        # la fixture ci-dessus en cree une en « AASC ». Les deux coexistent reellement en base,
        # ce qui est precisement la raison d'etre de la comparaison insensible a la casse.
        type_minuscule, _ = InstitutionType.objects.get_or_create(
            code="aasc", defaults={"libelle": "Association"})
        asso = Institution.objects.create(nom="AASC minuscule", type=type_minuscule)
        user = create_user(username="casse@test.fr", email="casse@test.fr", type="SECOURS")
        user.institution = asso
        user.save()

        assert _acces(user) is True
