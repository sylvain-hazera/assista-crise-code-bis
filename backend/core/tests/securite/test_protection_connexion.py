"""Protection de la connexion contre la force brute (demande de Sylvain du 15/11/2026).

Ce que ces tests tiennent, par ordre d'importance :

1. **Sans le code, le mot de passe n'est pas examiné.** Sur un compte protégé, un bon mot de
   passe sans code reçoit exactement la réponse d'un mauvais.
2. **Aucun contournement** : lien magique, lien d'activation, connexion Grafana/Matrix,
   administration Django et renouvellement de session appliquent la même règle.
3. **Le frein est par compte**, ne dit pas qui est inscrit, et ne ferme jamais un compte pour
   de bon : un appareil déjà connu du titulaire n'est pas ralenti par les échecs d'un inconnu.
4. **Quinze jours** pour les comptes à pouvoir, puis plus de session sans activation — sauf sur
   un satellite, et jamais pour une machine.
5. **Rien en clair** : ni le secret, ni les codes de secours, ni l'adresse dans les compteurs.
"""
import datetime
import re

import pytest
from django.core import mail
from django.db import connection
from django.test import Client
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient

from core import frein_connexion as frein
from core import second_facteur
from core.models import (
    AppareilConnu, CodeSecours, ContactInstitution, FreinConnexion, Institution,
    InstitutionType, Satellite, SecondFacteur, Team,
)
from core.second_facteur import code_au_pas, pas_courant, pas_du_code
from core.views import MAGIC_LINK_SIGNER

MDP = "Un-mot-de-passe-assez-long-2026"
JETON = "/api/token/"
DEBUT = "/api/connexion/debut/"
CODE = "/api/connexion/code/"


def _code(utilisateur, decalage=0):
    """Le code qu'afficherait le téléphone du titulaire."""
    facteur = SecondFacteur.objects.get(utilisateur=utilisateur)
    return code_au_pas(facteur.secret, pas_courant() + decalage)


def _proteger(utilisateur):
    """Active un second facteur, comme le ferait le titulaire. Rend les codes de secours."""
    preparation = second_facteur.preparer(utilisateur)
    codes = second_facteur.confirmer(
        utilisateur, code_au_pas(preparation["secret"], pas_courant() - 1))
    assert codes
    return codes


def _lien(utilisateur):
    uid = urlsafe_base64_encode(force_bytes(str(utilisateur.pk)))
    return uid, MAGIC_LINK_SIGNER.sign(uid)


@pytest.fixture
def citoyen(create_user):
    return create_user(username="citoyen@frein.test", email="citoyen@frein.test", password=MDP)


@pytest.fixture
def maire(create_user):
    return create_user(username="maire@frein.test", email="maire@frein.test",
                       type="AUT_LOCALE", password=MDP)


@pytest.fixture
def admin(create_user):
    return create_user(username="admin@frein.test", email="admin@frein.test",
                       type="ADMIN", password=MDP)


@pytest.fixture
def client():
    return APIClient()


# ── 0. Le code lui-même ──────────────────────────────────────────────────────────────────────

