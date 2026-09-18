"""Vue de supervision inter-collectivités (communes voisines -> préfecture) — voir le cadrage
"Chantier B" section 5 et SatelliteViewSet.supervision/_communes_visibles_supervision. Le
référentiel Commune ne conserve que des centroïdes (pas de géométrie précise) : l'adjacence
"limitrophe" entre communes est approximée par distance de centroïde, restreinte au même
département — voir SATELLITE_SUPERVISION_RAYON_LIMITROPHE_KM."""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AuditAction, AuditLog, Commune, ContactInstitution, Crisis, ImplicationInstitution, Institution,
    InstitutionType, Satellite, StatutImplication, TypeImplication,
)


def _make_commune(code, departement_code, epci_code, region_code, lat, lon):
    return Commune.objects.create(
        code=code, nom=f"Commune {code}", departement_code=departement_code, epci_code=epci_code,
        region_code=region_code, centre_latitude=lat, centre_longitude=lon, population=1000,
    )


def _make_institution(code_type, nom, commune_code):
    itype, _ = InstitutionType.objects.get_or_create(code=code_type, defaults={'libelle': code_type})
    return Institution.objects.create(nom=nom, type=itype, commune_code=commune_code)


def _client_for(create_user, institution, email):
    user = create_user(username=email, email=email, type='AUT_LOCALE', institution=institution)
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def communes():
    return {
        # ~6.7 km de "a" (même département/EPCI) — doit être vue comme "limitrophe".
        "a": _make_commune("88001", "88", "EPCI88", "R88", 48.0, 6.0),
        "b": _make_commune("88002", "88", "EPCI88", "R88", 48.05, 6.05),
        # ~55 km de "a", même département mais autre EPCI — hors rayon limitrophe.
        "c": _make_commune("88003", "88", "EPCI88X", "R88", 48.5, 6.0),
        # Autre département/région entièrement.
        "d": _make_commune("99001", "99", "EPCI99", "R99", 10.0, 10.0),
    }


@pytest.fixture
def institution_a(communes):
    return _make_institution("MAIRIE", "Mairie A", communes["a"].code)


@pytest.fixture
def institution_b(communes):
    return _make_institution("MAIRIE", "Mairie B", communes["b"].code)


@pytest.fixture
def institution_c(communes):
    return _make_institution("MAIRIE", "Mairie C", communes["c"].code)


@pytest.fixture
def institution_d(communes):
    return _make_institution("MAIRIE", "Mairie D", communes["d"].code)


@pytest.fixture
def institution_epci(communes):
    return _make_institution("EPCI", "EPCI 88", communes["a"].code)


@pytest.fixture
def institution_departement(communes):
    return _make_institution("SDIS", "SDIS 88", communes["a"].code)


@pytest.fixture
def crisis_a(communes):
    return Crisis.objects.create(
        name="Crise commune A", type="INONDATION", location="POINT (6.0 48.0)",
        zone_communes=[communes["a"].code],
    )


@pytest.fixture
def implication_a(crisis_a, institution_a):
    return ImplicationInstitution.objects.create(
        crise=crisis_a, institution=institution_a,
        type_implication=TypeImplication.ACTEUR, statut=StatutImplication.VALIDEE,
    )


