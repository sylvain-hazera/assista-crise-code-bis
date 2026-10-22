"""Copie central -> satellite des équipes et de la radio, et de la zone de démonstration (retour
de terrain du 21/10/2026 : companion MeshCore invisible sur le satellite, pas d'équipes, pas de
zone démo). Voir core/sync_referentiel.py et synchroniser_entrant."""
import datetime

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    CanalMeshCore, CompagnonMeshCore, CompagnonMeshtastic, Commune, ContactMeshCore, Crisis,
    Institution, InstitutionType, NoeudMeshUtilisateur, ProvisionCanalMeshCore, RelaisMeshCore, Satellite,
    StatutEnrolementSatellite, Team, User,
)
from core.sync_comptes import appliquer_comptes
from core.sync_referentiel import appliquer_referentiel, referentiel_pour_satellite


@pytest.fixture
def commune(db):
    return Commune.objects.create(
        code="42218", nom="Saint-Étienne", departement_code="42", epci_code="244200770",
        region_code="84", centre_latitude=45.43, centre_longitude=4.39,
    )


@pytest.fixture
def institution(commune):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie Référentiel", type=itype, commune_code=commune.code)


@pytest.fixture
def autre_institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie Ailleurs", type=itype, commune_code="59350")


def _satellite(create_user, institution, profil="FULL", demo_role="UTIL_SIMPLE"):
    compte = create_user(
        username=f"satellite-ref-{profil}@service.assista-crise.local",
        email=f"satellite-ref-{profil}@service.assista-crise.local",
        type="UTIL_SIMPLE", institution=institution,
    )
    compte.demo_role = demo_role
    compte.save()
    return Satellite.objects.create(
        institution=institution, nom=f"Sat {profil}", profil=profil,
        statut_enrolement=StatutEnrolementSatellite.APPROUVE, compte_service=compte,
    )


def _client(satellite):
    client = APIClient()
    client.force_authenticate(user=satellite.compte_service)
    return client


@pytest.fixture
def radio(create_user, institution, autre_institution):
    """Équipe, companion, contact, canal, nœud attribué et répéteurs, dans et hors institution."""
    membre = create_user(username="membre@mairie.fr", email="membre@mairie.fr", type="AUT_LOCALE", institution=institution)
    equipe = Team.objects.create(name="Équipe Nord", institution=institution)
    equipe.members.add(membre)
    compagnon = CompagnonMeshCore.objects.create(
        institution=institution, nom="Companion du satellite", connexion_type="SERIE",
        serie_device="/dev/ttyACM1", location=Point(4.39, 45.43, srid=4326),
    )
    contact = ContactMeshCore.objects.create(compagnon=compagnon, pubkey_hex="ab" * 32, nom="Radio de Jeanne")
    canal = CanalMeshCore.objects.create(institution=institution, equipe=equipe, nom="#nord")
    provision = ProvisionCanalMeshCore.objects.create(canal=canal, compagnon=compagnon, canal_idx=2)
    noeud = NoeudMeshUtilisateur.objects.create(utilisateur=membre, pubkey_hex="cd" * 32, nom_noeud="T-Deck Jeanne")
    relais_commun = RelaisMeshCore.objects.create(nom="Relais Pilat", pubkey_hex="ef" * 32)
    relais_ailleurs = RelaisMeshCore.objects.create(nom="Relais Lille", pubkey_hex="01" * 32, institution=autre_institution)
    equipe_ailleurs = Team.objects.create(name="Équipe Lille", institution=autre_institution)
    compagnon_ailleurs = CompagnonMeshCore.objects.create(institution=autre_institution, nom="Companion Lille")
    return locals()


