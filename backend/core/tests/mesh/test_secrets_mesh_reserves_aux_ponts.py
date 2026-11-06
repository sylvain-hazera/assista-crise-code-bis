"""Les endpoints qui livrent un secret mesh en clair ne sont plus ouverts à tout compte connecté.

Avant le 07/11/2026, `get_permissions` de ces vues ne restreignait que create/update/destroy et
laissait tout le reste sur `IsAuthenticated` : **n'importe quel citoyen inscrit** pouvait lire le
mot de passe MQTT du broker de l'institution, la clé privée X25519 de ses companions et les PSK
de ses canaux -- donc se faire passer pour une passerelle et déchiffrer son trafic radio.

Ces endpoints doivent exister (un pont ne peut pas parler le protocole sans ces secrets), d'où
une permission dédiée plutôt qu'une suppression : core/permissions.py:EstComptePont.
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import (
    CanalMeshCore, CanalMeshtastic, CompagnonMeshCore, CompagnonMeshtastic, Institution,
    InstitutionType, ProvisionCanalMeshCore, Satellite, StatutEnrolementSatellite, Team,
)


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie Secrets", type=itype)


@pytest.fixture
def compagnon_meshtastic(db, institution):
    return CompagnonMeshtastic.objects.create(
        nom="Pont Gaulix", node_num=0x4000, institution=institution,
        mqtt_username="passerelle", mqtt_password="secret-du-broker", actif=True,
    )


@pytest.fixture
def compagnon_meshcore(db, institution):
    return CompagnonMeshCore.objects.create(nom="Companion", connexion_type="TCP")


@pytest.fixture
def canal_meshtastic(db, compagnon_meshtastic):
    return CanalMeshtastic.objects.create(
        nom="Fr_EMCOM", psk_hex="ab" * 16, compagnon=compagnon_meshtastic, actif=True,
    )


@pytest.fixture
def canal_meshcore(db, institution):
    equipe = Team.objects.create(name="Equipe secrets", institution=institution)
    return CanalMeshCore.objects.create(equipe=equipe, nom="Equipe", cle_partagee_hex="cd" * 16)


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _urls(compagnon_meshtastic, compagnon_meshcore):
    """Les cinq endroits où un secret sort en clair."""
    return [
        reverse('compagnonmeshtastic-actifs-avec-identifiants'),
        reverse('compagnonmeshtastic-avec-cle-privee', args=[compagnon_meshtastic.id]),
        reverse('canalmeshtastic-avec-cle'),
        reverse('compagnonmeshcore-canaux-a-provisionner', args=[compagnon_meshcore.id]),
        reverse('compagnonmeshcore-canaux-pour-decodage-logiciel', args=[compagnon_meshcore.id]),
    ]


@pytest.mark.django_db
class TestRefus:

    def test_un_citoyen_inscrit_ne_lit_aucun_secret(self, create_user, compagnon_meshtastic,
                                                    compagnon_meshcore, canal_meshtastic, canal_meshcore):
        """LE test de cette correction : c'était exactement le trou."""
        citoyen = create_user(username="citoyen-secrets@x.fr", email="citoyen-secrets@x.fr",
                              type="UTIL_SIMPLE")
        client = _client(citoyen)
        for url in _urls(compagnon_meshtastic, compagnon_meshcore):
            assert client.get(url).status_code == 403, url

    def test_un_acteur_institutionnel_non_plus(self, create_user, institution, compagnon_meshtastic,
                                               compagnon_meshcore):
        """Une mairie n'a pas besoin des clés privées de ses passerelles pour travailler, et
        laisser passer « institutionnel » rendrait le secret lisible par chaque agent."""
        agent = create_user(username="agent-secrets@x.fr", email="agent-secrets@x.fr",
                            type="AUT_LOCALE", institution=institution)
        client = _client(agent)
        for url in _urls(compagnon_meshtastic, compagnon_meshcore):
            assert client.get(url).status_code == 403, url

    def test_un_admin_de_demonstration_non_plus(self, create_user, compagnon_meshtastic,
                                                compagnon_meshcore):
        """Rôle RÉEL, pas effectif : un demo_role=ADMIN prêté le temps d'une démonstration ne
        donne pas les clés du réseau radio réel (même choix que core/grafana.py)."""
        faux_admin = create_user(username="demo-secrets@x.fr", email="demo-secrets@x.fr",
                                 type="UTIL_SIMPLE", demo_role="ADMIN")
        client = _client(faux_admin)
        for url in _urls(compagnon_meshtastic, compagnon_meshcore):
            assert client.get(url, HTTP_X_ENVIRONMENT="DEMO").status_code == 403, url

    def test_un_anonyme_non_plus(self, compagnon_meshtastic, compagnon_meshcore):
        client = APIClient()
        for url in _urls(compagnon_meshtastic, compagnon_meshcore):
            assert client.get(url).status_code in (401, 403), url

    def test_le_message_dit_quoi_faire(self, create_user, compagnon_meshtastic):
        citoyen = create_user(username="citoyen2-secrets@x.fr", email="citoyen2-secrets@x.fr",
                              type="UTIL_SIMPLE")
        reponse = _client(citoyen).get(reverse('compagnonmeshtastic-actifs-avec-identifiants'))
        assert "marquer_compte_pont" in str(reponse.data)


