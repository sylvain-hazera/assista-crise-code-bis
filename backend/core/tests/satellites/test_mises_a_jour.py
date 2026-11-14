"""Mise à jour des satellites depuis le central (demande de Sylvain du 14/11/2026).

Ce que ces tests tiennent, par ordre d'importance :

1. **Rien d'installable sans signature valide.** Le central ne fait que transmettre : une
   version dont la signature ne vérifie pas n'est pas publiée, et on ne peut ordonner qu'une
   version publiée.
2. **Qui peut ordonner** : l'administrateur et ceux qui administrent CE satellite. Personne
   d'une autre institution, et jamais le satellite lui-même.
3. **Pas pendant une crise** sans l'avoir confirmé.
4. **Le satellite doit prendre l'ordre avant d'agir**, et un ordre annulé le lui dit.
"""
import datetime

import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework.test import APIClient

from core import signature_satellites
from core.mises_a_jour_satellites import (
    EXPIRATION_ORDRE, etat_version, meme_version, ordre_ouvert,
)
from core.models import (
    ContactInstitution, Crisis, ImplicationInstitution, Institution, InstitutionType,
    MiseAJourSatellite, Satellite, StatutMiseAJour, VersionSatellite,
)
from core.signature_satellites import SignatureInvalide, cles_publiques, verifier

from .signatures_de_test import (
    AUTRE_CLE_PUBLIQUE, CLE_PUBLIQUE, COMMIT_A, COMMIT_B, SIGNATURE_A, SIGNATURE_A_AUTRE_CLE,
    SIGNATURE_A_AUTRE_USAGE, SIGNATURE_B,
)

VERSIONS = "/api/versions-satellite/"


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture(autouse=True)
def cle_de_test(monkeypatch, tmp_path):
    """Le serveur de test fait confiance à la clé de test, et à elle seule."""
    fichier = tmp_path / "cles.pub"
    fichier.write_text(f"# commentaire\n{CLE_PUBLIQUE}\n", encoding="utf-8")
    monkeypatch.setattr(signature_satellites, "FICHIER_CLES", fichier)


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="MAIRIE_MAJ", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie essai maj", type=itype)


@pytest.fixture
def admin(create_user):
    return create_user(username="admin@maj.test", email="admin@maj.test", type="ADMIN")


@pytest.fixture
def agent_mairie(create_user, mairie):
    u = create_user(username="agent@maj.test", email="agent@maj.test", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=mairie, utilisateur=u, actif=True)
    return u


@pytest.fixture
def satellite(create_user, mairie):
    service = create_user(username="sat@maj.test", email="sat@maj.test", type="UTIL_SIMPLE")
    return Satellite.objects.create(
        institution=mairie, nom="satellite-essai", profil="FULL", environment="PROD",
        statut_enrolement="APPROUVE", compte_service=service,
        version_logicielle="0000000", agent_mise_a_jour_vu=timezone.now(),
        dernier_contact=timezone.now(),
    )


@pytest.fixture
def version_a(admin):
    return VersionSatellite.objects.create(
        commit=COMMIT_A, signature=SIGNATURE_A, libelle="Version A", publiee_par=admin)


def _url(satellite, action):
    return f"/api/satellites/{satellite.id}/{action}/"


class TestLaSignature:
    """Vérifiée contre de vraies signatures `ssh-keygen` (voir signatures_de_test.py)."""

    cles = cles_publiques(CLE_PUBLIQUE)

    def test_une_vraie_signature_est_acceptee(self):
        verifier(COMMIT_A, SIGNATURE_A, self.cles)
        verifier(COMMIT_B, SIGNATURE_B, self.cles)

    def test_la_signature_d_une_autre_version_est_refusee(self):
        with pytest.raises(SignatureInvalide):
            verifier(COMMIT_B, SIGNATURE_A, self.cles)

    def test_une_cle_inconnue_est_refusee(self):
        with pytest.raises(SignatureInvalide, match="clé autorisée"):
            verifier(COMMIT_A, SIGNATURE_A_AUTRE_CLE, self.cles)
        # Et acceptée dès que cette clé est autorisée : c'est bien la clé qui décide.
        verifier(COMMIT_A, SIGNATURE_A_AUTRE_CLE, cles_publiques(AUTRE_CLE_PUBLIQUE))

    def test_une_signature_faite_pour_autre_chose_est_refusee(self):
        """Même clé, même texte, mais signé « pour git » : ce n'est pas un ordre."""
        with pytest.raises(SignatureInvalide, match="autre usage"):
            verifier(COMMIT_A, SIGNATURE_A_AUTRE_USAGE, self.cles)

    def test_un_octet_change_suffit(self):
        lignes = SIGNATURE_A.strip().splitlines()
        corps = lignes[-2]
        lignes[-2] = corps[:-6] + ("A" if corps[-6] != "A" else "B") + corps[-5:]
        with pytest.raises(SignatureInvalide):
            verifier(COMMIT_A, "\n".join(lignes), self.cles)

    @pytest.mark.parametrize("commit", ["a" * 39, "A" * 40, "abc1234", "", "g" * 40])
    def test_un_numero_de_version_incomplet_est_refuse(self, commit):
        with pytest.raises(SignatureInvalide):
            verifier(commit, SIGNATURE_A, self.cles)

    @pytest.mark.parametrize("signature", ["", "n'importe quoi",
                                           "-----BEGIN SSH SIGNATURE-----\n!!!\n-----END SSH SIGNATURE-----"])
    def test_un_bloc_illisible_est_refuse_sans_lever_autre_chose(self, signature):
        with pytest.raises(SignatureInvalide):
            verifier(COMMIT_A, signature, self.cles)

    def test_sans_cle_configuree_rien_n_est_accepte(self):
        with pytest.raises(SignatureInvalide, match="Aucune clé"):
            verifier(COMMIT_A, SIGNATURE_A, [])