@pytest.mark.django_db
class TestReferentielCentral:

    def test_seulement_ce_qui_concerne_l_institution(self, create_user, institution, radio):
        satellite = _satellite(create_user, institution)

        ref = _client(satellite).get(reverse('satellite-donnees', args=[satellite.id])).data["referentiel"]

        ids = lambda cle: {e["id"] for e in ref[cle]}
        assert ids("equipes") == {str(radio["equipe"].id)}
        assert ids("compagnons_meshcore") == {str(radio["compagnon"].id)}
        assert ids("contacts_meshcore") == {str(radio["contact"].id)}
        assert ids("canaux_meshcore") == {str(radio["canal"].id)}
        assert ids("provisions_canaux_meshcore") == {str(radio["provision"].id)}
        assert ids("noeuds_meshcore") == {str(radio["noeud"].id)}
        assert str(radio["relais_commun"].id) in ids("relais_meshcore")
        assert str(radio["relais_ailleurs"].id) not in ids("relais_meshcore")
        equipe = ref["equipes"][0]
        assert equipe["members"] == [str(radio["membre"].id)]

    def test_satellite_passerelle_ne_recoit_pas_le_referentiel(self, create_user, institution, radio):
        satellite = _satellite(create_user, institution, profil="GW")
        assert _client(satellite).get(reverse('satellite-donnees', args=[satellite.id])).data["referentiel"] == {}

    def test_zone_demo_servie_au_compte_de_service(self, create_user, institution, commune):
        satellite = _satellite(create_user, institution)
        lieu = Point(commune.centre_longitude, commune.centre_latitude, srid=4326)
        prod = Crisis.objects.create(name="Réelle", type="INONDATION", location=lieu, zone_communes=[commune.code])
        demo = Crisis.objects.create(name="Démo", type="INONDATION", location=lieu, zone_communes=[commune.code], environment="DEMO")
        equipe_demo = Team.objects.create(name="Équipe démo", institution=institution, environment="DEMO")

        reponse = _client(satellite).get(reverse('satellite-donnees', args=[satellite.id]), HTTP_X_ENVIRONMENT="DEMO")

        assert reponse.status_code == 200, reponse.data
        assert [c["id"] for c in reponse.data["crises"]] == [str(demo.id)]
        assert str(prod.id) not in {c["id"] for c in reponse.data["crises"]}
        assert [e["id"] for e in reponse.data["referentiel"]["equipes"]] == [str(equipe_demo.id)]

    def test_validation_donne_l_acces_demo_au_compte_de_service(self, create_user, institution):
        from core.models import ContactInstitution
        maire = create_user(username="maire-ref@test.fr", email="maire-ref@test.fr", type="AUT_LOCALE", institution=institution)
        ContactInstitution.objects.create(institution=institution, utilisateur=maire, actif=True)
        satellite = Satellite.objects.create(institution=institution, nom="Sat neuf", profil="FULL")
        client = APIClient()
        client.force_authenticate(user=maire)

        client.post(reverse('satellite-valider', args=[satellite.id]), {}, format="json")

        satellite.refresh_from_db()
        assert satellite.compte_service.demo_role == "UTIL_SIMPLE"


@pytest.mark.django_db
class TestReferentielSatellite:
    """Côté satellite, simulé dans la même base : on construit la copie, on efface les objets,
    on applique, et ils doivent revenir à l'identique (même identifiant, mêmes champs)."""

    def test_recree_a_l_identique_avec_relations_et_champs_chiffres(self, institution, radio):
        ref = referentiel_pour_satellite(institution, "PROD")
        date_creation = radio["compagnon"].date_creation
        ids = {cle: radio[cle].id for cle in ("canal", "contact", "noeud", "compagnon", "equipe", "provision")}
        for cle in ids:
            radio[cle].delete()          # (delete() remet l'id de l'objet Python à None)

        resultat = appliquer_referentiel(ref)

        assert resultat["erreur"] == 0
        compagnon = CompagnonMeshCore.objects.get(pk=ids["compagnon"])
        assert compagnon.serie_device == "/dev/ttyACM1" and compagnon.location.x == pytest.approx(4.39)
        assert compagnon.date_creation == date_creation               # pas « maintenant »
        assert ContactMeshCore.objects.get(pk=ids["contact"]).nom == "Radio de Jeanne"   # chiffré relu
        assert NoeudMeshUtilisateur.objects.get(pk=ids["noeud"]).nom_noeud == "T-Deck Jeanne"
        canal = CanalMeshCore.objects.get(pk=ids["canal"])
        assert canal.equipe_id == ids["equipe"]
        provision = ProvisionCanalMeshCore.objects.get(pk=ids["provision"])     # slot du canal sur la radio
        assert (provision.canal_id, provision.compagnon_id, provision.canal_idx) == (canal.id, compagnon.id, 2)
        assert list(Team.objects.get(pk=ids["equipe"]).members.all()) == [radio["membre"]]

    def test_contact_decouvert_hors_ligne_mis_a_jour_sans_doublon(self, institution, radio):
        ref = referentiel_pour_satellite(institution, "PROD")
        # Pendant la coupure, le pont a recréé ce contact localement sous un autre identifiant.
        radio["contact"].delete()
        local = ContactMeshCore.objects.create(compagnon=radio["compagnon"], pubkey_hex="ab" * 32, nom="ancien nom")

        appliquer_referentiel(ref)

        contacts = ContactMeshCore.objects.filter(compagnon=radio["compagnon"], pubkey_hex="ab" * 32)
        assert contacts.count() == 1 and contacts.get().pk == local.pk
        assert contacts.get().nom == "Radio de Jeanne"

    def test_reference_absente_videe_ou_objet_ignore(self, create_user, institution, radio):
        ref = referentiel_pour_satellite(institution, "PROD")
        noeud = ref["noeuds_meshcore"][0]
        radio["noeud"].delete()
        radio["membre"].delete()                                   # compte pas (encore) copié

        resultat = appliquer_referentiel({"noeuds_meshcore": [noeud]})

        assert resultat == {"applique": 0, "ignore": 1, "erreur": 0}   # utilisateur obligatoire
        assert not NoeudMeshUtilisateur.objects.filter(pk=noeud["id"]).exists()

    def test_creation_d_equipe_sans_effets_de_bord(self, institution, radio, monkeypatch):
        ref = referentiel_pour_satellite(institution, "PROD")
        equipe_id = radio["equipe"].id
        radio["canal"].delete()
        radio["equipe"].delete()
        appele = []
        monkeypatch.setattr(Team, "save", lambda *a, **k: appele.append(1))   # save() jamais appelé

        appliquer_referentiel({"equipes": ref["equipes"]})

        assert appele == [] and Team.objects.filter(pk=equipe_id).exists()


