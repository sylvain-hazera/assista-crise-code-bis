"""Cartographie du réseau MeshCore public : import depuis CoreScope, puis service à la carte.

Trois décisions sont verrouillées ici, et aucune des trois ne se devine à la lecture du code :

1. **Les companions ne sont PAS importés.** Un companion est l'appareil personnel de quelqu'un,
   et sa position est très souvent son domicile. L'instance publique les sert (707 sur
   meshstats.serveurperso.in au 11/11/2026) ; nous n'en republions aucun. Le test vaut garde :
   si quelqu'un ajoute `companion` à `ROLES` pour « avoir plus de points », il casse.
2. **Un nom préfixé 🚫 est un refus d'affichage**, et il est honoré de notre côté aussi — une
   instance mal configurée ne doit pas nous faire republier ce que son opérateur a caché.
3. **La taille de hash est servie à l'interface.** Elle décide de ce qu'on peut conclure des
   chemins d'un nœud : à un octet, un préfixe n'a que 256 valeurs, et les sauts de ce nœud ne
   sont pas une preuve de topologie. Une carte qui la cache laisse croire le contraire.

La pagination est testée sur `has_more`, et non sur `total`, parce que l'instance renvoie dans
`total` la taille de la PAGE : s'y fier n'importerait que les 200 premiers nœuds, en silence.
"""
from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.test import APIClient

from core.management.commands.importer_cartographie_meshcore import ROLES
from core.models import (
    Environment, NoeudPublicMeshCore, NoeudUtilisateurMeshtastic,
)

INSTANCE = "https://meshstats.exemple.invalide"
URL_LISTE = "/api/noeuds-publics-meshcore/"
URL_GEOJSON = "/api/noeuds-publics-meshcore/geojson/"
URL_RESUME = "/api/noeuds-publics-meshcore/resume/"


def noeud_api(cle, nom="Relais", role="repeater", lat=48.85, lon=2.35, **extra):
    """Une ligne de /api/nodes telle que CoreScope la sert."""
    charge = {
        "public_key": cle, "name": nom, "role": role, "lat": lat, "lon": lon,
        "first_seen": "2026-10-01T08:00:00Z", "last_seen": "2026-11-11T07:30:00Z",
        "relay_active": True, "relay_count_24h": 42,
        "coverage_score": 0.71, "redundancy_score": 0.3, "bridge_score": 0.5,
        "usefulness_score": 0.64, "usefulness_grade": "B", "hash_size": 2,
    }
    charge.update(extra)
    return charge


class FausseReponse:
    def __init__(self, charge):
        self._charge = charge

    def raise_for_status(self):
        return None

    def json(self):
        return self._charge


class FauxClient:
    """Un faux `requests.Session` qui répond par rôle, et enregistre ce qu'on lui a demandé."""

    def __init__(self, par_role):
        self.par_role = par_role
        self.appels = []
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def update(self, *_args, **_kw):
        return None

    def get(self, url, params=None, timeout=None):
        params = params or {}
        self.appels.append(params)
        pages = self.par_role.get(params.get('role'), [])
        indice = sum(1 for a in self.appels[:-1] if a.get('role') == params.get('role'))
        if indice >= len(pages):
            return FausseReponse({"nodes": [], "has_more": False})
        return FausseReponse(pages[indice])


def importer(par_role, **options):
    sortie = StringIO()
    faux = FauxClient(par_role)
    faux.headers = {}
    with patch('core.management.commands.importer_cartographie_meshcore.requests.Session',
               return_value=faux):
        call_command('importer_cartographie_meshcore', instance=INSTANCE, stdout=sortie,
                     **options)
    return sortie.getvalue(), faux