@pytest.mark.django_db
class TestPublierUneVersion:

    def test_l_administrateur_publie_une_version_signee(self, admin):
        reponse = _client(admin).post(
            VERSIONS, {"commit": COMMIT_A, "signature": SIGNATURE_A, "libelle": "A"},
            format="json")
        assert reponse.status_code == 201, reponse.content
        assert VersionSatellite.objects.get().commit == COMMIT_A

    def test_une_signature_fausse_n_est_pas_publiee(self, admin):
        reponse = _client(admin).post(
            VERSIONS, {"commit": COMMIT_B, "signature": SIGNATURE_A}, format="json")
        assert reponse.status_code == 400
        assert not VersionSatellite.objects.exists()

    def test_un_acteur_institutionnel_lit_mais_ne_publie_pas(self, agent_mairie, version_a):
        client = _client(agent_mairie)
        liste = client.get(VERSIONS).json()
        assert liste["cle_configuree"] is True
        assert [v["commit"] for v in liste["versions"]] == [COMMIT_A]
        reponse = client.post(
            VERSIONS, {"commit": COMMIT_B, "signature": SIGNATURE_B}, format="json")
        assert reponse.status_code == 403

    def test_retirer_une_version_annule_les_ordres_pas_encore_pris(
            self, admin, satellite, version_a):
        _client(admin).post(_url(satellite, "mettre-a-jour"), {}, format="json")
        reponse = _client(admin).post(f"{VERSIONS}{version_a.id}/retirer/")
        assert reponse.status_code == 200
        assert MiseAJourSatellite.objects.get().statut == StatutMiseAJour.ANNULEE


@pytest.mark.django_db
class TestVoir:

    def test_a_jour_en_retard_inconnue(self, satellite, version_a):
        assert etat_version(satellite) == "EN_RETARD"
        satellite.version_logicielle = COMMIT_A
        assert etat_version(satellite) == "A_JOUR"
        satellite.version_logicielle = ""
        assert etat_version(satellite) == "INCONNUE"

    def test_sans_version_publiee_il_n_y_a_pas_de_reference(self, satellite):
        assert etat_version(satellite) is None

    def test_les_anciens_satellites_rapportent_un_prefixe(self):
        """`git describe --always` : sept caractères, ou une étiquette suivie de `-g…`."""
        assert meme_version(COMMIT_A[:7], COMMIT_A)
        assert meme_version("v1.2-3-g" + COMMIT_A[:8], COMMIT_A)
        assert not meme_version(COMMIT_B[:7], COMMIT_A)
        # Trop court pour désigner un commit : on ne conclut pas « à jour » là-dessus.
        assert not meme_version("aaa", COMMIT_A)

    def test_la_liste_des_satellites_dit_l_etat_de_version(
            self, admin, satellite, version_a):
        ligne = _client(admin).get("/api/satellites/").json()[0]
        assert ligne["etat_version"] == "EN_RETARD"
        assert ligne["agent_present"] is True
        assert ligne["mise_a_jour"] is None