@pytest.mark.django_db
class TestDemoSurLeSatellite:

    def test_droit_demo_recopie_avec_les_comptes(self):
        from django.contrib.auth.hashers import make_password
        donnees = {
            "institution": {
                "id": "11111111-2222-3333-4444-555555555556", "nom": "Mairie copiée démo", "type_code": "MAIRIE",
                "type_libelle": "Mairie", "commune_code": "42218", "commune_nom": "Saint-Étienne",
                "epci_code": None, "departement_code": "42", "region_code": "84",
                "secteur_niveau_effectif": "commune", "secteur_nom": "Saint-Étienne", "environment": "PROD",
            },
            "comptes": [
                {"id": "aaaaaaaa-0000-0000-0000-0000000000d1", "username": "demo@mairie.fr", "email": "demo@mairie.fr",
                 "first_name": "A", "last_name": "B", "type": "AUT_LOCALE", "demo_role": "AUT_LOCALE", "password": make_password("x")},
                {"id": "aaaaaaaa-0000-0000-0000-0000000000d2", "username": "sansdemo@mairie.fr", "email": "sansdemo@mairie.fr",
                 "first_name": "C", "last_name": "D", "type": "AUT_LOCALE", "demo_role": None, "password": make_password("x")},
            ],
        }
        appliquer_comptes(donnees)
        assert User.objects.get(pk="aaaaaaaa-0000-0000-0000-0000000000d1").demo_role == "AUT_LOCALE"
        assert User.objects.get(pk="aaaaaaaa-0000-0000-0000-0000000000d2").demo_role is None

    def test_synchronisation_deux_passes_production_puis_demo(self, monkeypatch, settings):
        settings.SATELLITE_CENTRAL_URL = "https://central.test"
        settings.SATELLITE_ID = "00000000-0000-0000-0000-000000000001"
        settings.SATELLITE_EMAIL = "sat@service.assista-crise.local"
        settings.SATELLITE_PASSWORD = "x"
        demandees = []

        class Reponse:
            def __init__(self, data): self._data = data
            def raise_for_status(self): pass
            def json(self): return self._data

        def faux_get(url, headers=None, **kwargs):
            demandees.append((url.rsplit("/", 2)[-2], (headers or {}).get("X-Environment")))
            return Reponse({"institution": {}, "comptes": []} if url.endswith("/comptes/") else {})

        monkeypatch.setattr("core.management.commands.synchroniser_entrant.requests.post", lambda *a, **k: Reponse({"access": "j"}))
        monkeypatch.setattr("core.management.commands.synchroniser_entrant.requests.get", faux_get)

        call_command("synchroniser_entrant")

        assert demandees == [("comptes", None), ("donnees", "PROD"), ("donnees", "DEMO")]
