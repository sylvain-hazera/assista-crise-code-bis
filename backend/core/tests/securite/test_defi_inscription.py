"""Création de compte : le contrôle anti-robot (16/11/2026, core/defi_inscription.py).

Demande de Sylvain : « un challenge facile pour des humains en temps de crise mais qui bloque
les robots ». La personne n'a rien à lire ni à résoudre : son navigateur fait un calcul, qui
devient plus long quand les signaux sont ceux d'un robot.
"""
import hashlib
from datetime import timedelta

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from core import defi_inscription as di
from core.crypto_fields import blind_index
from core.models import CompteurInscription, User

URL = "/api/register/"
URL_DEFI = "/api/inscription/defi/"

CHROME_ANDROID = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Mobile Safari/537.36"
SAFARI_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1"
GYMNASE = "203.0.113.7"


@pytest.fixture(autouse=True)
def controle_actif(settings):
    """Rallume le contrôle (coupé pour le reste de la suite, voir conftest.py), avec de petits
    nombres : un vrai défi demanderait des dizaines de milliers d'essais par test."""
    settings.INSCRIPTION_DEFI_ACTIF = True
    settings.INSCRIPTION_DEFI_MAXIMUMS = {di.NORMAL: 50, di.ELEVE: 500, di.FORT: 5000}
    settings.INSCRIPTION_DELAI_MINIMAL = 0


def _client(agent=CHROME_ANDROID, adresse=GYMNASE):
    return APIClient(HTTP_USER_AGENT=agent, HTTP_X_REAL_IP=adresse)


def _resoudre(defi):
    """Ce que fait le navigateur : essayer les nombres un à un."""
    for nombre in range(defi["maximum"] + 1):
        if hashlib.sha256(f"{defi['sel']}{nombre}".encode()).hexdigest() == defi["empreinte"]:
            return {**defi, "nombre": nombre}
    raise AssertionError("défi sans solution")


def _defi(client):
    reponse = client.get(URL_DEFI)
    assert reponse.status_code == 200, reponse.content
    return _resoudre(reponse.json())


def _inscrit(email) -> bool:
    """L'adresse est chiffrée en base : on la retrouve par son index aveugle."""
    return User.objects.filter(email_bidx=blind_index(email)).exists()


def _payload(email, **extra):
    return {"username": email, "email": email, "password": "MotDePasse!2026",
            "first_name": "Jon", "last_name": "Jin", "type": "UTIL_SIMPLE", **extra}


def _inscrire(client, email, **extra):
    return client.post(URL, _payload(email, defi=_defi(client), **extra), format="json")


@pytest.mark.django_db
class TestLeParcoursOrdinaire:
    def test_une_personne_s_inscrit_sans_rien_resoudre_elle_meme(self):
        client = _client()

        defi = client.get(URL_DEFI).json()
        assert defi["niveau"] == di.NORMAL and defi["maximum"] == 50
        reponse = client.post(URL, _payload("habitante@exemple.fr", defi=_resoudre(defi)), format="json")

        assert reponse.status_code == 201, reponse.content
        assert _inscrit("habitante@exemple.fr")

    def test_un_defi_ne_sert_qu_une_fois(self):
        client = _client()
        defi = _defi(client)

        assert client.post(URL, _payload("premier@exemple.fr", defi=defi), format="json").status_code == 201
        rejoue = client.post(URL, _payload("second@exemple.fr", defi=defi), format="json")

        assert rejoue.status_code == 428
        assert rejoue.json()["code"] == "DEFI_REQUIS"
        assert _inscrit("premier@exemple.fr") and not _inscrit("second@exemple.fr")

    def test_une_solution_fausse_ou_un_defi_fabrique_ne_passe_pas(self):
        client = _client()
        defi = _defi(client)

        faux = {**defi, "nombre": (defi["nombre"] + 1) % (defi["maximum"] + 1)}
        assert client.post(URL, _payload("faux@exemple.fr", defi=faux), format="json").status_code == 428

        # Un défi que le serveur n'a pas signé : le robot choisit lui-même un calcul trivial.
        maison = {"sel": "abc", "nombre": 0, "maximum": 0, "emis": defi["emis"], "expire": defi["expire"],
                  "empreinte": hashlib.sha256(b"abc0").hexdigest(), "signature": defi["signature"]}
        assert client.post(URL, _payload("maison@exemple.fr", defi=maison), format="json").status_code == 428
        assert not _inscrit("faux@exemple.fr") and not _inscrit("maison@exemple.fr")

    def test_un_defi_echu_est_a_refaire(self, rf):
        requete = rf.get(URL_DEFI, HTTP_X_REAL_IP=GYMNASE, HTTP_USER_AGENT=CHROME_ANDROID)
        ancien = _resoudre(di.emettre(requete, maintenant=1_000_000))

        reponse = _client().post(URL, _payload("tardif@exemple.fr", defi=ancien), format="json")

        assert reponse.status_code == 428

    def test_le_controle_passe_avant_la_validation_du_formulaire(self):
        """Un robot ne doit pas apprendre qu'une adresse est déjà inscrite sans avoir payé."""
        client = _client()
        assert _inscrire(client, "connue@exemple.fr").status_code == 201

        sans_calcul = client.post(URL, _payload("connue@exemple.fr", defi={"sel": "x"}), format="json")

        assert sans_calcul.status_code == 428            # et non 400 « adresse déjà utilisée »


