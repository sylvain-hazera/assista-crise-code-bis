"""Clés des canaux d'équipe Meshtastic (22/10/2026) : envoyées en base64 comme l'application
Meshtastic les demande (l'hexadécimal y était relu comme une autre clé), noms limités aux 11
octets du firmware, et envoyées par la radio de l'institution de l'équipe."""
import base64

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import (
    CompagnonMeshtastic,
    Institution,
    InstitutionType,
    MessageMeshtasticLog,
    NoeudUtilisateurMeshtastic,
    Team,
)
from core.views import _nom_canal_meshtastic_equipe


@pytest.fixture
def loire(db):
    itype, _ = InstitutionType.objects.get_or_create(code="DEPARTEMENT", defaults={"libelle": "Département"})
    return Institution.objects.create(nom="Conseil départemental - Loire", type=itype)


@pytest.fixture
def admin(create_user):
    client = APIClient()
    client.force_authenticate(user=create_user(username="admin-cles@test.fr", email="admin-cles@test.fr", type="ADMIN"))
    return client


@pytest.mark.django_db
def test_cle_envoyee_en_base64_par_la_radio_de_l_institution(create_user, admin, loire):
    CompagnonMeshtastic.objects.create(nom="Bureau", node_num=1, principal=True)
    radio_loire = CompagnonMeshtastic.objects.create(nom="Satellite Loire", node_num=2, institution=loire)
    fred = create_user(username="fred@loire.fr", email="fred@loire.fr", type="AUT_LOCALE")
    NoeudUtilisateurMeshtastic.objects.create(utilisateur=fred, node_num=3030487139)
    equipe = Team.objects.create(name="CAI", institution=loire)
    equipe.members.add(fred)

    reponse = admin.post(reverse('team-provisionner-canal-meshtastic', args=[equipe.id]))

    assert reponse.status_code == 200, reponse.data
    message = MessageMeshtasticLog.objects.get(contact_node_num=3030487139)
    canal = equipe.canal_meshtastic
    cle = base64.b64encode(bytes.fromhex(canal.psk_hex)).decode()
    assert message.contenu == f"{cle} - EquipeCAI"
    assert len(cle) == 24 and cle.endswith("==")
    assert message.compagnon == radio_loire                       # pas Bureau, hors de portée


@pytest.mark.parametrize("nom_equipe, attendu", [
    ("CAI", "EquipeCAI"),
    ("Les Cuves Pompes", "LesCuvesPom"),
    ("Équipe Voirie — Points de transit", "EquipeVoiri"),
])
def test_nom_de_canal_dans_la_limite_du_firmware(nom_equipe, attendu):
    nom = _nom_canal_meshtastic_equipe(Team(name=nom_equipe))
    assert nom == attendu and len(nom.encode("utf-8")) <= 11


@pytest.mark.django_db
def test_canal_cree_a_la_main_nom_trop_long_refuse(admin):
    reponse = admin.post(reverse('canalmeshtastic-list'), {"nom": "EquipeLesCuves", "psk_hex": "00" * 16}, format="json")
    assert reponse.status_code == 400
    assert "nom" in reponse.data
