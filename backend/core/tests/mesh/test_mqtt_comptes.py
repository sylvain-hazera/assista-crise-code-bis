"""Comptes du broker MQTT administrés depuis l'application (core/mqtt_comptes.py).

Le test qui compte vraiment est `test_vecteur_de_reference_de_mosquitto_passwd` : Django
réimplémente le format de mot de passe de Mosquitto, et rien ne garantirait sans lui que le
broker accepte nos empreintes. Le vecteur ci-dessous a été produit par le vrai
`mosquitto_passwd` 2.1.2 (`mosquitto_passwd -c -b fichier essai motdepasse-connu`) : s'il cesse
de correspondre, l'authentification du broker est cassée, et aucun autre test ne le dirait.

Pourquoi ce format est réimplémenté plutôt que délégué au greffon « dynamic security » de
Mosquitto : voir la docstring de core/mqtt_comptes.py — ce greffon ne sait créer un compte que
par un broker en fonctionnement, ce qui rendrait le broker inutilisable tant que Django ne
l'a pas amorcé.
"""
import base64

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from core.models import CompteMqtt, RoleCompteMqtt
from core.mqtt_comptes import (
    ITERATIONS, NomDeCompteInvalide, ecrire_fichiers, hacher, rendre_acl, rendre_passwd,
    valider_nom,
)

# Produit par mosquitto_passwd 2.1.2 — ne pas « corriger » sans le régénérer avec l'outil.
LIGNE_REFERENCE = (
    "essai:$7$1000$dJdBexXfhj5DnzVGbIA3NBbVTjjJan+YPsR6ph+R9jX8zlm7WGfpxVOabVAoXF01JL2W6xPKmNX96jEdn+wZtQ=="
    "$uLFUkHthgD3MoWz0LGNy3qelBQtIRq9OdTjOqwThL1xtApaO+APTZnJKkYpLTmqBUVrAaQ6Op5EFh+pKlGLGVw=="
)
MOT_DE_PASSE_REFERENCE = "motdepasse-connu"


class TestFormatMosquitto:

    def test_vecteur_de_reference_de_mosquitto_passwd(self):
        """Rejoue le hachage du vrai outil avec son sel : si ça ne correspond plus, le broker
        refusera tous les comptes écrits par Django."""
        _, reste = LIGNE_REFERENCE.split(":", 1)
        _, algo, iterations, sel_b64, _empreinte = reste.split("$")
        assert algo == "7", "le format a changé de fonction de dérivation"
        recalcule = hacher(
            MOT_DE_PASSE_REFERENCE, sel=base64.b64decode(sel_b64), iterations=int(iterations),
        )
        assert recalcule == reste

    def test_le_sel_est_tire_au_hasard_a_chaque_appel(self):
        """Deux comptes de même mot de passe ne doivent pas avoir la même empreinte, sinon le
        fichier révélerait qui partage un mot de passe."""
        assert hacher("identique") != hacher("identique")

    def test_les_iterations_par_defaut_suivent_l_outil(self):
        assert f"$7${ITERATIONS}$" in hacher("x")


class TestValidationDesNoms:
    """Un nom de compte devient un `user <nom>` dans le fichier de droits : un nom contenant un
    retour à la ligne y injecterait des droits arbitraires."""

    @pytest.mark.parametrize("nom", ["pont", "passerelle-mairie", "gw_01", "A1.b"])
    def test_noms_acceptes(self, nom):
        assert valider_nom(nom) == nom

    @pytest.mark.parametrize("nom", [
        "", "a", "-debut", "espace dans le nom", "retour\nligne", "deux:points",
        "topic read #", "x" * 64,
    ])
    def test_noms_refuses(self, nom):
        with pytest.raises(NomDeCompteInvalide):
            valider_nom(nom)


class _CompteFactice:
    def __init__(self, nom, role=RoleCompteMqtt.RADIO, racine="msh/EU_868", mot_de_passe="secret",
                 description=""):
        self.nom, self.role, self.racine_topic = nom, role, racine
        self.mot_de_passe, self.description = mot_de_passe, description

    def get_role_display(self):
        return "Passerelle"