@pytest.mark.django_db
class TestAutorises:

    def test_un_compte_de_pont_marque_lit_les_secrets(self, create_user, compagnon_meshtastic,
                                                      compagnon_meshcore, canal_meshtastic):
        pont = create_user(username="pont-secrets@x.fr", email="pont-secrets@x.fr",
                           type="UTIL_SIMPLE", compte_service_pont=True)
        client = _client(pont)
        for url in _urls(compagnon_meshtastic, compagnon_meshcore):
            assert client.get(url).status_code == 200, url

        # Et le secret sort bien : la permission protège, elle ne casse pas la fonction.
        identifiants = client.get(reverse('compagnonmeshtastic-actifs-avec-identifiants')).data
        assert identifiants[0]["mqtt_password"] == "secret-du-broker"
        cles = client.get(reverse('canalmeshtastic-avec-cle')).data
        assert cles[0]["psk_hex"] == "ab" * 16

    def test_le_compte_de_service_d_un_satellite_approuve_aussi(self, create_user, institution,
                                                                compagnon_meshtastic, compagnon_meshcore):
        """Son pont local lit les mêmes endpoints : aucun marquage à faire en plus de
        l'enrôlement, sinon chaque satellite validé demanderait une intervention manuelle."""
        compte = create_user(username="sat-secrets@x.fr", email="sat-secrets@x.fr",
                             type="UTIL_SIMPLE", institution=institution)
        Satellite.objects.create(institution=institution, nom="poste-secrets", profil="FULL",
                                 statut_enrolement=StatutEnrolementSatellite.APPROUVE,
                                 compte_service=compte)
        client = _client(compte)
        for url in _urls(compagnon_meshtastic, compagnon_meshcore):
            assert client.get(url).status_code == 200, url

    def test_un_satellite_pas_encore_approuve_est_refuse(self, create_user, institution,
                                                         compagnon_meshtastic, compagnon_meshcore):
        compte = create_user(username="sat-attente@x.fr", email="sat-attente@x.fr",
                             type="UTIL_SIMPLE", institution=institution)
        Satellite.objects.create(institution=institution, nom="poste-attente", profil="FULL",
                                 statut_enrolement=StatutEnrolementSatellite.EN_ATTENTE,
                                 compte_service=compte)
        client = _client(compte)
        for url in _urls(compagnon_meshtastic, compagnon_meshcore):
            assert client.get(url).status_code == 403, url

    def test_un_administrateur_reel_aussi(self, create_user, compagnon_meshtastic, compagnon_meshcore):
        """Pour le diagnostic : un administrateur doit pouvoir vérifier ce que le pont reçoit."""
        admin = create_user(username="admin-secrets@x.fr", email="admin-secrets@x.fr", type="ADMIN")
        client = _client(admin)
        for url in _urls(compagnon_meshtastic, compagnon_meshcore):
            assert client.get(url).status_code == 200, url


