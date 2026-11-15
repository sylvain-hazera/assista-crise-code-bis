"""Signature d'une version depuis la page Satellites (demande de Sylvain du 15/11/2026 : « que
je n'aie que la phrase de passe à rentrer dans la page web »).

Ce que ces tests tiennent :

1. **Le serveur ne signe pas et ne voit jamais la phrase de passe.** Il remet une clé
   CHIFFRÉE ; ce qu'il reçoit ensuite est une signature, qu'il vérifie comme avant.
2. **La signature faite ainsi est celle d'OpenSSH, à l'octet près** : un satellite la vérifie
   avec `ssh-keygen`, il ne doit voir aucune différence.
3. **Seul l'administrateur reçoit la clé emballée**, jamais en démonstration, et chaque remise
   est tracée.
"""
import json
from unittest import mock

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from rest_framework.test import APIClient

from core import signature_satellites
from core.models import AuditLog, VersionSatellite
from core.signature_satellites import (
    SignatureInvalide, cle_emballee, deballer_cle, derniere_version_poussee, emballer_cle, signer,
    verifier,
)

from .cle_navigateur_de_test import (
    CLE_PUBLIQUE_NAVIGATEUR, EMBALLAGE, GRAINE, PHRASE, SIGNATURE_SSH_KEYGEN_A,
)
from .signatures_de_test import CLE_PUBLIQUE, COMMIT_A, COMMIT_B

A_SIGNER = "/api/versions-satellite/a-signer/"
VERSIONS = "/api/versions-satellite/"
CLE_D_ESSAI = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(GRAINE))


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.fixture(autouse=True)
def serveur_de_test(monkeypatch, tmp_path):
    """Le serveur fait confiance à la clé d'essai du navigateur, et a son emballage."""
    cles = tmp_path / "cles.pub"
    cles.write_text(f"{CLE_PUBLIQUE_NAVIGATEUR}\n", encoding="utf-8")
    monkeypatch.setattr(signature_satellites, "FICHIER_CLES", cles)
    emballage = tmp_path / "emballage.json"
    emballage.write_text(json.dumps(EMBALLAGE), encoding="utf-8")
    monkeypatch.setenv("SIGNATURE_SATELLITES_WEB_FILE", str(emballage))
    monkeypatch.setenv("SATELLITES_DEPOT_GITHUB", "exemple/depot")
    return emballage


@pytest.fixture
def admin(create_user):
    return create_user(username="admin@signature.test", email="admin@signature.test", type="ADMIN")


@pytest.fixture
def depot():
    """Le dépôt public répond que le dernier commit poussé est COMMIT_A."""
    with mock.patch("requests.get") as appel:
        appel.return_value.json.return_value = {
            "sha": COMMIT_A,
            "commit": {"message": "Veille : mesures des stations\n\nDétail.",
                       "committer": {"date": "2026-11-15T12:50:00Z"}},
        }
        yield appel


class TestFormatDeLaSignature:

    def test_notre_signature_est_celle_de_ssh_keygen_a_l_octet_pres(self):
        assert signer(CLE_D_ESSAI, COMMIT_A) == SIGNATURE_SSH_KEYGEN_A

    def test_elle_est_acceptee_par_la_verification_existante(self):
        verifier(COMMIT_A, signer(CLE_D_ESSAI, COMMIT_A))
        with pytest.raises(SignatureInvalide):
            verifier(COMMIT_B, signer(CLE_D_ESSAI, COMMIT_A))

    def test_un_numero_de_version_incomplet_n_est_pas_signe(self):
        with pytest.raises(SignatureInvalide):
            signer(CLE_D_ESSAI, "abc123")


class TestEmballageDeLaCle:

    def test_l_emballage_de_reference_est_reproductible(self):
        """Mêmes clé, phrase, sel et vecteur : même emballage. C'est ce qui permet au test du
        navigateur de travailler sur la même valeur que celui-ci."""
        assert emballer_cle(CLE_D_ESSAI, PHRASE, sel=bytes(range(16)), vecteur=bytes(range(12))) == EMBALLAGE

    def test_la_bonne_phrase_rend_la_cle(self):
        assert signer(deballer_cle(EMBALLAGE, PHRASE), COMMIT_A) == SIGNATURE_SSH_KEYGEN_A

    def test_une_mauvaise_phrase_ne_rend_rien(self):
        with pytest.raises(SignatureInvalide, match="Phrase de passe incorrecte"):
            deballer_cle(EMBALLAGE, PHRASE + " ")

    def test_l_emballage_ne_contient_ni_la_cle_ni_la_phrase_en_clair(self):
        texte = json.dumps(EMBALLAGE)

        assert GRAINE not in texte and PHRASE not in texte
        assert bytes.fromhex(GRAINE) not in __import__("base64").b64decode(EMBALLAGE["chiffre"])

    def test_deux_emballages_de_la_meme_cle_different(self):
        """Sel et vecteur tirés au hasard en service."""
        un, deux = emballer_cle(CLE_D_ESSAI, PHRASE, iterations=1000), emballer_cle(CLE_D_ESSAI, PHRASE, iterations=1000)

        assert un["sel"] != deux["sel"] and un["chiffre"] != deux["chiffre"]

    def test_une_phrase_vide_est_refusee(self):
        with pytest.raises(ValueError):
            emballer_cle(CLE_D_ESSAI, "")

    def test_un_emballage_d_une_cle_non_autorisee_n_est_pas_servi(self, monkeypatch, tmp_path):
        """Il ne produirait que des signatures refusées : autant le dire avant."""
        autres = tmp_path / "autres.pub"
        autres.write_text(f"{CLE_PUBLIQUE}\n", encoding="utf-8")
        monkeypatch.setattr(signature_satellites, "FICHIER_CLES", autres)

        assert cle_emballee() is None

    @pytest.mark.parametrize("contenu", ["", "pas du json", "[]", '{"version": 1}'])
    def test_un_fichier_absent_vide_ou_abime_vaut_pas_d_emballage(self, serveur_de_test, contenu):
        serveur_de_test.write_text(contenu, encoding="utf-8")

        assert cle_emballee() is None