@pytest.mark.django_db
class TestImport:

    def test_les_companions_ne_sont_jamais_demandes(self):
        """La décision la plus importante du module, et elle est invisible à la lecture : on
        n'interroge que les rôles qui désignent une INFRASTRUCTURE. Un companion est l'appareil
        de quelqu'un, souvent chez lui."""
        assert ROLES == ("repeater", "room")
        assert "companion" not in ROLES
        _, faux = importer({})
        roles_demandes = {a.get('role') for a in faux.appels}
        assert roles_demandes == {"repeater", "room"}

    def test_un_repeteur_positionne_est_importe_avec_ses_scores(self):
        importer({"repeater": [{"nodes": [noeud_api("aa" * 32)], "has_more": False}]})
        noeud = NoeudPublicMeshCore.objects.get(pubkey_hex="aa" * 32)
        assert noeud.instance == INSTANCE
        assert noeud.role == "repeater"
        assert noeud.relais_24h == 42
        assert noeud.taille_hash == 2
        # Les scores sont REPRIS, pas recalculés : ils viennent d'un volume d'observations
        # que nous n'avons pas.
        assert noeud.score_couverture == pytest.approx(0.71)
        assert noeud.note_utilite == "B"
        assert noeud.location.x == pytest.approx(2.35)
        assert noeud.location.y == pytest.approx(48.85)

    def test_un_noeud_sans_position_n_est_pas_importe(self):
        sortie, _ = importer({"repeater": [
            {"nodes": [noeud_api("bb" * 32, lat=None, lon=None)], "has_more": False}]})
        assert not NoeudPublicMeshCore.objects.exists()
        assert "sans position        : 1" in sortie

    def test_un_nom_prefixe_interdit_est_un_refus_d_affichage_honore(self):
        """L'opérateur a renommé son nœud pour ne pas être affiché. CoreScope le retire déjà de
        ses réponses ; on le refait, parce qu'une instance mal configurée ne doit pas nous faire
        republier ce que quelqu'un a demandé à cacher."""
        sortie, _ = importer({"repeater": [
            {"nodes": [noeud_api("cc" * 32, nom="\U0001F6AB prive")], "has_more": False}]})
        assert not NoeudPublicMeshCore.objects.exists()
        assert "masqués par leur nom : 1" in sortie

    def test_une_cle_tronquee_est_ignoree(self):
        """Un préfixe n'est pas une identité : l'importer créerait une ligne qu'aucun chemin ne
        pourra jamais confirmer."""
        importer({"repeater": [{"nodes": [noeud_api("dd" * 4)], "has_more": False}]})
        assert not NoeudPublicMeshCore.objects.exists()

    def test_la_pagination_suit_has_more_et_non_total(self):
        """`total` vaut la taille de la page dans les réponses de l'instance. S'y fier
        arrêterait l'import à la première page, sans rien dire."""
        page1 = {"nodes": [noeud_api(f"{i:02x}" * 32) for i in range(1, 4)],
                 "total": 3, "has_more": True}
        page2 = {"nodes": [noeud_api("ee" * 32)], "total": 1, "has_more": False}
        importer({"repeater": [page1, page2]})
        assert NoeudPublicMeshCore.objects.count() == 4

    def test_l_import_est_idempotent(self):
        pages = {"repeater": [{"nodes": [noeud_api("aa" * 32, nom="Avant")], "has_more": False}]}
        importer(pages)
        sortie, _ = importer(
            {"repeater": [{"nodes": [noeud_api("aa" * 32, nom="Apres")], "has_more": False}]})
        assert NoeudPublicMeshCore.objects.count() == 1
        assert NoeudPublicMeshCore.objects.get().nom == "Apres"
        assert "mis à jour           : 1" in sortie

    def test_compter_n_ecrit_rien_mais_dit_ce_qu_il_y_aurait(self):
        sortie, _ = importer(
            {"repeater": [{"nodes": [noeud_api("aa" * 32)], "has_more": False}]},
            compter=True)
        assert not NoeudPublicMeshCore.objects.exists()
        assert "nœuds lus            : 1" in sortie
        assert "rien n'a été écrit" in sortie

    def test_la_repartition_des_tailles_de_hash_est_annoncee_avec_sa_consequence(self):
        """Un chiffre sans sa conséquence ne sert à rien : à un octet, les sauts de ce nœud ne
        sont pas une preuve de topologie, et c'est cela qu'il faut lire."""
        sortie, _ = importer({"repeater": [{"nodes": [
            noeud_api("aa" * 32, hash_size=1), noeud_api("bb" * 32, hash_size=2),
        ], "has_more": False}]})
        assert "1 octet(s) : 1" in sortie
        assert "pas servir de preuve de topologie" in sortie

    def test_une_instance_injoignable_echoue_fort(self):
        """Mieux vaut une erreur qu'une table à moitié remplie sans que personne le sache."""
        import requests

        class ClientQuiEchoue(FauxClient):
            def get(self, *_a, **_kw):
                raise requests.RequestException("connexion refusée")

        with patch('core.management.commands.importer_cartographie_meshcore.requests.Session',
                   return_value=ClientQuiEchoue({})):
            with pytest.raises(CommandError, match="Échec de lecture"):
                call_command('importer_cartographie_meshcore', instance=INSTANCE,
                             stdout=StringIO())

    def test_aucune_information_sur_qui_interroge_n_est_envoyee(self):
        """C'est le service de quelqu'un d'autre : il n'a pas à savoir que c'est Assista-Crise,
        ni pour quelle commune, qui regarde sa carte."""
        _, faux = importer({})
        agent = faux.headers.get('User-Agent', '')
        assert agent == 'curl'
        assert 'assista' not in agent.lower()