class TestCode:
    SECRET_RFC = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # « 12345678901234567890 », RFC 6238 annexe B

    @pytest.mark.parametrize("instant, attendu", [
        (59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
        (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130"),
    ])
    def test_vecteurs_de_la_rfc(self, instant, attendu):
        assert code_au_pas(self.SECRET_RFC, instant // 30, chiffres=8) == attendu

    def test_un_pas_de_tolerance_de_chaque_cote_pas_deux(self):
        secret = second_facteur.nouveau_secret()
        maintenant = 1_800_000_000
        pas = maintenant // 30
        for decalage in (-1, 0, 1):
            assert pas_du_code(secret, code_au_pas(secret, pas + decalage), instant=maintenant) == pas + decalage
        for decalage in (-2, 2):
            assert pas_du_code(secret, code_au_pas(secret, pas + decalage), instant=maintenant) is None

    def test_un_code_mal_forme_est_refuse_sans_erreur(self):
        secret = second_facteur.nouveau_secret()
        for faux in ("", "12345", "1234567", "abcdef", None):
            assert pas_du_code(secret, faux) is None

    def test_espaces_et_tirets_dans_la_saisie_sont_ignores(self):
        secret = second_facteur.nouveau_secret()
        bon = code_au_pas(secret, pas_courant())
        assert pas_du_code(secret, f"{bon[:3]} {bon[3:]}") == pas_courant()

    def test_l_adresse_otpauth_porte_le_secret_et_l_emetteur(self):
        adresse = second_facteur.adresse_otpauth("ABCDEFGH", "a+b@exemple.test")
        assert adresse.startswith("otpauth://totp/Assista-Crise%3Aa%2Bb%40exemple.test?")
        assert "secret=ABCDEFGH" in adresse and "issuer=Assista-Crise" in adresse

    def test_le_qr_est_fabrique_ici(self):
        assert second_facteur.qr_svg("otpauth://totp/x?secret=ABC").lstrip().startswith("<?xml")


# ── 1. Sans le code, le mot de passe n'est pas examiné ───────────────────────────────────────

@pytest.mark.django_db
class TestParcoursEnTroisEtapes:
    def test_un_compte_sans_second_facteur_entre_comme_avant(self, client, citoyen):
        """Ancienne application mobile, satellite, pont radio : adresse et mot de passe."""
        reponse = client.post(JETON, {"email": citoyen.email, "password": MDP}, format="json")
        assert reponse.status_code == 200
        assert {"access", "refresh", "user", "appareil"} <= set(reponse.data)
        assert reponse.data["user"]["email"] == citoyen.email

    def test_se_connecter_depuis_la_zone_de_demonstration_ne_masque_pas_son_propre_nom(self, client, citoyen):
        """Le navigateur envoie la zone active dès la connexion. La fiche rendue est celle du
        titulaire : ni pseudonyme, ni adresse masquée, comme avant le parcours en étapes."""
        reponse = client.post(JETON, {"email": citoyen.email, "password": MDP}, format="json",
                              HTTP_X_ENVIRONMENT="DEMO")
        assert reponse.status_code == 200
        assert reponse.data["user"]["email"] == citoyen.email
        assert reponse.data["user"]["first_name"] == citoyen.first_name
        assert reponse.data["user"]["second_facteur"]["applicable"] is True

    def test_l_etape_suivante_depend_de_la_protection_du_compte(self, client, citoyen, maire):
        _proteger(maire)
        assert client.post(DEBUT, {"email": maire.email}, format="json").data == {"etape": "code"}
        assert client.post(DEBUT, {"email": citoyen.email}, format="json").data == {"etape": "mot_de_passe"}

    def test_une_adresse_inconnue_peut_aussi_se_voir_demander_un_code(self, client, db):
        """Sinon « code » désignerait à coup sûr un compte à pouvoir."""
        reponses = {client.post(DEBUT, {"email": f"inconnu{i}@nulle-part.test"}, format="json").data["etape"]
                    for i in range(80)}
        assert reponses == {"code", "mot_de_passe"}
        une = "inconnu7@nulle-part.test"
        assert (client.post(DEBUT, {"email": une}, format="json").data
                == client.post(DEBUT, {"email": une.upper()}, format="json").data)

    def test_bon_mot_de_passe_sans_code_recoit_la_reponse_d_un_mauvais(self, client, maire):
        _proteger(maire)
        bon = client.post(JETON, {"email": maire.email, "password": MDP}, format="json")
        mauvais = client.post(JETON, {"email": maire.email, "password": "faux"}, format="json")
        assert bon.status_code == mauvais.status_code == 401
        assert bon.data == mauvais.data
        assert "access" not in bon.data

    def test_code_puis_mot_de_passe_ouvre_la_session(self, client, maire):
        _proteger(maire)
        etape = client.post(CODE, {"email": maire.email, "code": _code(maire)}, format="json")
        assert etape.status_code == 200
        reponse = client.post(JETON, {"email": maire.email, "password": MDP,
                                      "jeton_etape": etape.data["jeton_etape"]}, format="json")
        assert reponse.status_code == 200 and reponse.data["access"]

    def test_le_code_ne_dispense_pas_du_mot_de_passe(self, client, maire):
        _proteger(maire)
        jeton = client.post(CODE, {"email": maire.email, "code": _code(maire)}, format="json").data["jeton_etape"]
        reponse = client.post(JETON, {"email": maire.email, "password": "faux",
                                      "jeton_etape": jeton}, format="json")
        assert reponse.status_code == 401

    def test_le_jeton_d_etape_d_un_autre_compte_ne_sert_a_rien(self, client, maire, admin):
        _proteger(maire)
        _proteger(admin)
        jeton_maire = client.post(CODE, {"email": maire.email, "code": _code(maire)}, format="json").data["jeton_etape"]
        reponse = client.post(JETON, {"email": admin.email, "password": MDP,
                                      "jeton_etape": jeton_maire}, format="json")
        assert reponse.status_code == 401

    def test_un_code_faux_et_une_adresse_inconnue_recoivent_la_meme_reponse(self, client, maire):
        _proteger(maire)
        faux = client.post(CODE, {"email": maire.email, "code": "000000"}, format="json")
        inconnu = client.post(CODE, {"email": "personne@nulle-part.test", "code": "000000"}, format="json")
        assert faux.status_code == inconnu.status_code == 401
        assert faux.data == inconnu.data

    def test_un_code_ne_sert_qu_une_fois(self, client, maire):
        _proteger(maire)
        code = _code(maire)
        assert client.post(CODE, {"email": maire.email, "code": code}, format="json").status_code == 200
        assert client.post(CODE, {"email": maire.email, "code": code}, format="json").status_code == 401

    def test_un_code_de_secours_remplace_le_code_une_seule_fois(self, client, maire):
        codes = _proteger(maire)
        assert len(codes) == 10
        assert client.post(CODE, {"email": maire.email, "code": codes[0]}, format="json").status_code == 200
        assert client.post(CODE, {"email": maire.email, "code": codes[0]}, format="json").status_code == 401
        assert client.post(CODE, {"email": maire.email, "code": codes[1].upper()}, format="json").status_code == 200
        assert second_facteur.etat(maire)["codes_secours_restants"] == 8


# ── 2. Aucun contournement ───────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestContournements:
    def test_un_lien_magique_ne_suffit_pas_sur_un_compte_protege(self, client, maire):
        _proteger(maire)
        uid, jeton = _lien(maire)
        seul = client.get(f"/api/magic-login/{uid}/{jeton}/")
        assert seul.status_code == 401 and seul.data["code"] == "CODE_REQUIS"
        faux = client.post(f"/api/magic-login/{uid}/{jeton}/", {"code": "000000"}, format="json")
        assert faux.status_code == 401
        bon = client.post(f"/api/magic-login/{uid}/{jeton}/", {"code": _code(maire)}, format="json")
        assert bon.status_code == 200 and bon.data["token"] and bon.data["refresh"]

    def test_un_lien_magique_suffit_sur_un_compte_sans_second_facteur(self, client, citoyen):
        uid, jeton = _lien(citoyen)
        reponse = client.get(f"/api/magic-login/{uid}/{jeton}/")
        assert reponse.status_code == 200 and reponse.data["token"]

    def test_le_lien_d_activation_suit_la_meme_regle(self, client, maire):
        """Il reste valable sept jours et rouvre une session à chaque clic."""
        _proteger(maire)
        uid, jeton = _lien(maire)
        assert client.get(f"/api/activate-account/{uid}/{jeton}/").status_code == 401
        bon = client.post(f"/api/activate-account/{uid}/{jeton}/", {"code": _code(maire)}, format="json")
        assert bon.status_code == 200 and bon.data["token"]

    def test_la_connexion_grafana_matrix_exige_le_code_avant_le_mot_de_passe(self, maire):
        _proteger(maire)
        navigateur = Client()
        sans = navigateur.post("/accounts/login/", {"username": maire.email, "password": MDP})
        assert sans.status_code == 200 and "_auth_user_id" not in navigateur.session
        avec = navigateur.post("/accounts/login/",
                               {"username": maire.email, "password": MDP, "code": _code(maire)})
        assert avec.status_code == 302 and navigateur.session["_auth_user_id"] == str(maire.pk)

    def test_la_connexion_grafana_matrix_reste_ouverte_sans_second_facteur(self, citoyen):
        navigateur = Client()
        reponse = navigateur.post("/accounts/login/", {"username": citoyen.email, "password": MDP})
        assert reponse.status_code == 302

    def test_l_administration_django_exige_le_code(self, admin):
        admin.is_staff = True
        admin.save(update_fields=["is_staff"])
        _proteger(admin)
        navigateur = Client()
        page = navigateur.get("/django-admin/login/")
        assert page.status_code == 200 and b'name="code"' in page.content
        sans = navigateur.post("/django-admin/login/", {"username": admin.email, "password": MDP})
        assert "_auth_user_id" not in navigateur.session and sans.status_code == 200
        avec = navigateur.post("/django-admin/login/",
                               {"username": admin.email, "password": MDP, "code": _code(admin)})
        assert avec.status_code == 302 and navigateur.session["_auth_user_id"] == str(admin.pk)

    def test_les_formulaires_par_session_sont_freines_eux_aussi(self, citoyen):
        navigateur = Client()
        for _ in range(frein.ECHECS_SANS_DELAI + 1):
            navigateur.post("/accounts/login/", {"username": citoyen.email, "password": "faux"})
        bon = navigateur.post("/accounts/login/", {"username": citoyen.email, "password": MDP})
        assert bon.status_code == 200 and "_auth_user_id" not in navigateur.session
        assert "Trop d&#x27;essais" in bon.content.decode() or "Trop d'essais" in bon.content.decode()

    def test_reinitialiser_son_mot_de_passe_ne_retire_pas_le_second_facteur(self, client, maire):
        _proteger(maire)
        uid, jeton = _lien(maire)
        nouveau = "Un-tout-autre-mot-de-passe-2027"
        assert client.post(f"/api/reset-password/{uid}/{jeton}/",
                           {"new_password": nouveau}, format="json").status_code == 204
        assert client.post(JETON, {"email": maire.email, "password": nouveau}, format="json").status_code == 401
        etape = client.post(CODE, {"email": maire.email, "code": _code(maire)}, format="json").data["jeton_etape"]
        assert client.post(JETON, {"email": maire.email, "password": nouveau,
                                   "jeton_etape": etape}, format="json").status_code == 200


# ── 3. Le frein ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestFrein:
    def _rater(self, client, email, fois, **extra):
        return [client.post(JETON, {"email": email, "password": "faux", **extra}, format="json")
                for _ in range(fois)]

    def test_cinq_echecs_sans_delai_puis_on_attend_meme_avec_le_bon_mot_de_passe(self, client, citoyen):
        reponses = self._rater(client, citoyen.email, frein.ECHECS_SANS_DELAI)
        assert {r.status_code for r in reponses} == {401}
        sixieme = self._rater(client, citoyen.email, 1)[0]
        assert sixieme.status_code == 429 and int(sixieme.data["attendre"]) == frein.DELAIS_SECONDES[0]
        bon = client.post(JETON, {"email": citoyen.email, "password": MDP}, format="json")
        assert bon.status_code == 429 and "access" not in bon.data

    def test_le_delai_double_et_plafonne_a_un_quart_d_heure(self, db):
        cle = frein.cle(frein.ETAPE_MOT_DE_PASSE, "x@exemple.test")
        delais = [frein.echec(cle) for _ in range(frein.ECHECS_SANS_DELAI + 9)]
        assert delais[:frein.ECHECS_SANS_DELAI] == [0] * frein.ECHECS_SANS_DELAI
        assert delais[frein.ECHECS_SANS_DELAI:frein.ECHECS_SANS_DELAI + 6] == list(frein.DELAIS_SECONDES)
        assert set(delais[frein.ECHECS_SANS_DELAI + 6:]) == {900}

    def test_jamais_de_verrouillage_definitif(self, client, citoyen):
        self._rater(client, citoyen.email, frein.ECHECS_SANS_DELAI + 30)
        FreinConnexion.objects.update(bloque_jusqua=timezone.now() - datetime.timedelta(seconds=1))
        reponse = client.post(JETON, {"email": citoyen.email, "password": MDP}, format="json")
        assert reponse.status_code == 200
        assert not FreinConnexion.objects.exists()  # la réussite efface le compteur

    def test_une_adresse_inconnue_est_freinee_comme_une_autre(self, client, citoyen):
        connu = [r.status_code for r in self._rater(client, citoyen.email, frein.ECHECS_SANS_DELAI + 2)]
        inconnu = [r.status_code for r in self._rater(client, "personne@nulle-part.test", frein.ECHECS_SANS_DELAI + 2)]
        assert connu == inconnu

    def test_un_appareil_connu_n_est_pas_ralenti_par_les_echecs_d_un_inconnu(self, client, citoyen):
        """Sinon n'importe qui pourrait empêcher un maire d'entrer, rien qu'avec son adresse."""
        appareil = client.post(JETON, {"email": citoyen.email, "password": MDP}, format="json").data["appareil"]
        self._rater(client, citoyen.email, frein.ECHECS_SANS_DELAI + 5)
        inconnu = client.post(JETON, {"email": citoyen.email, "password": MDP}, format="json")
        assert inconnu.status_code == 429
        connu = client.post(JETON, {"email": citoyen.email, "password": MDP, "appareil": appareil}, format="json")
        assert connu.status_code == 200
        assert connu.data["appareil"] == appareil and connu.data["appareil_nouveau"] is False

    def test_un_jeton_d_appareil_invente_ne_donne_aucun_passe_droit(self, client, citoyen):
        self._rater(client, citoyen.email, frein.ECHECS_SANS_DELAI + 1)
        reponse = client.post(JETON, {"email": citoyen.email, "password": MDP,
                                      "appareil": "x" * 43}, format="json")
        assert reponse.status_code == 429

    def test_le_code_est_freine_par_compte_lui_aussi(self, client, maire):
        _proteger(maire)
        for _ in range(frein.ECHECS_SANS_DELAI):
            assert client.post(CODE, {"email": maire.email, "code": "000000"}, format="json").status_code == 401
        assert client.post(CODE, {"email": maire.email, "code": "000000"}, format="json").status_code == 429
        assert client.post(CODE, {"email": maire.email, "code": _code(maire)}, format="json").status_code == 429

    def test_les_essais_sans_code_ne_ralentissent_pas_qui_a_le_code(self, client, maire):
        """Un inconnu qui martèle des mots de passe sur un compte protégé ne gêne pas le
        titulaire, même depuis un appareil neuf : avoir donné le code lui vaut son compteur."""
        _proteger(maire)
        self._rater(client, maire.email, frein.ECHECS_SANS_DELAI + 5)
        etape = client.post(CODE, {"email": maire.email, "code": _code(maire)}, format="json").data["jeton_etape"]
        reponse = client.post(JETON, {"email": maire.email, "password": MDP, "jeton_etape": etape}, format="json")
        assert reponse.status_code == 200

    def test_un_compteur_oublie_au_bout_d_un_jour(self, db):
        cle = frein.cle(frein.ETAPE_MOT_DE_PASSE, "y@exemple.test")
        for _ in range(frein.ECHECS_SANS_DELAI):
            frein.echec(cle)
        FreinConnexion.objects.update(dernier_echec=timezone.now() - frein.OUBLI - datetime.timedelta(minutes=1))
        assert frein.echec(cle) == 0
        assert FreinConnexion.objects.get(cle=cle).echecs == 1

    def test_la_demande_de_reinitialisation_est_freinee_en_silence(self, client, citoyen):
        mail.outbox.clear()
        reponses = [client.post("/api/reset-password/request/", {"email": citoyen.email}, format="json")
                    for _ in range(frein.ECHECS_SANS_DELAI + 4)]
        assert {r.status_code for r in reponses} == {200}
        assert len({str(r.data) for r in reponses}) == 1
        assert len(mail.outbox) <= frein.ECHECS_SANS_DELAI + 1


# ── 4. Quinze jours, puis l'obligation ───────────────────────────────────────────────────────

@pytest.mark.django_db
class TestObligation:
    def test_qui_est_a_pouvoir(self, create_user, citoyen, maire, admin):
        assert second_facteur.est_a_pouvoir(maire) and second_facteur.est_a_pouvoir(admin)
        assert not second_facteur.est_a_pouvoir(citoyen)
        for role in ("SECOURS", "REGULATEUR"):
            assert second_facteur.est_a_pouvoir(
                create_user(username=f"{role}@frein.test", email=f"{role}@frein.test", type=role))

    def test_un_membre_de_bureau_et_un_encadrant_sont_a_pouvoir(self, create_user):
        itype, _ = InstitutionType.objects.get_or_create(code="ASSO_FREIN", defaults={"libelle": "Association"})
        association = Institution.objects.create(nom="Association essai frein", type=itype)
        tresorier = create_user(username="tresorier@frein.test", email="tresorier@frein.test")
        adherent = create_user(username="adherent@frein.test", email="adherent@frein.test")
        chef = create_user(username="chef@frein.test", email="chef@frein.test")
        ContactInstitution.objects.create(institution=association, utilisateur=tresorier, actif=True, membre_bureau=True)
        ContactInstitution.objects.create(institution=association, utilisateur=adherent, actif=True)
        equipe = Team.objects.create(name="Équipe essai frein", institution=association)
        equipe.membres_encadrement.add(chef)
        assert second_facteur.est_a_pouvoir(tresorier)
        assert second_facteur.est_a_pouvoir(chef)
        assert not second_facteur.est_a_pouvoir(adherent)

    def test_une_machine_n_est_jamais_concernee(self, create_user):
        pont = create_user(username="pont@frein.test", email="pont@frein.test", type="AUT_LOCALE")
        pont.compte_service_pont = True
        pont.save(update_fields=["compte_service_pont"])
        assert not second_facteur.est_a_pouvoir(pont)
        assert second_facteur.etat(pont)["requis"] is False

    def test_un_compte_marque_machine_est_dispense_et_la_commande_le_pose(self, client, create_user, capsys):
        """Le pont Matrix, un script : un rôle, mais pas de téléphone. Sans marquage il serait
        pris pour un compte à pouvoir et cesserait de se connecter au bout de quinze jours."""
        from django.core.management import CommandError, call_command
        robot = create_user(username="robot@frein.test", email="robot@frein.test", type="ADMIN", password=MDP)
        self._echeance_passee(robot)
        assert client.post(JETON, {"email": robot.email, "password": MDP}, format="json").status_code == 403

        call_command("comptes_a_proteger")
        assert "robot@frein.test" in capsys.readouterr().out

        call_command("marquer_compte_machine", robot.email)
        robot.refresh_from_db()
        assert robot.compte_machine and robot.second_facteur_exige_le is None
        assert not second_facteur.est_a_pouvoir(robot)
        assert client.post(JETON, {"email": robot.email, "password": MDP}, format="json").status_code == 200
        capsys.readouterr()  # la confirmation du marquage cite l'adresse : on repart d'une sortie vide
        call_command("comptes_a_proteger")
        assert "robot@frein.test" not in capsys.readouterr().out

        call_command("marquer_compte_machine", robot.email, "--retirer")
        robot.refresh_from_db()
        assert not robot.compte_machine and second_facteur.est_a_pouvoir(robot)
        with pytest.raises(CommandError):
            call_command("marquer_compte_machine", "personne@nulle-part.test")

    def test_on_ne_marque_pas_machine_un_compte_qui_a_un_second_facteur(self, maire):
        from django.core.management import CommandError, call_command
        _proteger(maire)
        with pytest.raises(CommandError):
            call_command("marquer_compte_machine", maire.email)
        maire.refresh_from_db()
        assert not maire.compte_machine

    def test_le_compte_de_service_d_un_satellite_non_plus(self, create_user):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_FREIN", defaults={"libelle": "Mairie"})
        mairie = Institution.objects.create(nom="Mairie essai frein", type=itype)
        service = create_user(username="sat@frein.test", email="sat@frein.test", type="AUT_LOCALE")
        Satellite.objects.create(nom="satellite-frein", institution=mairie, compte_service=service)
        assert not second_facteur.est_a_pouvoir(service)

    def test_le_delai_court_a_partir_du_premier_constat(self, client, maire):
        avant = timezone.now()
        reponse = client.post(JETON, {"email": maire.email, "password": MDP}, format="json")
        assert reponse.status_code == 200
        etat = reponse.data["user"]["second_facteur"]
        assert etat["requis"] and not etat["actif"] and not etat["bloquant"]
        maire.refresh_from_db()
        assert avant + datetime.timedelta(days=15) <= maire.second_facteur_exige_le <= timezone.now() + datetime.timedelta(days=15)
        # un second passage ne repousse pas l'échéance
        echeance = maire.second_facteur_exige_le
        client.post(JETON, {"email": maire.email, "password": MDP}, format="json")
        maire.refresh_from_db()
        assert maire.second_facteur_exige_le == echeance

    def test_un_simple_compte_n_a_ni_delai_ni_obligation(self, client, citoyen):
        etat = client.post(JETON, {"email": citoyen.email, "password": MDP}, format="json").data["user"]["second_facteur"]
        assert etat["requis"] is False and etat["date_limite"] is None
        citoyen.refresh_from_db()
        assert citoyen.second_facteur_exige_le is None

    def _echeance_passee(self, utilisateur):
        utilisateur.second_facteur_exige_le = timezone.now() - datetime.timedelta(minutes=1)
        utilisateur.save(update_fields=["second_facteur_exige_le"])

    def test_apres_le_delai_plus_de_session_mais_de_quoi_activer(self, client, maire):
        self._echeance_passee(maire)
        reponse = client.post(JETON, {"email": maire.email, "password": MDP}, format="json")
        assert reponse.status_code == 403
        assert reponse.data["code"] == "SECOND_FACTEUR_A_ACTIVER"
        assert "access" not in reponse.data and "refresh" not in reponse.data
        jeton = reponse.data["jeton_enrolement"]

        preparation = client.post("/api/second-facteur/preparer/", {"jeton_enrolement": jeton}, format="json")
        assert preparation.status_code == 200
        assert preparation.data["adresse"].startswith("otpauth://totp/")
        assert "<svg" in preparation.data["qr_svg"]

        faux = client.post("/api/second-facteur/confirmer/",
                           {"jeton_enrolement": jeton, "code": "000000"}, format="json")
        assert faux.status_code == 400
        bon = client.post("/api/second-facteur/confirmer/", {
            "jeton_enrolement": jeton,
            "code": code_au_pas(preparation.data["secret"], pas_courant()),
        }, format="json")
        assert bon.status_code == 200
        assert len(bon.data["codes_secours"]) == 10
        assert bon.data["session"]["access"] and bon.data["etat"]["actif"]

    def test_apres_le_delai_un_mauvais_mot_de_passe_ne_donne_rien(self, client, maire):
        self._echeance_passee(maire)
        reponse = client.post(JETON, {"email": maire.email, "password": "faux"}, format="json")
        assert reponse.status_code == 401 and "jeton_enrolement" not in reponse.data

    def test_un_jeton_d_activation_invente_ne_donne_rien(self, client, maire):
        for chemin in ("preparer", "confirmer"):
            reponse = client.post(f"/api/second-facteur/{chemin}/",
                                  {"jeton_enrolement": "invente", "code": "123456"}, format="json")
            assert reponse.status_code == 401
        assert not SecondFacteur.objects.exists()

    def test_apres_le_delai_le_lien_magique_mene_aussi_a_l_activation(self, client, maire):
        self._echeance_passee(maire)
        uid, jeton = _lien(maire)
        reponse = client.get(f"/api/magic-login/{uid}/{jeton}/")
        assert reponse.status_code == 403 and reponse.data["jeton_enrolement"]

    def test_apres_le_delai_une_session_ouverte_ne_se_renouvelle_plus(self, client, maire, citoyen):
        session = client.post(JETON, {"email": maire.email, "password": MDP}, format="json").data
        autre = client.post(JETON, {"email": citoyen.email, "password": MDP}, format="json").data
        assert client.post("/api/token/refresh/", {"refresh": session["refresh"]}, format="json").status_code == 200
        session = client.post(JETON, {"email": maire.email, "password": MDP}, format="json").data
        self._echeance_passee(maire)
        refus = client.post("/api/token/refresh/", {"refresh": session["refresh"]}, format="json")
        assert refus.status_code == 401 and refus.data["code"] == "SECOND_FACTEUR_A_ACTIVER"
        assert client.post("/api/token/refresh/", {"refresh": autre["refresh"]}, format="json").status_code == 200

    def test_un_jeton_de_renouvellement_invalide_reste_refuse_proprement(self, client, db):
        assert client.post("/api/token/refresh/", {"refresh": "invente"}, format="json").status_code == 401
        assert client.post("/api/token/refresh/", {}, format="json").status_code == 400

    def test_les_formulaires_par_session_refusent_apres_le_delai(self, maire):
        self._echeance_passee(maire)
        navigateur = Client()
        reponse = navigateur.post("/accounts/login/", {"username": maire.email, "password": MDP})
        assert reponse.status_code == 200 and "_auth_user_id" not in navigateur.session
        assert "activer son code" in reponse.content.decode()

    def test_sur_un_satellite_rien_n_est_demande(self, client, maire, settings):
        """Décision de Sylvain : pas de code sur un satellite coupé d'Internet."""
        _proteger(maire)
        self._echeance_passee(maire)
        settings.SATELLITE_ID = "satellite-de-test"
        assert client.post(DEBUT, {"email": maire.email}, format="json").data == {"etape": "mot_de_passe"}
        reponse = client.post(JETON, {"email": maire.email, "password": MDP}, format="json")
        assert reponse.status_code == 200
        assert reponse.data["user"]["second_facteur"]["applicable"] is False
        assert client.post("/api/second-facteur/preparer/", {}, format="json").status_code == 404


# ── 5. Gérer son second facteur ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestGestion:
    def _connecte(self, utilisateur):
        c = APIClient()
        c.force_authenticate(user=utilisateur)
        return c

    def test_activer_depuis_son_compte_redemande_le_mot_de_passe(self, citoyen):
        c = self._connecte(citoyen)
        assert c.post("/api/second-facteur/preparer/", {}, format="json").status_code == 400
        assert c.post("/api/second-facteur/preparer/", {"mot_de_passe": "faux"}, format="json").status_code == 400
        preparation = c.post("/api/second-facteur/preparer/", {"mot_de_passe": MDP}, format="json")
        assert preparation.status_code == 200
        # préparé n'est pas actif : la connexion ne demande encore aucun code
        assert second_facteur.second_facteur_actif(citoyen) is None
        confirmation = c.post("/api/second-facteur/confirmer/",
                              {"code": code_au_pas(preparation.data["secret"], pas_courant())}, format="json")
        assert confirmation.status_code == 200 and "session" not in confirmation.data
        assert c.get("/api/second-facteur/").data["actif"] is True

    def test_un_compte_sans_mot_de_passe_peut_activer_le_sien(self, create_user):
        """Compte créé par import, connecté par lien magique : il n'a rien à redonner."""
        importe = create_user(username="importe@frein.test", email="importe@frein.test")
        importe.set_unusable_password()
        importe.save()
        assert self._connecte(importe).post("/api/second-facteur/preparer/", {}, format="json").status_code == 200

    def test_on_ne_prepare_pas_par_dessus_un_second_facteur_actif(self, citoyen):
        _proteger(citoyen)
        reponse = self._connecte(citoyen).post("/api/second-facteur/preparer/", {"mot_de_passe": MDP}, format="json")
        assert reponse.status_code == 409

    def test_retirer_demande_un_code_et_un_compte_a_pouvoir_doit_reactiver_aussitot(self, maire):
        _proteger(maire)
        c = self._connecte(maire)
        assert c.post("/api/second-facteur/retirer/", {"code": "000000"}, format="json").status_code == 400
        assert second_facteur.second_facteur_actif(maire) is not None
        reponse = c.post("/api/second-facteur/retirer/", {"code": _code(maire)}, format="json")
        assert reponse.status_code == 200
        assert reponse.data["etat"]["actif"] is False and reponse.data["etat"]["bloquant"] is True
        assert not CodeSecours.objects.filter(utilisateur=maire).exists()

    def test_renouveler_les_codes_de_secours_invalide_les_anciens(self, client, maire):
        anciens = _proteger(maire)
        c = self._connecte(maire)
        assert c.post("/api/second-facteur/codes-secours/", {"code": "000000"}, format="json").status_code == 400
        nouveaux = c.post("/api/second-facteur/codes-secours/", {"code": _code(maire)}, format="json").data["codes_secours"]
        assert len(nouveaux) == 10 and not set(nouveaux) & set(anciens)
        assert client.post(CODE, {"email": maire.email, "code": anciens[0]}, format="json").status_code == 401
        assert client.post(CODE, {"email": maire.email, "code": nouveaux[0]}, format="json").status_code == 200

    def test_un_administrateur_reinitialise_et_le_titulaire_est_prevenu(self, admin, maire, citoyen):
        _proteger(maire)
        chemin = f"/api/users/{maire.pk}/reinitialiser-second-facteur/"
        assert self._connecte(citoyen).post(chemin).status_code in (403, 404)
        assert self._connecte(maire).post(chemin).status_code == 403
        assert second_facteur.second_facteur_actif(maire) is not None

        mail.outbox.clear()
        reponse = self._connecte(admin).post(chemin)
        assert reponse.status_code == 200
        assert second_facteur.second_facteur_actif(maire) is None
        assert [m.to for m in mail.outbox] == [[maire.email]]
        # pas de nouveau délai : la prochaine connexion doit activer avant d'entrer
        suite = APIClient().post(JETON, {"email": maire.email, "password": MDP}, format="json")
        assert suite.status_code == 403 and suite.data["code"] == "SECOND_FACTEUR_A_ACTIVER"
        assert self._connecte(admin).post(chemin).status_code == 400  # plus rien à retirer

    def test_un_administrateur_voit_qui_est_protege_les_autres_non(self, admin, maire, citoyen):
        _proteger(maire)
        vu_par_admin = self._connecte(admin).get(f"/api/users/{maire.pk}/")
        assert vu_par_admin.status_code == 200 and vu_par_admin.data["second_facteur"] == {"actif": True}

    def test_la_commande_de_secours(self, maire):
        from django.core.management import CommandError, call_command
        _proteger(maire)
        call_command("reinitialiser_second_facteur", maire.email)
        assert second_facteur.second_facteur_actif(maire) is None
        with pytest.raises(CommandError):
            call_command("reinitialiser_second_facteur", maire.email)
        with pytest.raises(CommandError):
            call_command("reinitialiser_second_facteur", "personne@nulle-part.test")


# ── 5 bis. Le code envoyé par e-mail ─────────────────────────────────────────────────────────

def _code_recu(outbox=None):
    """Le code lu dans le dernier message arrivé, comme le lirait le titulaire."""
    corps = (outbox or mail.outbox)[-1].body
    return re.search(r"code de connexion : (\d{3}) (\d{3})", corps).group(1, 2)


def _proteger_par_mail(utilisateur):
    """Active le mode e-mail, comme le ferait le titulaire. Rend les codes de secours."""
    mail.outbox.clear()
    preparation = second_facteur.preparer(utilisateur, "email")
    assert preparation["mode"] == "email"
    codes = second_facteur.confirmer(utilisateur, "".join(_code_recu()))
    assert codes
    mail.outbox.clear()
    # L'activation vient d'envoyer un code : on efface le délai d'une minute pour la suite.
    SecondFacteur.objects.filter(utilisateur=utilisateur).update(code_mail_envoye_le=None)
    frein.reussite(frein.cle(second_facteur.ETAPE_ENVOI, utilisateur.email))
    return codes


@pytest.mark.django_db
class TestCodeParMail:
    def test_l_adresse_fait_partir_le_code_sans_le_dire(self, client, maire, citoyen):
        _proteger_par_mail(maire)
        _proteger(citoyen)
        par_mail = client.post(DEBUT, {"email": maire.email}, format="json")
        par_application = client.post(DEBUT, {"email": citoyen.email}, format="json")
        # même réponse : rien ne dit à un inconnu comment un compte est protégé
        assert par_mail.data == par_application.data == {"etape": "code"}
        assert [m.to for m in mail.outbox] == [[maire.email]]

    def test_le_code_n_est_ni_dans_l_objet_ni_en_base(self, client, maire):
        _proteger_par_mail(maire)
        client.post(DEBUT, {"email": maire.email}, format="json")
        code = "".join(_code_recu())
        assert code not in mail.outbox[-1].subject and " ".join(_code_recu()) not in mail.outbox[-1].subject
        with connection.cursor() as curseur:
            curseur.execute(f"SELECT * FROM {SecondFacteur._meta.db_table}")
            brut = " ".join(str(v) for ligne in curseur.fetchall() for v in ligne)
        assert code not in brut

    def test_parcours_complet_code_recu_puis_mot_de_passe(self, client, maire):
        _proteger_par_mail(maire)
        client.post(DEBUT, {"email": maire.email}, format="json")
        # sans le code, le mot de passe n'est toujours pas examiné
        assert client.post(JETON, {"email": maire.email, "password": MDP}, format="json").status_code == 401
        etape = client.post(CODE, {"email": maire.email, "code": " ".join(_code_recu())}, format="json")
        assert etape.status_code == 200
        session = client.post(JETON, {"email": maire.email, "password": MDP,
                                      "jeton_etape": etape.data["jeton_etape"]}, format="json")
        assert session.status_code == 200
        assert session.data["user"]["second_facteur"]["mode"] == "email"

    def test_le_code_ne_sert_qu_une_fois(self, client, maire):
        _proteger_par_mail(maire)
        client.post(DEBUT, {"email": maire.email}, format="json")
        code = "".join(_code_recu())
        assert client.post(CODE, {"email": maire.email, "code": code}, format="json").status_code == 200
        assert client.post(CODE, {"email": maire.email, "code": code}, format="json").status_code == 401

    def test_le_code_expire_au_bout_de_cinq_minutes(self, client, maire):
        _proteger_par_mail(maire)
        client.post(DEBUT, {"email": maire.email}, format="json")
        code = "".join(_code_recu())
        facteur = SecondFacteur.objects.get(utilisateur=maire)
        assert (datetime.timedelta(minutes=4, seconds=50)
                < facteur.code_mail_expire_le - timezone.now() <= datetime.timedelta(minutes=5))
        SecondFacteur.objects.filter(pk=facteur.pk).update(
            code_mail_expire_le=timezone.now() - datetime.timedelta(seconds=1))
        assert client.post(CODE, {"email": maire.email, "code": code}, format="json").status_code == 401

    def test_cinq_essais_rates_annulent_le_code(self, maire):
        _proteger_par_mail(maire)
        second_facteur.envoyer_code_par_mail(None, maire)
        code = "".join(_code_recu())
        faux = "000000" if code != "000000" else "111111"
        for _ in range(second_facteur.ESSAIS_CODE_MAIL):
            assert not second_facteur.verifier_code(maire, faux)
        assert not second_facteur.verifier_code(maire, code)

    def test_un_envoi_par_minute_au_plus(self, client, maire):
        _proteger_par_mail(maire)
        for _ in range(4):
            client.post(DEBUT, {"email": maire.email}, format="json")
            client.post("/api/connexion/envoyer-code/", {"email": maire.email}, format="json")
        assert len(mail.outbox) == 1

    def test_renvoyer_le_code_repond_pareil_pour_toute_adresse(self, client, maire, citoyen):
        _proteger_par_mail(maire)
        reponses = [client.post("/api/connexion/envoyer-code/", {"email": adresse}, format="json")
                    for adresse in (maire.email, citoyen.email, "personne@nulle-part.test")]
        assert {r.status_code for r in reponses} == {200}
        assert len({str(r.data) for r in reponses}) == 1
        assert [m.to for m in mail.outbox] == [[maire.email]]

    def test_un_inconnu_qui_fait_partir_des_codes_n_epuise_pas_le_quota_du_titulaire(self, client, maire):
        """Sinon connaître l'adresse d'un maire suffirait à l'empêcher de recevoir son code."""
        _proteger_par_mail(maire)
        appareil, _ = frein.retenir_appareil(maire, "")
        for _ in range(frein.ECHECS_SANS_DELAI + 3):   # l'inconnu : quota épuisé, puis freiné
            SecondFacteur.objects.filter(utilisateur=maire).update(code_mail_envoye_le=None)
            client.post(DEBUT, {"email": maire.email}, format="json")
        envoyes = len(mail.outbox)
        SecondFacteur.objects.filter(utilisateur=maire).update(code_mail_envoye_le=None)
        client.post(DEBUT, {"email": maire.email}, format="json")
        assert len(mail.outbox) == envoyes                     # l'inconnu n'obtient plus rien
        client.post(DEBUT, {"email": maire.email, "appareil": appareil}, format="json")
        assert len(mail.outbox) == envoyes + 1                 # le titulaire, si

    def test_un_code_de_secours_marche_aussi_en_mode_e_mail(self, client, maire):
        codes = _proteger_par_mail(maire)
        assert client.post(CODE, {"email": maire.email, "code": codes[0]}, format="json").status_code == 200

    def test_il_faut_un_mot_de_passe_pour_choisir_ce_mode(self, create_user):
        """Sans mot de passe, tout tiendrait à la boîte aux lettres : un seul facteur."""
        importe = create_user(username="lien@frein.test", email="lien@frein.test")
        importe.set_unusable_password()
        importe.save()
        c = APIClient()
        c.force_authenticate(user=importe)
        reponse = c.post("/api/second-facteur/preparer/", {"mode": "email"}, format="json")
        assert reponse.status_code == 400 and "mot de passe" in reponse.data["detail"]
        assert not SecondFacteur.objects.filter(utilisateur=importe).exists()

    def test_activer_le_mode_e_mail_depuis_son_compte(self, citoyen):
        c = APIClient()
        c.force_authenticate(user=citoyen)
        mail.outbox.clear()
        preparation = c.post("/api/second-facteur/preparer/", {"mode": "email", "mot_de_passe": MDP}, format="json")
        assert preparation.status_code == 200
        assert preparation.data == {"mode": "email", "adresse": second_facteur.masquer_adresse(citoyen.email)}
        assert citoyen.email not in str(preparation.data)
        assert c.post("/api/second-facteur/confirmer/", {"code": "000000"}, format="json").status_code == 400
        confirmation = c.post("/api/second-facteur/confirmer/", {"code": "".join(_code_recu())}, format="json")
        assert confirmation.status_code == 200 and len(confirmation.data["codes_secours"]) == 10
        assert confirmation.data["etat"]["mode"] == "email"

    def test_retirer_demande_un_code_que_l_on_se_fait_envoyer(self, maire):
        _proteger_par_mail(maire)
        c = APIClient()
        c.force_authenticate(user=maire)
        envoi = c.post("/api/second-facteur/envoyer-code/", {}, format="json")
        assert envoi.status_code == 200 and envoi.data["envoye"] is True
        assert c.post("/api/second-facteur/envoyer-code/", {}, format="json").data["envoye"] is False
        assert c.post("/api/second-facteur/retirer/", {"code": "".join(_code_recu())}, format="json").status_code == 200
        assert second_facteur.second_facteur_actif(maire) is None

    def test_un_lien_recu_par_e_mail_demande_alors_le_mot_de_passe(self, client, maire):
        """Le lien et le code arriveraient dans la même boîte : ils prouveraient deux fois la
        même chose. Le second facteur d'un lien, en mode e-mail, c'est le mot de passe."""
        _proteger_par_mail(maire)
        uid, jeton = _lien(maire)
        seul = client.get(f"/api/magic-login/{uid}/{jeton}/")
        assert seul.status_code == 401 and seul.data["code"] == "MOT_DE_PASSE_REQUIS"
        assert mail.outbox == []     # aucun code n'est envoyé : il ne servirait à rien ici
        faux = client.post(f"/api/magic-login/{uid}/{jeton}/", {"mot_de_passe": "faux"}, format="json")
        assert faux.status_code == 401 and faux.data["code"] == "MOT_DE_PASSE_REQUIS"
        bon = client.post(f"/api/magic-login/{uid}/{jeton}/", {"mot_de_passe": MDP}, format="json")
        assert bon.status_code == 200 and bon.data["token"]

    def test_la_connexion_grafana_matrix_envoie_le_code_quand_le_champ_est_vide(self, maire):
        _proteger_par_mail(maire)
        navigateur = Client()
        premier = navigateur.post("/accounts/login/", {"username": maire.email, "password": MDP})
        assert premier.status_code == 200 and "_auth_user_id" not in navigateur.session
        assert "un code" in premier.content.decode() and len(mail.outbox) == 1
        second = navigateur.post("/accounts/login/", {"username": maire.email, "password": MDP,
                                                      "code": "".join(_code_recu())})
        assert second.status_code == 302 and navigateur.session["_auth_user_id"] == str(maire.pk)

    def test_le_message_sans_code_est_le_meme_pour_tout_le_monde(self, maire, citoyen):
        _proteger_par_mail(maire)
        pages = [Client().post("/accounts/login/", {"username": adresse, "password": "faux"}).content.decode()
                 for adresse in (maire.email, citoyen.email, "personne@nulle-part.test")]
        erreurs = {re.search(r'class="erreurs">([^<]*)<', page).group(1) for page in pages}
        assert len(erreurs) == 1

    def test_l_adresse_masquee_ne_donne_pas_l_adresse(self):
        assert second_facteur.masquer_adresse("camille.durand@exemple.fr") == "c" + "•" * 13 + "@exemple.fr"
        assert second_facteur.masquer_adresse("a@b.fr") == "a•••@b.fr"


# ── 5 bis. Le code par e-mail À LA DEMANDE, pour un compte à application ─────────────────────

ENVOI = "/api/connexion/envoyer-code/"


@pytest.mark.django_db
class TestCodeParMailALaDemande:
    """Demandé par Sylvain le 15/11/2026 : un compte protégé par une application doit AUSSI
    pouvoir se faire envoyer un code, en plus de l'application et des dix codes de secours."""

    def test_rien_ne_part_tant_qu_on_ne_le_demande_pas(self, client, maire):
        _proteger(maire)
        mail.outbox.clear()
        assert client.post(DEBUT, {"email": maire.email}, format="json").data == {"etape": "code"}
        assert mail.outbox == []     # sinon chaque connexion vaudrait un message

    def test_parcours_complet_code_demande_puis_mot_de_passe(self, client, maire):
        _proteger(maire)
        mail.outbox.clear()
        client.post(DEBUT, {"email": maire.email}, format="json")
        assert client.post(ENVOI, {"email": maire.email}, format="json").status_code == 200
        assert [m.to for m in mail.outbox] == [[maire.email]]
        etape = client.post(CODE, {"email": maire.email, "code": " ".join(_code_recu())}, format="json")
        assert etape.status_code == 200
        # le code reçu ne dispense pas du mot de passe
        assert client.post(JETON, {"email": maire.email, "password": "faux",
                                   "jeton_etape": etape.data["jeton_etape"]}, format="json").status_code == 401
        session = client.post(JETON, {"email": maire.email, "password": MDP,
                                      "jeton_etape": etape.data["jeton_etape"]}, format="json")
        assert session.status_code == 200
        # le compte reste un compte à application : rien n'a changé de mode
        assert session.data["user"]["second_facteur"]["mode"] == "application"

    def test_l_application_et_les_codes_de_secours_marchent_toujours(self, client, maire):
        codes = _proteger(maire)
        client.post(ENVOI, {"email": maire.email}, format="json")
        assert client.post(CODE, {"email": maire.email, "code": _code(maire)}, format="json").status_code == 200
        assert client.post(CODE, {"email": maire.email, "code": codes[0]}, format="json").status_code == 200

    def test_le_code_demande_ne_sert_qu_une_fois_et_expire(self, client, maire):
        _proteger(maire)
        mail.outbox.clear()
        client.post(ENVOI, {"email": maire.email}, format="json")
        code = "".join(_code_recu())
        assert client.post(CODE, {"email": maire.email, "code": code}, format="json").status_code == 200
        assert client.post(CODE, {"email": maire.email, "code": code}, format="json").status_code == 401

        SecondFacteur.objects.filter(utilisateur=maire).update(code_mail_envoye_le=None)
        frein.reussite(frein.cle(second_facteur.ETAPE_ENVOI, maire.email))
        client.post(ENVOI, {"email": maire.email}, format="json")
        code = "".join(_code_recu())
        SecondFacteur.objects.filter(utilisateur=maire).update(
            code_mail_expire_le=timezone.now() - datetime.timedelta(seconds=1))
        assert client.post(CODE, {"email": maire.email, "code": code}, format="json").status_code == 401

    def test_un_envoi_par_minute_au_plus(self, client, maire):
        _proteger(maire)
        mail.outbox.clear()
        for _ in range(4):
            client.post(ENVOI, {"email": maire.email}, format="json")
        assert len(mail.outbox) == 1

    def test_la_reponse_est_la_meme_pour_toute_adresse(self, client, maire, admin, citoyen):
        """Compte à application, compte en mode e-mail, compte sans protection, adresse
        inconnue : rien ne les distingue pour qui demande."""
        _proteger(maire)
        _proteger_par_mail(admin)
        mail.outbox.clear()
        reponses = [client.post(ENVOI, {"email": adresse}, format="json")
                    for adresse in (maire.email, admin.email, citoyen.email, "personne@nulle-part.test")]
        assert {r.status_code for r in reponses} == {200}
        assert len({str(r.data) for r in reponses}) == 1
        # seuls les comptes protégés reçoivent quelque chose
        assert sorted(m.to[0] for m in mail.outbox) == sorted([maire.email, admin.email])

    def test_une_application_pas_encore_activee_ne_recoit_rien(self, client, maire):
        """L'activation prouve que l'application connaît le secret : un code reçu par e-mail
        ne doit pas pouvoir la remplacer."""
        second_facteur.preparer(maire)
        mail.outbox.clear()
        client.post(ENVOI, {"email": maire.email}, format="json")
        assert mail.outbox == []
        assert second_facteur.envoyer_code_par_mail(None, maire, a_la_demande=True) is False

    def test_un_lien_recu_par_e_mail_n_accepte_pas_un_code_recu_par_e_mail(self, client, maire):
        """Le lien et le code arriveraient dans la même boîte : lire les e-mails de quelqu'un
        suffirait à entrer chez lui. Avec un lien, il faut l'application ou un code de secours."""
        _proteger(maire)
        mail.outbox.clear()
        client.post(ENVOI, {"email": maire.email}, format="json")
        code = "".join(_code_recu())
        uid, jeton = _lien(maire)
        refus = client.post(f"/api/magic-login/{uid}/{jeton}/", {"code": code}, format="json")
        assert refus.status_code == 401 and refus.data["code"] == "CODE_REQUIS"
        # et ce refus n'a pas brûlé le code : il sert encore par la porte ordinaire
        assert client.post(CODE, {"email": maire.email, "code": code}, format="json").status_code == 200
        bon = client.post(f"/api/magic-login/{uid}/{jeton}/", {"code": _code(maire)}, format="json")
        assert bon.status_code == 200 and bon.data["token"]

    def test_avec_un_lien_et_sans_telephone_le_mot_de_passe_fait_le_second_facteur(self, client, maire):
        """Lien (boîte aux lettres) + mot de passe (ce que l'on sait) : deux facteurs, sans
        téléphone. Un mot de passe faux est freiné comme ailleurs."""
        _proteger(maire)
        uid, jeton = _lien(maire)
        seul = client.get(f"/api/magic-login/{uid}/{jeton}/")
        assert seul.status_code == 401 and seul.data["code"] == "CODE_REQUIS"
        faux = client.post(f"/api/magic-login/{uid}/{jeton}/", {"mot_de_passe": "faux"}, format="json")
        assert faux.status_code == 401 and faux.data["code"] == "MOT_DE_PASSE_REQUIS"
        bon = client.post(f"/api/magic-login/{uid}/{jeton}/", {"mot_de_passe": MDP}, format="json")
        assert bon.status_code == 200 and bon.data["token"]

    def test_avec_un_lien_un_compte_sans_mot_de_passe_garde_l_application(self, client, create_user):
        importe = create_user(username="sans-mdp@frein.test", email="sans-mdp@frein.test")
        importe.set_unusable_password()
        importe.save()
        _proteger(importe)
        uid, jeton = _lien(importe)
        for essai in ("", "n-importe-quoi"):
            refus = client.post(f"/api/magic-login/{uid}/{jeton}/", {"mot_de_passe": essai}, format="json")
            assert refus.status_code == 401
        bon = client.post(f"/api/magic-login/{uid}/{jeton}/", {"code": _code(importe)}, format="json")
        assert bon.status_code == 200 and bon.data["token"]

    def test_depuis_son_compte_changer_de_telephone_sans_l_ancien(self, maire):
        _proteger(maire)
        mail.outbox.clear()
        c = APIClient()
        c.force_authenticate(user=maire)
        envoi = c.post("/api/second-facteur/envoyer-code/", {}, format="json")
        assert envoi.status_code == 200 and envoi.data["envoye"] is True
        retrait = c.post("/api/second-facteur/retirer/", {"code": "".join(_code_recu())}, format="json")
        assert retrait.status_code == 200
        assert second_facteur.second_facteur_actif(maire) is None

    def test_la_connexion_grafana_matrix_envoie_un_code_quand_le_champ_est_vide(self, maire):
        _proteger(maire)
        mail.outbox.clear()
        navigateur = Client()
        premier = navigateur.post("/accounts/login/", {"username": maire.email, "password": MDP})
        assert premier.status_code == 200 and "_auth_user_id" not in navigateur.session
        assert len(mail.outbox) == 1
        second = navigateur.post("/accounts/login/", {"username": maire.email, "password": MDP,
                                                      "code": "".join(_code_recu())})
        assert second.status_code == 302 and navigateur.session["_auth_user_id"] == str(maire.pk)

    def test_un_inconnu_ne_peut_pas_noyer_la_boite_du_titulaire(self, client, maire):
        """Cinq envois libres pour les appareils inconnus, puis un délai qui s'allonge."""
        _proteger(maire)
        mail.outbox.clear()
        for _ in range(frein.ECHECS_SANS_DELAI + 4):
            SecondFacteur.objects.filter(utilisateur=maire).update(code_mail_envoye_le=None)
            client.post(ENVOI, {"email": maire.email}, format="json")
        assert len(mail.outbox) == frein.ECHECS_SANS_DELAI + 1


# ── 6. Mots de passe ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestMotsDePasse:
    def test_la_reinitialisation_applique_les_regles_de_django(self, client, citoyen):
        """Avant, « huit caractères » suffisait : 12345678 passait."""
        uid, jeton = _lien(citoyen)
        for faible in ("12345678", "password", "court"):
            reponse = client.post(f"/api/reset-password/{uid}/{jeton}/", {"new_password": faible}, format="json")
            assert reponse.status_code == 400, faible
        assert client.post(f"/api/reset-password/{uid}/{jeton}/",
                           {"new_password": "cheval-agrafe-9"}, format="json").status_code == 204

    def test_le_changement_depuis_le_profil_aussi(self, citoyen):
        c = APIClient()
        c.force_authenticate(user=citoyen)
        assert c.post("/api/change-password/", {"old_password": MDP, "new_password": "12345678"}, format="json").status_code == 400
        assert c.post("/api/change-password/", {"old_password": MDP, "new_password": "cheval-agrafe-9"}, format="json").status_code == 204

    def test_douze_caracteres_pour_un_compte_a_pouvoir(self, client, maire):
        uid, jeton = _lien(maire)
        court = client.post(f"/api/reset-password/{uid}/{jeton}/", {"new_password": "cheval-agr9"}, format="json")
        assert court.status_code == 400 and "12 caractères" in court.data["error"]
        assert client.post(f"/api/reset-password/{uid}/{jeton}/",
                           {"new_password": "cheval-agrafe-9"}, format="json").status_code == 204


# ── 7. Rien en clair ─────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRienEnClair:
    def _colonnes(self, table):
        with connection.cursor() as curseur:
            curseur.execute(f"SELECT * FROM {table}")
            return " ".join(str(valeur) for ligne in curseur.fetchall() for valeur in ligne)

    def test_le_secret_est_chiffre_en_base(self, citoyen):
        secret = second_facteur.preparer(citoyen)["secret"]
        brut = self._colonnes(SecondFacteur._meta.db_table)
        assert secret not in brut
        assert SecondFacteur.objects.get(utilisateur=citoyen).secret == secret

    def test_les_codes_de_secours_ne_sont_gardes_qu_en_empreinte(self, citoyen):
        codes = _proteger(citoyen)
        brut = self._colonnes(CodeSecours._meta.db_table)
        for code in codes:
            assert code not in brut and code.replace("-", "") not in brut

    def test_les_compteurs_ne_portent_ni_adresse_ni_appareil(self, client, citoyen):
        appareil = client.post(JETON, {"email": citoyen.email, "password": MDP}, format="json").data["appareil"]
        client.post(JETON, {"email": citoyen.email, "password": "faux"}, format="json")
        client.post(JETON, {"email": citoyen.email, "password": "faux", "appareil": appareil}, format="json")
        assert FreinConnexion.objects.count() == 2
        for table in (FreinConnexion._meta.db_table, AppareilConnu._meta.db_table):
            brut = self._colonnes(table)
            assert citoyen.email not in brut and appareil not in brut

    def test_le_libelle_d_appareil_est_grossier(self):
        agent = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Mobile Safari/537.36"
        assert frein.libelle_appareil(agent) == "Chrome sur Android"
        assert frein.libelle_appareil("") == "Navigateur"

    def test_on_ne_garde_que_les_vingt_derniers_appareils(self, citoyen):
        for i in range(frein.APPAREILS_GARDES + 5):
            frein.retenir_appareil(citoyen, f"appareil-numero-{i:03d}-" + "z" * 30)
        assert AppareilConnu.objects.filter(utilisateur=citoyen).count() == frein.APPAREILS_GARDES