@pytest.mark.django_db
class TestLesSignauxDurcissentSansRefuser:
    def test_le_champ_piege_rempli_demande_un_calcul_plus_long_puis_accepte(self):
        """Un gestionnaire de mots de passe remplit parfois les champs cachés : la personne ne
        doit pas être refusée, seulement attendre un peu plus."""
        client = _client()

        premier = _inscrire(client, "piege@exemple.fr", site_web="https://exemple.fr")
        assert premier.status_code == 428

        defi = client.get(URL_DEFI).json()
        assert defi["niveau"] == di.ELEVE
        second = client.post(URL, _payload("piege@exemple.fr", defi=_resoudre(defi), site_web="https://exemple.fr"),
                             format="json")
        assert second.status_code == 201, second.content

    def test_un_formulaire_envoye_trop_vite_aussi(self, settings):
        settings.INSCRIPTION_DELAI_MINIMAL = 3
        client = _client()

        assert _inscrire(client, "eclair@exemple.fr").status_code == 428
        assert client.get(URL_DEFI).json()["niveau"] == di.ELEVE
        # Au niveau élevé, c'est le calcul qui fait foi : plus de délai à respecter.
        assert _inscrire(client, "eclair@exemple.fr").status_code == 201

    def test_la_suspicion_ne_touche_que_la_meme_adresse_et_le_meme_navigateur(self):
        _inscrire(_client(), "piege2@exemple.fr", site_web="x")

        assert _client(agent=SAFARI_IPHONE).get(URL_DEFI).json()["niveau"] == di.NORMAL
        assert _client(adresse="198.51.100.4").get(URL_DEFI).json()["niveau"] == di.NORMAL


@pytest.mark.django_db
class TestLeVolume:
    def test_un_gymnase_en_wifi_partage_n_est_pas_bloque(self, settings):
        """Même adresse publique pour tous : le calcul s'allonge, personne n'est refusé."""
        settings.INSCRIPTION_SEUILS_PAR_FAMILLE = {di.ELEVE: 3, di.FORT: 6}
        android = _client()

        for i in range(8):
            assert _inscrire(android, f"sinistre{i}@exemple.fr").status_code == 201, i

        assert android.get(URL_DEFI).json()["niveau"] == di.FORT
        assert all(_inscrit(f"sinistre{i}@exemple.fr") for i in range(8))

    def test_les_iphone_ne_patissent_pas_des_inscriptions_sur_android(self, settings):
        settings.INSCRIPTION_SEUILS_PAR_FAMILLE = {di.ELEVE: 2, di.FORT: 50}
        android = _client()
        for i in range(3):
            _inscrire(android, f"android{i}@exemple.fr")

        assert android.get(URL_DEFI).json()["niveau"] == di.ELEVE
        assert _client(agent=SAFARI_IPHONE).get(URL_DEFI).json()["niveau"] == di.NORMAL

    def test_changer_de_signature_ne_donne_pas_un_compteur_neuf_indefiniment(self, settings):
        """Le compteur par adresse seule rattrape le robot qui se dit chaque fois différent."""
        settings.INSCRIPTION_SEUILS_PAR_ADRESSE = {di.ELEVE: 3, di.FORT: 50}
        for i in range(3):
            _inscrire(_client(agent=f"Robot/{i} Chrome/{100 + i}.0"), f"robot{i}@exemple.fr")

        assert _client(agent="Robot/99 Chrome/199.0").get(URL_DEFI).json()["niveau"] == di.ELEVE

    def test_au_dela_du_plafond_de_l_adresse_plus_rien_ne_passe(self, settings):
        settings.INSCRIPTION_PLAFOND_PAR_ADRESSE = 2
        client = _client()
        defi_d_avance = _defi(client)
        _inscrire(client, "p1@exemple.fr")
        _inscrire(client, "p2@exemple.fr")

        assert client.get(URL_DEFI).status_code == 429
        refus = client.post(URL, _payload("p3@exemple.fr", defi=defi_d_avance), format="json")
        assert refus.status_code == 429
        assert refus.json()["code"] == "TROP_DE_DEMANDES"
        # … pour cette adresse seulement.
        assert _inscrire(_client(adresse="198.51.100.9"), "ailleurs@exemple.fr").status_code == 201

    def test_l_en_tete_que_le_visiteur_ecrit_lui_meme_ne_change_pas_son_compteur(self, settings):
        """X-Forwarded-For commence par ce que le visiteur veut bien y mettre."""
        settings.INSCRIPTION_PLAFOND_PAR_ADRESSE = 1
        _inscrire(_client(), "xff1@exemple.fr")

        tricheur = APIClient(HTTP_USER_AGENT=CHROME_ANDROID, HTTP_X_REAL_IP=GYMNASE,
                             HTTP_X_FORWARDED_FOR="8.8.8.8")
        assert tricheur.get(URL_DEFI).status_code == 429

    def test_un_foyer_en_ipv6_a_un_seul_compteur(self, rf):
        a = rf.get("/", HTTP_X_REAL_IP="2001:db8:1:2:aaaa::1")
        b = rf.get("/", HTTP_X_REAL_IP="2001:db8:1:2:bbbb::2")
        voisin = rf.get("/", HTTP_X_REAL_IP="2001:db8:1:3::1")

        assert di.adresse_comptee(a) == di.adresse_comptee(b) == "2001:db8:1:2::/64"
        assert di.adresse_comptee(voisin) != di.adresse_comptee(a)

    def test_sur_le_reseau_local_chaque_appareil_a_son_compteur(self, rf):
        """Satellite, réseau de la mairie : le serveur voit l'adresse locale (RFC 1918)."""
        assert di.adresse_comptee(rf.get("/", REMOTE_ADDR="192.168.1.20")) == "192.168.1.20"
        assert di.adresse_comptee(rf.get("/", REMOTE_ADDR="192.168.1.21")) == "192.168.1.21"