class TestRenduDesFichiers:

    def test_une_ligne_par_compte_au_bon_format(self):
        contenu = rendre_passwd([_CompteFactice("pont"), _CompteFactice("passerelle1")])
        lignes = contenu.strip().split("\n")
        assert [l.split(":")[0] for l in lignes] == ["pont", "passerelle1"]
        assert all(l.split(":", 1)[1].startswith("$7$") for l in lignes)

    def test_un_compte_sans_mot_de_passe_est_ignore(self):
        """Une ligne malformée ferait refuser le fichier ENTIER par le broker, donc couperait
        tous les comptes — mieux vaut omettre ce compte-là."""
        contenu = rendre_passwd([_CompteFactice("ok"), _CompteFactice("vide", mot_de_passe="")])
        assert "vide" not in contenu
        assert "ok:" in contenu

    def test_les_droits_viennent_du_role_et_pas_d_une_saisie(self):
        acl = rendre_acl([
            _CompteFactice("exporteur", role=RoleCompteMqtt.SUPERVISION),
            _CompteFactice("gw", role=RoleCompteMqtt.RADIO, racine="msh/EU_868"),
        ])
        assert "user exporteur" in acl and "topic read $SYS/#" in acl
        assert "user gw" in acl and "topic readwrite msh/EU_868/#" in acl
        # La supervision ne doit RIEN pouvoir publier, ni lire le trafic radio.
        bloc_exporteur = acl.split("user exporteur")[1].split("user gw")[0]
        assert "readwrite" not in bloc_exporteur
        assert "msh/" not in bloc_exporteur

    def test_un_nom_invalide_fait_echouer_le_rendu_plutot_que_d_injecter(self):
        with pytest.raises(NomDeCompteInvalide):
            rendre_acl([_CompteFactice("mechant\ntopic readwrite #")])

    def test_sans_dossier_configure_rien_n_est_ecrit(self, settings):
        settings.MQTT_COMPTES_DIR = ""
        assert ecrire_fichiers() is False


@pytest.mark.django_db
class TestEcritureReelle:

    def test_rien_n_est_ecrit_sans_compte_d_infrastructure(self, settings, tmp_path):
        """Garde-fou : écrire les fichiers alors que les comptes d'amorçage ne sont pas en base
        les supprimerait du broker — l'exporteur et le pont perdraient l'accès, en silence."""
        settings.MQTT_COMPTES_DIR = str(tmp_path)
        CompteMqtt.objects.create(nom="seulement-une-passerelle", mot_de_passe="x")
        assert ecrire_fichiers() is False
        assert not (tmp_path / "passwd").exists()

    def test_les_deux_fichiers_sont_ecrits_et_relisibles(self, settings, tmp_path):
        settings.MQTT_COMPTES_DIR = str(tmp_path)
        CompteMqtt.objects.create(nom="pont", mot_de_passe="abc", role=RoleCompteMqtt.RADIO,
                                  infrastructure=True)
        CompteMqtt.objects.create(nom="exporteur", mot_de_passe="def",
                                  role=RoleCompteMqtt.SUPERVISION, infrastructure=True)

        assert ecrire_fichiers() is True
        passwd = (tmp_path / "passwd").read_text()
        acl = (tmp_path / "acl").read_text()
        assert "pont:$7$" in passwd and "exporteur:$7$" in passwd
        assert "topic readwrite msh/EU_868/#" in acl and "topic read $SYS/#" in acl
        # Empreintes de mots de passe : jamais lisibles par tout le monde.
        assert oct((tmp_path / "passwd").stat().st_mode)[-3:] == "640"

    def test_un_compte_inactif_est_exclu(self, settings, tmp_path):
        settings.MQTT_COMPTES_DIR = str(tmp_path)
        CompteMqtt.objects.create(nom="pont", mot_de_passe="p", infrastructure=True)
        CompteMqtt.objects.create(nom="actif", mot_de_passe="a")
        CompteMqtt.objects.create(nom="coupe", mot_de_passe="b", actif=False)
        assert ecrire_fichiers() is True
        contenu = (tmp_path / "passwd").read_text()
        assert "coupe" not in contenu and "actif:" in contenu

    def test_le_mot_de_passe_est_chiffre_au_repos(self):
        """Même règle que les autres secrets mesh (migration 0230) : rien en clair en base."""
        from django.db import connection
        compte = CompteMqtt.objects.create(nom="chiffre", mot_de_passe="tres-secret")
        with connection.cursor() as curseur:
            curseur.execute("SELECT mot_de_passe FROM core_comptemqtt WHERE id = %s", [str(compte.id)])
            brut = curseur.fetchone()[0]
        assert "tres-secret" not in brut
        assert brut.startswith("gAAAAA")