@pytest.mark.django_db
class TestOrdonner:

    def test_l_administrateur_et_l_administrateur_du_satellite_peuvent(
            self, admin, agent_mairie, satellite, version_a):
        reponse = _client(agent_mairie).post(_url(satellite, "mettre-a-jour"), {}, format="json")
        assert reponse.status_code == 201, reponse.content
        assert reponse.json()["mise_a_jour"]["statut"] == "DEMANDEE"
        ordre = MiseAJourSatellite.objects.get()
        assert ordre.version == version_a and ordre.demandee_par == agent_mairie
        assert ordre.version_avant == "0000000"

        _client(admin).post(_url(satellite, "annuler-mise-a-jour"))
        assert _client(admin).post(
            _url(satellite, "mettre-a-jour"), {}, format="json").status_code == 201

    def test_quelqu_un_d_une_autre_institution_ne_peut_pas(
            self, create_user, satellite, version_a):
        ailleurs = Institution.objects.create(nom="Mairie voisine maj",
                                              type=satellite.institution.type)
        voisin = create_user(username="voisin@maj.test", email="voisin@maj.test",
                             type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=ailleurs, utilisateur=voisin, actif=True)
        reponse = _client(voisin).post(_url(satellite, "mettre-a-jour"), {}, format="json")
        assert reponse.status_code == 404
        assert not MiseAJourSatellite.objects.exists()

    def test_le_satellite_ne_s_ordonne_pas_sa_propre_mise_a_jour(self, satellite, version_a):
        reponse = _client(satellite.compte_service).post(
            _url(satellite, "mettre-a-jour"), {}, format="json")
        assert reponse.status_code == 403

    def test_un_seul_ordre_ouvert_par_satellite(self, admin, satellite, version_a):
        client = _client(admin)
        assert client.post(_url(satellite, "mettre-a-jour"), {}, format="json").status_code == 201
        second = client.post(_url(satellite, "mettre-a-jour"), {}, format="json")
        assert second.status_code == 400 and second.json()["code"] == "DEJA_DEMANDEE"

    def test_refus_sans_agent(self, admin, satellite, version_a):
        """Passerelle Windows, ou satellite jamais mis à jour depuis : personne n'écouterait."""
        satellite.agent_mise_a_jour_vu = None
        satellite.save()
        reponse = _client(admin).post(_url(satellite, "mettre-a-jour"), {}, format="json")
        assert reponse.status_code == 400 and reponse.json()["code"] == "SANS_AGENT"

    def test_refus_si_deja_a_jour_ou_sans_version(self, admin, satellite):
        client = _client(admin)
        assert client.post(_url(satellite, "mettre-a-jour"), {},
                           format="json").json()["code"] == "AUCUNE_VERSION"
        VersionSatellite.objects.create(commit=COMMIT_A, signature=SIGNATURE_A)
        satellite.version_logicielle = COMMIT_A[:7]
        satellite.save()
        assert client.post(_url(satellite, "mettre-a-jour"), {},
                           format="json").json()["code"] == "DEJA_A_JOUR"

    def test_pendant_une_crise_il_faut_confirmer(self, admin, satellite, version_a):
        crise = Crisis.objects.create(name="Crue essai maj", environment="PROD",
                                      location=Point(-0.57, 44.84, srid=4326))
        ImplicationInstitution.objects.create(
            crise=crise, institution=satellite.institution, type_implication="ACTEUR",
            environment="PROD")
        client = _client(admin)

        refus = client.post(_url(satellite, "mettre-a-jour"), {}, format="json")
        assert refus.status_code == 409
        assert refus.json()["code"] == "CRISE_EN_COURS"
        assert refus.json()["crises"] == ["Crue essai maj"]
        assert not MiseAJourSatellite.objects.exists()

        accepte = client.post(_url(satellite, "mettre-a-jour"), {"malgre_crise": True},
                              format="json")
        assert accepte.status_code == 201
        assert MiseAJourSatellite.objects.get().malgre_crise is True

    def test_une_crise_d_essai_ne_bloque_pas(self, admin, satellite, version_a):
        crise = Crisis.objects.create(name="Essai maj", environment="PROD", essai=True,
                                      location=Point(-0.57, 44.84, srid=4326))
        ImplicationInstitution.objects.create(
            crise=crise, institution=satellite.institution, type_implication="ACTEUR",
            environment="PROD")
        assert _client(admin).post(
            _url(satellite, "mettre-a-jour"), {}, format="json").status_code == 201