@pytest.mark.django_db
class TestLesClientsSansDefi:
    def test_l_application_deja_installee_garde_un_petit_quota(self):
        client = _client(agent="ReserveResilience/11 (Android)")

        for i in range(di.SANS_DEFI_PAR_ADRESSE):
            assert client.post(URL, _payload(f"appli{i}@exemple.fr"), format="json").status_code == 201

        au_dela = client.post(URL, _payload("appli-de-trop@exemple.fr"), format="json")
        assert au_dela.status_code == 428
        assert au_dela.json()["code"] == "DEFI_REQUIS"

    def test_le_quota_sans_defi_est_aussi_plafonne_en_tout(self, settings):
        """Mille adresses qui postent sans calcul ne créent pas mille comptes."""
        settings.INSCRIPTION_SANS_DEFI_EN_TOUT = 2
        for i in range(2):
            assert _client(adresse=f"198.51.100.{i}").post(
                URL, _payload(f"flot{i}@exemple.fr"), format="json").status_code == 201

        assert _client(adresse="198.51.100.200").post(
            URL, _payload("flot-de-trop@exemple.fr"), format="json").status_code == 428

    def test_la_tolerance_se_ferme_d_un_reglage(self, settings):
        settings.INSCRIPTION_SANS_DEFI_TOLEREE = False

        assert _client().post(URL, _payload("ancien@exemple.fr"), format="json").status_code == 428


@pytest.mark.django_db
class TestDurcirALaMain:
    def test_la_commande_impose_un_niveau_a_tout_le_monde_pour_un_temps(self, capsys):
        call_command("durcir_inscription", "FORT", "--heures", "1")

        assert _client().get(URL_DEFI).json()["niveau"] == di.FORT
        assert _client(agent=SAFARI_IPHONE, adresse="198.51.100.77").get(URL_DEFI).json()["niveau"] == di.FORT

        call_command("durcir_inscription", "NORMAL")
        assert _client().get(URL_DEFI).json()["niveau"] == di.NORMAL

    def test_le_reglage_s_efface_tout_seul(self):
        di.imposer_niveau(di.ELEVE, timedelta(seconds=-1))

        assert di.niveau_impose() == di.NORMAL


@pytest.mark.django_db
class TestRienEnClair:
    def test_ni_adresse_ni_navigateur_ne_sont_lisibles_en_base(self):
        _inscrire(_client(), "discret@exemple.fr", site_web="x")

        lignes = list(CompteurInscription.objects.values_list("cle", flat=True))
        assert lignes
        for cle in lignes:
            assert len(cle) == 64 and all(c in "0123456789abcdef" for c in cle), cle
            assert GYMNASE not in cle and "Chrome" not in cle

    def test_les_compteurs_echus_s_effacent(self):
        CompteurInscription.objects.create(
            cle="a" * 64, nombre=3, expire_le=di.timezone.now() - timedelta(minutes=1))

        assert di.purger() == 1
