"""Thèmes « à l'écoute » et dépôt public (besoins_ecoute.besoins_a_lecoute, TypesALecouteView).

Le filtrage des formulaires publics par les thèmes déclarés laissait le visiteur sans aucune
option dans trois cas réels, constatés en base le 26/10/2026 :
  - une mairie cochant une FAMILLE de thèmes (« Accueil & alimentation », « Secours & soins »),
    alors que les correspondances thème -> type étaient posées sur les sous-besoins ;
  - une mairie cochant seulement « Autre », faute de correspondance côté demande d'aide ;
  - une implication ACTEUR créée automatiquement (déclaration de crise, point confié à une
    équipe), donc sans aucun thème.
Dans chacun, le public ne pouvait plus rien déposer : ni demande, ni offre, ni signalement.
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.besoins_ecoute import besoins_a_lecoute
from core.models import (
    Besoin,
    Crisis,
    InformationType,
    InformationTypeBesoin,
    OfferType,
    ImplicationInstitution,
    Institution,
    InstitutionType,
    RequestType,
    RequestTypeBesoin,
    StatutImplication,
    TypeImplication,
)


@pytest.fixture
def crise(db):
    return Crisis.objects.create(
        name="Crise thèmes à l'écoute", type="INONDATION",
        location="POINT (5.72 45.18)", zone_communes=["38185"],
    )


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "MAIRIE"})
    return Institution.objects.create(nom="Mairie thèmes à l'écoute", type=itype, commune_code="38185")


def _acteur(crise, institution, themes=()):
    implication = ImplicationInstitution.objects.create(
        crise=crise, institution=institution, actif=True,
        type_implication=TypeImplication.ACTEUR, statut=StatutImplication.VALIDEE,
    )
    if themes:
        implication.themes.set(themes)
    return implication


@pytest.mark.django_db
class TestFamillesDeThemes:

    def test_ecouter_une_famille_vaut_pour_ses_sous_besoins(self, crise, mairie):
        famille = Besoin.objects.create(nom="Accueil & alimentation test")
        enfant = Besoin.objects.create(nom="Hébergement test", parent=famille)
        _acteur(crise, mairie, [famille])

        a_lecoute = set(besoins_a_lecoute(crise, "38185").values_list("nom", flat=True))

        assert a_lecoute == {famille.nom, enfant.nom}

    def test_ecouter_un_sous_besoin_ne_vaut_pas_pour_la_famille(self, crise, mairie):
        """Sens unique assumé : un choix précis reste un choix précis."""
        famille = Besoin.objects.create(nom="Secours & soins test")
        enfant = Besoin.objects.create(nom="Soins médicaux test", parent=famille)
        autre_enfant = Besoin.objects.create(nom="Soutien psychologique test", parent=famille)
        _acteur(crise, mairie, [enfant])

        a_lecoute = set(besoins_a_lecoute(crise, "38185").values_list("nom", flat=True))

        assert a_lecoute == {enfant.nom}
        assert autre_enfant.nom not in a_lecoute

    def test_le_type_du_sous_besoin_devient_proposable(self, crise, mairie):
        """Le bout qui manquait vraiment : la famille écoutée doit faire apparaître les types
        des sous-besoins dans le formulaire public."""
        famille = Besoin.objects.create(nom="Pompage & citernes test")
        enfant = Besoin.objects.create(nom="Pompage test", parent=famille)
        request_type = RequestType.objects.create(type="Pompage test")
        RequestTypeBesoin.objects.create(request_type=request_type, besoin=enfant)
        _acteur(crise, mairie, [famille])

        client = APIClient()
        response = client.get(reverse('types_a_lecoute'), {
            "crise": str(crise.id), "commune_code": "38185", "axe": "request",
        })

        assert response.status_code == 200
        assert response.data["repli"] is False
        assert str(request_type.id) in response.data["type_ids"]


@pytest.mark.django_db
class TestThemeAutre:
    """« Autre » était relié au type d'offre et à celui de signalement, mais pas à celui de
    demande d'aide : une mairie n'écoutant que ce thème (cas réel, crise « FDF » /
    Rion-des-Landes) bloquait toute demande. Réparé par la migration 0216, dont on vérifie ici
    la correspondance — le référentiel « Autre » lui-même n'existe pas dans une base de test
    vierge, la migration est donc volontairement sans effet ici (et sur toute base où l'un des
    deux a été renommé)."""

    def test_la_migration_relie_le_besoin_au_type_de_demande(self):
        from importlib import import_module

        from django.apps import apps as registre

        # Le nom du module commence par un chiffre : import_module, pas un import classique.
        migration = import_module("core.migrations.0216_besoin_autre_vers_request_type_autre")

        besoin, _ = Besoin.objects.get_or_create(nom="Autre")
        request_type = RequestType.objects.create(type="Autre")

        migration.relier_autre(registre, None)
        # Rejouée (redéploiement, base déjà à jour) : jamais de doublon.
        migration.relier_autre(registre, None)

        assert RequestTypeBesoin.objects.filter(
            request_type=request_type, besoin=besoin,
        ).count() == 1

    def test_la_migration_ne_casse_rien_sans_referentiel(self):
        """Le type « Autre » peut avoir été renommé ou supprimé : une correspondance de
        référentiel ne doit jamais faire échouer un déploiement."""
        from importlib import import_module

        from django.apps import apps as registre

        migration = import_module("core.migrations.0216_besoin_autre_vers_request_type_autre")

        Besoin.objects.get_or_create(nom="Autre")
        assert not RequestType.objects.filter(type="Autre").exists()

        migration.relier_autre(registre, None)  # ne doit pas lever

        assert not RequestTypeBesoin.objects.filter(besoin__nom="Autre").exists()

    def test_le_theme_autre_rend_la_demande_d_aide_possible(self, crise, mairie):
        besoin, _ = Besoin.objects.get_or_create(nom="Autre")
        request_type = RequestType.objects.create(type="Autre")
        RequestTypeBesoin.objects.create(request_type=request_type, besoin=besoin)
        _acteur(crise, mairie, [besoin])

        client = APIClient()
        response = client.get(reverse('types_a_lecoute'), {
            "crise": str(crise.id), "commune_code": "38185", "axe": "request",
        })

        assert response.status_code == 200
        assert response.data["repli"] is False
        assert response.data["type_ids"] == [str(request_type.id)]


@pytest.mark.django_db
class TestRepliJamaisDeCulDeSac:
    """Un visiteur ne doit jamais se retrouver sans aucune option : mieux vaut un dépôt mal
    rangé que quelqu'un sans voix un jour de crise."""

    def test_acteur_sans_aucun_theme_laisse_le_depot_possible(self, crise, mairie):
        _acteur(crise, mairie, [])
        attendu = RequestType.objects.filter(actif=True).count()
        assert attendu > 0

        client = APIClient()
        response = client.get(reverse('types_a_lecoute'), {
            "crise": str(crise.id), "commune_code": "38185", "axe": "request",
        })

        assert response.status_code == 200
        assert response.data["repli"] is True
        assert len(response.data["type_ids"]) == attendu

    def test_theme_sans_correspondance_sur_cet_axe_bascule_en_repli(self, crise, mairie):
        # Thème neuf, relié à aucun type : rien à proposer sans repli.
        orphelin = Besoin.objects.create(nom="Thème sans correspondance test")
        _acteur(crise, mairie, [orphelin])

        client = APIClient()
        response = client.get(reverse('types_a_lecoute'), {
            "crise": str(crise.id), "commune_code": "38185", "axe": "request",
        })

        assert response.status_code == 200
        assert response.data["repli"] is True
        assert len(response.data["type_ids"]) > 0
        # Le thème déclaré reste affiché tel quel au visiteur.
        assert [b["nom"] for b in response.data["besoins"]] == [orphelin.nom]

    def test_repli_aussi_hors_zone_de_la_crise(self, crise, mairie):
        """Hors zone, aucune institution n'écoute : c'était le cul-de-sac le plus fréquent."""
        _acteur(crise, mairie, [Besoin.objects.create(nom="Thème hors zone test")])

        client = APIClient()
        response = client.get(reverse('types_a_lecoute'), {
            "crise": str(crise.id), "commune_code": "99999", "axe": "request",
        })

        assert response.status_code == 200
        assert response.data["repli"] is True
        assert len(response.data["type_ids"]) > 0

    def test_le_repli_vaut_pour_les_trois_formulaires(self, crise, mairie):
        _acteur(crise, mairie, [])
        # Une base de test vierge n'a ni OfferType ni InformationType (référentiels alimentés
        # en exploitation) : sans au moins une ligne, « tout le catalogue » reste vide.
        OfferType.objects.get_or_create(type="Offre test", defaults={"actif": True})
        InformationType.objects.get_or_create(type="Signalement test")
        client = APIClient()

        for axe in ("request", "offer", "information"):
            response = client.get(reverse('types_a_lecoute'), {
                "crise": str(crise.id), "commune_code": "38185", "axe": axe,
            })
            assert response.status_code == 200, axe
            assert response.data["repli"] is True, axe
            assert len(response.data["type_ids"]) > 0, axe

    def test_visiteur_anonyme_sert_bien_le_repli(self, crise, mairie):
        _acteur(crise, mairie, [])
        InformationType.objects.get_or_create(type="Signalement test")

        # Pas d'authentification du tout : c'est le cas normal d'un dépôt public.
        response = APIClient().get(reverse('types_a_lecoute'), {
            "crise": str(crise.id), "commune_code": "38185", "axe": "information",
        })

        assert response.status_code == 200
        assert len(response.data["type_ids"]) > 0