class TestDerniereVersionPoussee:

    def test_le_depot_public_donne_le_dernier_commit(self, depot):
        assert derniere_version_poussee() == {
            "commit": COMMIT_A, "titre": "Veille : mesures des stations", "date": "2026-11-15T12:50:00Z"}
        (adresse,), _options = depot.call_args
        assert adresse == "https://api.github.com/repos/exemple/depot/commits/main"

    def test_un_depot_muet_est_dit_sans_exception_technique(self):
        with mock.patch("requests.get", side_effect=requests.ConnectionError("coupé")):
            with pytest.raises(SignatureInvalide, match="n'a pas répondu"):
                derniere_version_poussee()

    @pytest.mark.parametrize("depot_configure", ["", "pas un dépôt", "a/b/c", "https://exemple.test/a/b"])
    def test_sans_depot_configure_aucun_appel_ne_part(self, monkeypatch, depot_configure):
        monkeypatch.setenv("SATELLITES_DEPOT_GITHUB", depot_configure)
        with mock.patch("requests.get") as appel:
            with pytest.raises(SignatureInvalide, match="pas configuré"):
                derniere_version_poussee()
        appel.assert_not_called()


@pytest.mark.django_db
class TestPointDAcces:

    def test_l_administrateur_recoit_la_version_et_la_cle_chiffree(self, admin, depot):
        reponse = _client(admin).get(A_SIGNER)

        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["version"]["commit"] == COMMIT_A and corps["deja_publiee"] is False
        assert corps["cle"] == EMBALLAGE and corps["erreur_depot"] is None
        assert reponse["Cache-Control"] == "no-store"

    def test_chaque_remise_de_la_cle_est_tracee(self, admin, depot):
        _client(admin).get(A_SIGNER)

        trace = AuditLog.objects.filter(objet_type="CleSignatureSatellites").get()
        assert trace.utilisateur_id == admin.id

    def test_personne_d_autre_ne_recoit_la_cle(self, create_user, depot):
        agent = create_user(username="agent@signature.test", email="agent@signature.test", type="AUT_LOCALE")
        citoyen = create_user(username="citoyen@signature.test", email="citoyen@signature.test")

        assert _client(agent).get(A_SIGNER).status_code == 403
        assert _client(citoyen).get(A_SIGNER).status_code == 403
        assert APIClient().get(A_SIGNER).status_code in (401, 403)
        assert not AuditLog.objects.filter(objet_type="CleSignatureSatellites").exists()

    def test_une_version_deja_publiee_est_signalee(self, admin, depot):
        VersionSatellite.objects.create(commit=COMMIT_A, signature=SIGNATURE_SSH_KEYGEN_A)

        assert _client(admin).get(A_SIGNER).json()["deja_publiee"] is True

    def test_un_depot_muet_n_empeche_pas_de_lire_le_reste(self, admin):
        with mock.patch("requests.get", side_effect=requests.ConnectionError("coupé")):
            corps = _client(admin).get(A_SIGNER).json()

        assert corps["version"] is None and "n'a pas répondu" in corps["erreur_depot"]

    def test_sans_emballage_prepare_la_page_le_sait(self, admin, depot, serveur_de_test):
        serveur_de_test.unlink()

        assert _client(admin).get(A_SIGNER).json()["cle"] is None
        assert not AuditLog.objects.filter(objet_type="CleSignatureSatellites").exists()

    def test_le_parcours_entier_ne_montre_jamais_la_phrase_au_serveur(self, admin, depot):
        """Ce que fait le navigateur, rejoué ici : il reçoit l'emballage, le déballe avec la
        phrase, signe, et n'envoie QUE le commit et la signature."""
        client = _client(admin)
        recu = client.get(A_SIGNER).json()

        signature = signer(deballer_cle(recu["cle"], PHRASE), recu["version"]["commit"])
        envoi = {"commit": recu["version"]["commit"], "signature": signature, "libelle": recu["version"]["titre"]}
        reponse = client.post(VERSIONS, envoi, format="json")

        assert reponse.status_code == 201
        assert PHRASE not in json.dumps(envoi)
        assert VersionSatellite.objects.get(commit=COMMIT_A).publiee_par_id == admin.id