@pytest.mark.django_db
class TestVisibiliteSupervision:

    def test_commune_voisine_dans_le_rayon_voit_la_crise(self, create_user, institution_b, implication_a, crisis_a):
        client, _ = _client_for(create_user, institution_b, "voisine-b@test.fr")
        response = client.get(reverse('satellite-supervision'))
        assert response.status_code == status.HTTP_200_OK
        assert any(r["crise_id"] == str(crisis_a.id) for r in response.data)

    def test_commune_hors_rayon_meme_departement_ne_voit_rien(self, create_user, institution_c, implication_a, crisis_a):
        client, _ = _client_for(create_user, institution_c, "lointaine-c@test.fr")
        response = client.get(reverse('satellite-supervision'))
        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_autre_departement_ne_voit_rien(self, create_user, institution_d, implication_a, crisis_a):
        client, _ = _client_for(create_user, institution_d, "autre-dept-d@test.fr")
        response = client.get(reverse('satellite-supervision'))
        assert response.data == []

    def test_epci_voit_toutes_ses_communes_membres(self, create_user, institution_epci, implication_a, crisis_a):
        client, _ = _client_for(create_user, institution_epci, "epci-88@test.fr")
        response = client.get(reverse('satellite-supervision'))
        assert any(r["crise_id"] == str(crisis_a.id) for r in response.data)

    def test_departement_voit_meme_au_dela_du_rayon_limitrophe(
        self, create_user, institution_departement, implication_a, crisis_a
    ):
        # SDIS 88 est rattaché à la commune A elle-même, donc ce test ne prouve pas grand-chose
        # par distance — mais confirme au moins l'accès de niveau département de base.
        client, _ = _client_for(create_user, institution_departement, "sdis-88@test.fr")
        response = client.get(reverse('satellite-supervision'))
        assert any(r["crise_id"] == str(crisis_a.id) for r in response.data)

    def test_admin_voit_tout_sans_institution(self, create_user, implication_a, crisis_a):
        admin = create_user(username="admin-supervision@test.fr", email="admin-supervision@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.get(reverse('satellite-supervision'))
        assert any(r["crise_id"] == str(crisis_a.id) for r in response.data)


@pytest.mark.django_db
class TestContenuSupervision:

    def test_institution_non_mairie_epci_exclue_des_resultats(self, create_user, institution_a, crisis_a, communes):
        sdis = _make_institution("SDIS", "SDIS acteur", communes["a"].code)
        ImplicationInstitution.objects.create(
            crise=crisis_a, institution=sdis, type_implication=TypeImplication.ACTEUR, statut=StatutImplication.VALIDEE,
        )
        client, _ = _client_for(create_user, institution_a, "mairie-a-contenu@test.fr")
        response = client.get(reverse('satellite-supervision'))
        assert not any(r["institution_id"] == str(sdis.id) for r in response.data)

    def test_implication_en_attente_exclue(self, create_user, institution_a, crisis_a, communes):
        autre = _make_institution("MAIRIE", "Mairie en attente", communes["a"].code)
        ImplicationInstitution.objects.create(
            crise=crisis_a, institution=autre, type_implication=TypeImplication.ACTEUR, statut=StatutImplication.EN_ATTENTE,
        )
        client, _ = _client_for(create_user, institution_a, "mairie-a-attente@test.fr")
        response = client.get(reverse('satellite-supervision'))
        assert not any(r["institution_id"] == str(autre.id) for r in response.data)

    def test_crise_cloturee_exclue(self, create_user, institution_a, crisis_a, implication_a):
        crisis_a.end_date = timezone.now()
        crisis_a.save(update_fields=['end_date'])
        client, _ = _client_for(create_user, institution_a, "mairie-a-cloture@test.fr")
        response = client.get(reverse('satellite-supervision'))
        assert response.data == []

    def test_satellite_none_donne_etat_null_et_pas_de_contact(
        self, create_user, institution_a, institution_b, implication_a, crisis_a
    ):
        # Vue depuis une commune voisine (institution_b), pas depuis institution_a elle-même —
        # sinon le contact du viewer, lui-même membre d'institution_a, fausserait le compte.
        client, _ = _client_for(create_user, institution_b, "voisine-b-sansat@test.fr")
        response = client.get(reverse('satellite-supervision'))
        ligne = next(r for r in response.data if r["institution_id"] == str(institution_a.id))
        assert ligne["satellite_etat"] is None
        assert ligne["contacts_secours"] == []

    def test_satellite_actif_ne_montre_pas_les_contacts(self, create_user, institution_a, implication_a, crisis_a):
        Satellite.objects.create(
            institution=institution_a, nom="Sat A", profil="GW", statut_enrolement="APPROUVE",
            dernier_contact=timezone.now(),
        )
        ContactInstitution.objects.create(
            institution=institution_a, utilisateur=create_user(username="contact-a@test.fr", email="contact-a@test.fr"),
            actif=True, fonction="Maire",
        )
        client, _ = _client_for(create_user, institution_a, "mairie-a-actif@test.fr")
        response = client.get(reverse('satellite-supervision'))
        ligne = next(r for r in response.data if r["institution_id"] == str(institution_a.id))
        assert ligne["satellite_etat"] == "ACTIF"
        assert ligne["contacts_secours"] == []

    def test_satellite_perdu_expose_les_contacts_de_secours(
        self, create_user, institution_a, institution_b, implication_a, crisis_a
    ):
        Satellite.objects.create(
            institution=institution_a, nom="Sat A", profil="GW", statut_enrolement="APPROUVE",
            dernier_contact=timezone.now() - datetime.timedelta(hours=5),
        )
        contact_user = create_user(
            username="contact-perdu@test.fr", email="contact-perdu@test.fr",
            first_name="Jean", last_name="Dupont", phone_number="0600000000",
        )
        ContactInstitution.objects.create(
            institution=institution_a, utilisateur=contact_user, actif=True, fonction="Maire", contact_principal=True,
        )
        # Vue depuis une commune voisine, pas depuis institution_a elle-même (voir commentaire
        # du test précédent).
        client, _ = _client_for(create_user, institution_b, "voisine-b-perdu@test.fr")
        response = client.get(reverse('satellite-supervision'))
        ligne = next(r for r in response.data if r["institution_id"] == str(institution_a.id))
        assert ligne["satellite_etat"] == "PERDU"
        assert len(ligne["contacts_secours"]) == 1
        assert ligne["contacts_secours"][0]["nom"] == "Jean Dupont"
        assert ligne["contacts_secours"][0]["telephone"] == "0600000000"

    def test_derniere_activite_humaine_null_si_aucun_audit_log(
        self, create_user, institution_a, institution_b, implication_a, crisis_a
    ):
        client, _ = _client_for(create_user, institution_b, "voisine-b-sansactivite@test.fr")
        response = client.get(reverse('satellite-supervision'))
        ligne = next(r for r in response.data if r["institution_id"] == str(institution_a.id))
        assert ligne["derniere_activite_humaine"] is None

    def test_derniere_activite_humaine_reflete_le_dernier_audit_log_de_l_institution(
        self, create_user, institution_a, institution_b, implication_a, crisis_a
    ):
        """Distincte de satellite_dernier_contact (synchronisation machine) : la plus récente
        ligne de main courante posée par n'importe quel membre de l'institution, tous objets
        confondus (voir AuditTraceMiddleware, qui journalise même une simple consultation)."""
        action = AuditAction.objects.get(code="LECTURE")
        membre = create_user(username="membre-a@test.fr", email="membre-a@test.fr", institution=institution_a)

        ancien = AuditLog.objects.create(
            utilisateur=membre, institution=institution_a, action=action, objet_type="Crisis",
        )
        ancien.date_action = timezone.now() - datetime.timedelta(hours=3)
        ancien.save(update_fields=["date_action"])

        recent = AuditLog.objects.create(
            utilisateur=membre, institution=institution_a, action=action, objet_type="Crisis",
        )
        recent.date_action = timezone.now() - datetime.timedelta(minutes=10)
        recent.save(update_fields=["date_action"])

        client, _ = _client_for(create_user, institution_b, "voisine-b-activite@test.fr")
        response = client.get(reverse('satellite-supervision'))
        ligne = next(r for r in response.data if r["institution_id"] == str(institution_a.id))

        # response.data (client de test DRF) expose les valeurs Python brutes, pas encore
        # sérialisées en JSON — un datetime reste un datetime, inutile de le reparser.
        assert ligne["derniere_activite_humaine"] is not None
        assert abs((ligne["derniere_activite_humaine"] - recent.date_action).total_seconds()) < 1