@pytest.mark.django_db
class TestCeQuiResteOuvert:
    """La correction ne doit pas emporter les endpoints que le pont utilise sans secret, ni les
    résumés faits exprès pour l'interface."""

    def test_le_resume_sans_identifiants_reste_ouvert(self, create_user, compagnon_meshtastic):
        citoyen = create_user(username="citoyen3-secrets@x.fr", email="citoyen3-secrets@x.fr",
                              type="UTIL_SIMPLE")
        reponse = _client(citoyen).get(reverse('compagnonmeshtastic-envoyables'))
        assert reponse.status_code == 200
        assert "mqtt_password" not in str(reponse.data)

    def test_la_liste_des_canaux_ne_contient_pas_la_psk(self, create_user, institution, canal_meshtastic):
        """`psk_hex` est write_only : la sérialisation normale ne l'a jamais exposée, c'est
        `avec-cle` qui le faisait."""
        agent = create_user(username="agent2-secrets@x.fr", email="agent2-secrets@x.fr",
                            type="AUT_LOCALE", institution=institution)
        reponse = _client(agent).get(reverse('canalmeshtastic-list'))
        assert reponse.status_code == 200
        assert "psk_hex" not in str(reponse.data)


@pytest.mark.django_db
class TestCommandeDeMarquage:
    """Le marquage est hors API, exprès : un compte qui lit tous les secrets radio ne doit pas
    pouvoir être fabriqué par une requête HTTP."""

    def _appeler(self, *args):
        from io import StringIO
        from django.core.management import call_command
        sortie = StringIO()
        call_command('marquer_compte_pont', *args, stdout=sortie)
        return sortie.getvalue()

    def test_marque_puis_retire(self, create_user):
        compte = create_user(username="pont-cmd@x.fr", email="pont-cmd@x.fr", type="UTIL_SIMPLE")
        assert not compte.compte_service_pont

        self._appeler("pont-cmd@x.fr")
        compte.refresh_from_db()
        assert compte.compte_service_pont

        self._appeler("pont-cmd@x.fr", "--retirer")
        compte.refresh_from_db()
        assert not compte.compte_service_pont

    def test_est_idempotente(self, create_user):
        create_user(username="pont-idem@x.fr", email="pont-idem@x.fr", type="UTIL_SIMPLE")
        self._appeler("pont-idem@x.fr")
        assert "rien à faire" in self._appeler("pont-idem@x.fr")

    def test_refuse_une_adresse_inconnue(self):
        from django.core.management.base import CommandError
        with pytest.raises(CommandError):
            self._appeler("personne@nulle-part.fr")

    def test_avertit_quand_aucun_compte_n_est_autorise(self, db):
        """Sans cet avertissement, on peut croire la configuration faite alors que le relais
        radio est arrêté."""
        sortie = self._appeler("--lister")
        assert "Aucun compte de service de pont" in sortie

    def test_liste_les_satellites_autorises_d_office(self, create_user, institution):
        compte = create_user(username="sat-liste@x.fr", email="sat-liste@x.fr",
                             type="UTIL_SIMPLE", institution=institution)
        Satellite.objects.create(institution=institution, nom="poste-liste", profil="FULL",
                                 statut_enrolement=StatutEnrolementSatellite.APPROUVE,
                                 compte_service=compte)
        sortie = self._appeler("--lister")
        assert "poste-liste" in sortie
        assert "aucun marquage requis" in sortie