@pytest.mark.django_db
class TestLAgentDuSatellite:

    def _ordonner(self, admin, satellite):
        _client(admin).post(_url(satellite, "mettre-a-jour"), {}, format="json")
        return MiseAJourSatellite.objects.get()

    def test_son_passage_le_fait_connaitre_et_rend_l_ordre_signe(
            self, admin, satellite, version_a):
        satellite.agent_mise_a_jour_vu = None
        satellite.save()
        client = _client(satellite.compte_service)

        vide = client.get(_url(satellite, "ordre-mise-a-jour") + "?version=" + "c" * 40)
        assert vide.json() == {"ordre": None}
        satellite.refresh_from_db()
        assert satellite.agent_mise_a_jour_vu is not None
        assert satellite.version_logicielle == "c" * 40

        ordre = self._ordonner(admin, satellite)
        recu = client.get(_url(satellite, "ordre-mise-a-jour")).json()["ordre"]
        assert recu["id"] == str(ordre.id)
        assert recu["commit"] == COMMIT_A and recu["signature"] == SIGNATURE_A

    def test_un_autre_compte_ne_lit_pas_l_ordre(self, admin, agent_mairie, satellite, version_a):
        self._ordonner(admin, satellite)
        assert _client(agent_mairie).get(
            _url(satellite, "ordre-mise-a-jour")).status_code == 403

    def test_le_deroule_complet(self, admin, satellite, version_a):
        ordre = self._ordonner(admin, satellite)
        client = _client(satellite.compte_service)
        rapport = _url(satellite, "rapport-mise-a-jour")

        pris = client.post(rapport, {"ordre": str(ordre.id), "statut": "EN_COURS",
                                     "etape": "Vérification"}, format="json")
        assert pris.status_code == 200
        ordre.refresh_from_db()
        assert ordre.statut == StatutMiseAJour.EN_COURS and ordre.date_debut is not None

        # Une fois commencée, elle ne s'annule plus.
        assert _client(admin).post(
            _url(satellite, "annuler-mise-a-jour")).json()["code"] == "DEJA_COMMENCEE"

        fini = client.post(rapport, {
            "ordre": str(ordre.id), "statut": "REUSSIE", "etape": "Terminée",
            "journal": "tout va bien", "version": COMMIT_A}, format="json")
        assert fini.status_code == 200
        ordre.refresh_from_db()
        satellite.refresh_from_db()
        assert ordre.statut == StatutMiseAJour.REUSSIE and ordre.date_fin is not None
        assert satellite.version_logicielle == COMMIT_A
        assert etat_version(satellite) == "A_JOUR"

        historique = _client(admin).get(_url(satellite, "mises-a-jour")).json()
        assert historique[0]["journal"] == "tout va bien"
        # La liste, elle, ne transporte pas le journal.
        assert _client(admin).get("/api/satellites/").json()[0]["mise_a_jour"]["journal"] is None

    def test_le_journal_est_chiffre_au_repos(self, admin, satellite, version_a):
        """« On ne stocke rien en clair » : vérifié en SQL brut, pas par l'ORM."""
        from django.db import connection

        ordre = self._ordonner(admin, satellite)
        _client(satellite.compte_service).post(
            _url(satellite, "rapport-mise-a-jour"),
            {"ordre": str(ordre.id), "statut": "ECHOUEE", "etape": "Construction",
             "journal": "chemin-tres-reconnaissable-sur-le-disque"}, format="json")
        with connection.cursor() as curseur:
            curseur.execute("SELECT journal FROM core_miseajoursatellite WHERE id = %s",
                            [ordre.id])
            brut = curseur.fetchone()[0]
        assert brut and "chemin-tres-reconnaissable" not in brut

    def test_un_ordre_annule_dit_au_satellite_de_s_arreter(self, admin, satellite, version_a):
        ordre = self._ordonner(admin, satellite)
        _client(admin).post(_url(satellite, "annuler-mise-a-jour"))
        reponse = _client(satellite.compte_service).post(
            _url(satellite, "rapport-mise-a-jour"),
            {"ordre": str(ordre.id), "statut": "EN_COURS"}, format="json")
        assert reponse.status_code == 409
        ordre.refresh_from_db()
        assert ordre.statut == StatutMiseAJour.ANNULEE

    def test_un_ordre_jamais_pris_expire(self, admin, satellite, version_a):
        ordre = self._ordonner(admin, satellite)
        MiseAJourSatellite.objects.filter(pk=ordre.pk).update(
            date_demande=timezone.now() - EXPIRATION_ORDRE - datetime.timedelta(hours=1))
        assert ordre_ouvert(satellite) is None
        ordre.refresh_from_db()
        assert ordre.statut == StatutMiseAJour.EXPIREE

    def test_le_compte_rendu_tardif_d_une_mise_a_jour_tenue_pour_perdue_est_pris(
            self, admin, satellite, version_a):
        """Le satellite est resté coupé du central pendant sa mise à jour : ce qu'il finit
        par dire vaut mieux que « plus de nouvelles »."""
        ordre = self._ordonner(admin, satellite)
        client = _client(satellite.compte_service)
        rapport = _url(satellite, "rapport-mise-a-jour")
        client.post(rapport, {"ordre": str(ordre.id), "statut": "EN_COURS"}, format="json")
        MiseAJourSatellite.objects.filter(pk=ordre.pk).update(
            date_debut=timezone.now() - datetime.timedelta(hours=7))
        assert ordre_ouvert(satellite) is None
        ordre.refresh_from_db()
        assert ordre.statut == StatutMiseAJour.ECHOUEE

        tardif = client.post(rapport, {"ordre": str(ordre.id), "statut": "REUSSIE",
                                       "version": COMMIT_A}, format="json")
        assert tardif.status_code == 200
        ordre.refresh_from_db()
        assert ordre.statut == StatutMiseAJour.REUSSIE