@pytest.fixture
def operateur(create_user, db):
    """Un porteur de nœud : le droit radio vient du matériel (voir test_acces_radio.py)."""
    utilisateur = create_user(username="porteur-carto@x.fr", email="porteur-carto@x.fr",
                              type="UTIL_SIMPLE")
    NoeudUtilisateurMeshtastic.objects.create(utilisateur=utilisateur, node_num=0xCA01)
    return utilisateur


@pytest.fixture
def trois_noeuds(db):
    NoeudPublicMeshCore.objects.create(
        instance=INSTANCE, pubkey_hex="aa" * 32, nom="Haut relais", role="repeater",
        location=Point(2.35, 48.85),
        relais_actif=True, score_utilite=0.9, note_utilite="A", taille_hash=2,
        date_import=timezone.now(), environment=Environment.PROD)
    NoeudPublicMeshCore.objects.create(
        instance=INSTANCE, pubkey_hex="bb" * 32, nom="Salle", role="room",
        location=Point(2.4, 48.9),
        relais_actif=False, score_utilite=0.2, note_utilite="D", taille_hash=1,
        date_import=timezone.now(), environment=Environment.PROD)
    NoeudPublicMeshCore.objects.create(
        instance=INSTANCE, pubkey_hex="cc" * 32, nom="Sans position", role="repeater",
        location=None, date_import=timezone.now(), environment=Environment.PROD)


@pytest.mark.django_db
class TestServiceALaCarte:

    def test_un_compte_sans_droit_radio_n_y_accede_pas(self, create_user, trois_noeuds):
        citoyen = create_user(username="citoyen-carto@x.fr", email="citoyen-carto@x.fr",
                              type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=citoyen)
        assert client.get(URL_GEOJSON).status_code == 403

    def test_le_geojson_ne_contient_que_des_noeuds_positionnes(self, operateur, trois_noeuds):
        """Une entité sans coordonnées dans une FeatureCollection casse la carte côté client."""
        client = APIClient()
        client.force_authenticate(user=operateur)
        reponse = client.get(URL_GEOJSON)
        assert reponse.status_code == 200
        assert reponse.data['type'] == "FeatureCollection"
        noms = {f['properties']['nom'] for f in reponse.data['features']}
        assert noms == {"Haut relais", "Salle"}
        for feature in reponse.data['features']:
            assert len(feature['geometry']['coordinates']) == 2

    def test_la_taille_de_hash_est_servie_avec_chaque_point(self, operateur, trois_noeuds):
        """Elle décide de ce qu'on peut conclure des chemins de ce nœud. La cacher laisserait
        lire une topologie là où il n'y a qu'un préfixe de 256 valeurs."""
        client = APIClient()
        client.force_authenticate(user=operateur)
        par_nom = {f['properties']['nom']: f['properties']
                   for f in client.get(URL_GEOJSON).data['features']}
        assert par_nom["Salle"]['taille_hash'] == 1
        assert par_nom["Haut relais"]['taille_hash'] == 2

    def test_le_filtre_actifs_ne_garde_que_les_relais_qui_relaient(self, operateur, trois_noeuds):
        client = APIClient()
        client.force_authenticate(user=operateur)
        reponse = client.get(URL_GEOJSON, {'actifs': '1'})
        assert [f['properties']['nom'] for f in reponse.data['features']] == ["Haut relais"]

    def test_le_filtre_role_fonctionne(self, operateur, trois_noeuds):
        client = APIClient()
        client.force_authenticate(user=operateur)
        reponse = client.get(URL_GEOJSON, {'role': 'room'})
        assert [f['properties']['nom'] for f in reponse.data['features']] == ["Salle"]

    def test_le_resume_dit_d_ou_vient_la_carte_et_ce_qu_elle_contient(self, operateur,
                                                                      trois_noeuds):
        """Une carte sans sa provenance ni sa date se lit comme un fait. Celle-ci est l'état
        d'une instance tierce à un instant donné."""
        client = APIClient()
        client.force_authenticate(user=operateur)
        reponse = client.get(URL_RESUME)
        assert reponse.status_code == 200
        assert reponse.data['instances'] == [INSTANCE]
        assert reponse.data['total'] == 2
        assert reponse.data['par_role'] == {"repeater": 1, "room": 1}
        assert reponse.data['actifs'] == 1
        assert reponse.data['par_taille_hash'] == {"1": 1, "2": 1}

    def test_la_liste_est_en_lecture_seule(self, operateur, trois_noeuds):
        """Ces lignes s'importent, elles ne se saisissent pas : une écriture à la main créerait
        une divergence avec l'instance d'origine que rien ne signalerait."""
        client = APIClient()
        client.force_authenticate(user=operateur)
        reponse = client.post(URL_LISTE, {'pubkey_hex': 'ff' * 32}, format='json')
        assert reponse.status_code in (403, 405)