@pytest.mark.django_db
class TestApi:

    @pytest.fixture
    def admin_client(self, create_user):
        client = APIClient()
        client.force_authenticate(user=create_user(
            username="admin-mqtt@x.fr", email="admin-mqtt@x.fr", type="ADMIN",
        ))
        return client

    def test_un_non_administrateur_est_refuse(self, create_user):
        client = APIClient()
        client.force_authenticate(user=create_user(
            username="secours@x.fr", email="secours@x.fr", type="SECOURS",
        ))
        assert client.get("/api/comptes-mqtt/").status_code == status.HTTP_403_FORBIDDEN

    def test_creation_avec_mot_de_passe_engendre(self, admin_client, settings, tmp_path):
        settings.MQTT_COMPTES_DIR = str(tmp_path)
        # Sans compte d'infrastructure, le garde-fou de ecrire_fichiers refuserait d'écrire.
        CompteMqtt.objects.create(nom="pont", mot_de_passe="p", infrastructure=True)
        reponse = admin_client.post(
            "/api/comptes-mqtt/", {"nom": "passerelle-mairie", "role": "RADIO"}, format="json",
        )
        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        # Jamais renvoyé dans la réponse de création.
        assert "mot_de_passe" not in reponse.data
        compte = CompteMqtt.objects.get(nom="passerelle-mairie")
        assert len(compte.mot_de_passe) > 20
        assert "passerelle-mairie:$7$" in (tmp_path / "passwd").read_text()

    def test_le_mot_de_passe_s_affiche_par_une_action_dediee(self, admin_client):
        compte = CompteMqtt.objects.create(nom="gw", mot_de_passe="le-secret")
        reponse = admin_client.get(f"/api/comptes-mqtt/{compte.id}/mot-de-passe/")
        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["mot_de_passe"] == "le-secret"

    def test_la_regeneration_change_le_mot_de_passe(self, admin_client, settings, tmp_path):
        settings.MQTT_COMPTES_DIR = str(tmp_path)
        compte = CompteMqtt.objects.create(nom="gw2", mot_de_passe="ancien")
        reponse = admin_client.post(f"/api/comptes-mqtt/{compte.id}/regenerer/")
        assert reponse.status_code == status.HTTP_200_OK
        compte.refresh_from_db()
        assert compte.mot_de_passe != "ancien"
        assert reponse.data["mot_de_passe"] == compte.mot_de_passe

    def test_un_compte_d_infrastructure_ne_peut_pas_etre_supprime(self, admin_client):
        """L'exporteur de supervision et le pont en dépendent : les supprimer depuis le web
        couperait la supervision du broker."""
        compte = CompteMqtt.objects.create(nom="pont", mot_de_passe="x", infrastructure=True)
        reponse = admin_client.delete(f"/api/comptes-mqtt/{compte.id}/")
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert CompteMqtt.objects.filter(pk=compte.pk).exists()

    def test_une_racine_avec_joker_est_refusee(self, admin_client):
        """`#` comme racine donnerait accès à tout le trafic du broker."""
        reponse = admin_client.post(
            "/api/comptes-mqtt/", {"nom": "trop-large", "racine_topic": "#"}, format="json",
        )
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "racine_topic" in reponse.data

    def test_un_nom_avec_retour_ligne_est_refuse(self, admin_client):
        reponse = admin_client.post(
            "/api/comptes-mqtt/", {"nom": "x\ntopic readwrite #"}, format="json",
        )
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
