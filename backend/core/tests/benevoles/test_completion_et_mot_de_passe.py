"""Page de complétion de fiche, et mot de passe choisi après coup.

Points 2 et 3 du déroulé d'enrôlement (11/11/2026). Ce qu'ils verrouillent :

1. **Le mot de passe est FACULTATIF et complémentaire.** Un compte créé par import n'en a
   aucun — `create_user(password=None)` pose un mot de passe inutilisable — et se connecte par
   lien magique. En poser un n'enlève rien : les deux chemins coexistent.
2. **`ChangePasswordView` ne peut pas servir** : elle exige l'ancien mot de passe, qu'un compte
   importé n'a pas. Sans vue dédiée, un bénévole ne pourrait JAMAIS s'en donner un.
3. **Changer d'adresse change d'équipe départementale**, et retire de l'ancienne. Quelqu'un qui
   déménage de Gironde en Savoie ne doit pas rester mobilisable en Gironde ni figurer dans deux
   salons Matrix départementaux.
4. **Le secteur est en lecture seule** : le laisser saisir permettrait de se déclarer dans un
   département où l'on n'habite pas, donc de rejoindre une équipe qui n'est pas la sienne.
"""
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, EchelonEquipe, FicheBenevole, Institution, InstitutionType, Team, User,
)

URL_FICHE = "/api/ma-fiche-benevole/"
URL_MDP = "/api/definir-mon-mot-de-passe/"


@pytest.fixture
def asso(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_COMP',
                                                     defaults={'libelle': 'Association'})
    return Institution.objects.create(nom="Association Completion", type=itype)


@pytest.fixture
def equipes(asso):
    g = Team.objects.create(name="Gironde", institution=asso,
                            echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="33")
    s = Team.objects.create(name="Savoie", institution=asso,
                            echelon=EchelonEquipe.DEPARTEMENTAL, territoire_code="73")
    return g, s


@pytest.fixture
def benevole(create_user, asso, equipes):
    """Un bénévole tel que l'import le crée : sans mot de passe utilisable."""
    u = User.objects.create_user(username="ben@essai.invalide", email="ben@essai.invalide",
                                 password=None, first_name="Jean", last_name="Dupont",
                                 type='UTIL_SIMPLE', enabled=True, is_active=True)
    ContactInstitution.objects.create(institution=asso, utilisateur=u, actif=True)
    equipes[0].members.add(u)
    return u


@pytest.fixture
def client(benevole):
    c = APIClient()
    c.force_authenticate(user=benevole)
    return c


@pytest.mark.django_db
class TestMotDePasse:

    def test_un_compte_importe_n_a_PAS_de_mot_de_passe_utilisable(self, benevole):
        """Le point de départ : il se connecte par lien magique, et rien ne lui propose d'en
        choisir un."""
        assert benevole.has_usable_password() is False

    def test_la_fiche_dit_si_un_mot_de_passe_est_defini(self, client):
        """L'interface en a besoin : le libellé change entre « choisir » et « modifier », et
        ça ne se devine pas côté navigateur."""
        assert client.get(URL_FICHE).data['mot_de_passe_defini'] is False

    def test_il_peut_en_choisir_un_SANS_connaitre_l_ancien(self, client, benevole):
        """`ChangePasswordView` exige l'ancien : un compte importé n'en a pas, et ne pourrait
        donc jamais s'en donner un. Pas une faille — l'appelant est déjà authentifié par son
        lien magique, dont la possession prouve l'accès à la boîte mail."""
        reponse = client.post(URL_MDP, {"nouveau_mot_de_passe": "UnMotDePasse!2026"},
                              format='json')
        assert reponse.status_code == 200, reponse.data

        benevole.refresh_from_db()
        assert benevole.has_usable_password() is True
        assert benevole.check_password("UnMotDePasse!2026")

    def test_le_lien_magique_continue_de_fonctionner_apres(self, client, benevole):
        """Complémentaire, pas un remplacement : poser un mot de passe n'invalide pas la
        connexion par email."""
        from core.views import build_magic_link, get_user_from_magic_link
        from django.urls import reverse

        client.post(URL_MDP, {"nouveau_mot_de_passe": "UnMotDePasse!2026"}, format='json')
        benevole.refresh_from_db()

        from django.test import RequestFactory
        requete = RequestFactory().post('/')
        requete.user = benevole
        lien = build_magic_link(requete, benevole, "magic-login")
        uidb64, token = lien.rstrip('/').split('/')[-2:]
        assert get_user_from_magic_link(uidb64, token) == benevole

    def test_un_mot_de_passe_trop_faible_est_refuse_avec_la_raison(self, client):
        """Les messages de Django disent QUOI corriger (« trop court », « trop courant ») :
        les remplacer par « invalide » ferait perdre la seule information utile."""
        reponse = client.post(URL_MDP, {"nouveau_mot_de_passe": "123"}, format='json')
        assert reponse.status_code == 400
        assert len(reponse.data['error']) > 20

    def test_un_mot_de_passe_vide_est_refuse(self, client):
        assert client.post(URL_MDP, {}, format='json').status_code == 400

    def test_un_visiteur_non_connecte_ne_peut_rien_poser(self, benevole):
        assert APIClient().post(URL_MDP, {"nouveau_mot_de_passe": "x"},
                                format='json').status_code in (401, 403)


@pytest.mark.django_db
class TestCompletionDeFiche:

    def test_la_fiche_est_creee_a_la_premiere_lecture(self, client, benevole):
        """L'écran doit s'ouvrir sur un formulaire vide, pas sur une erreur."""
        assert not FicheBenevole.objects.exists()
        assert client.get(URL_FICHE).status_code == 200
        assert FicheBenevole.objects.filter(utilisateur=benevole).exists()

    def test_la_personne_complete_sa_fiche(self, client, benevole):
        with patch('core.imports._geocoder_adresse',
                   return_value=(44.8, -0.5, "33063", "Bordeaux")), \
             patch('core.geo_lookup.commune_secteur_codes',
                   return_value={"epci_code": None, "departement_code": "33",
                                 "region_code": "75"}):
            reponse = client.patch(URL_FICHE, {
                "adresse": "1 place Pey Berland", "code_postal": "33000",
                "ville": "Bordeaux", "disponibilite": "REGULIERE",
                "metier": "Infirmière",
            }, format='json')

        assert reponse.status_code == 200, reponse.data
        fiche = FicheBenevole.objects.get(utilisateur=benevole)
        assert fiche.metier == "Infirmière"
        assert fiche.commune_code == "33063"
        assert fiche.completee_le is not None
        assert reponse.data['est_complete'] is True

    def test_le_secteur_ne_peut_PAS_etre_saisi_a_la_main(self, client, benevole):
        """Le laisser saisir permettrait de se déclarer dans un département où l'on n'habite
        pas, donc de rejoindre une équipe qui n'est pas la sienne."""
        client.patch(URL_FICHE, {"departement_code": "99", "commune_code": "99999"},
                     format='json')
        fiche = FicheBenevole.objects.get(utilisateur=benevole)
        assert fiche.departement_code != "99"
        assert fiche.commune_code != "99999"

    def test_un_demenagement_change_d_equipe_ET_retire_de_l_ancienne(self, client, benevole,
                                                                     equipes):
        """Quelqu'un qui déménage ne doit pas rester mobilisable dans son ancien département,
        ni figurer dans deux salons Matrix départementaux."""
        gironde, savoie = equipes
        assert gironde.members.filter(pk=benevole.pk).exists()

        with patch('core.imports._geocoder_adresse',
                   return_value=(45.56, 5.92, "73065", "Chambéry")), \
             patch('core.geo_lookup.commune_secteur_codes',
                   return_value={"epci_code": None, "departement_code": "73",
                                 "region_code": "84"}):
            client.patch(URL_FICHE, {"adresse": "1 rue de Chambéry",
                                     "code_postal": "73000", "ville": "Chambéry"},
                         format='json')

        assert savoie.members.filter(pk=benevole.pk).exists()
        assert not gironde.members.filter(pk=benevole.pk).exists()

    def test_une_adresse_non_geocodable_est_signalee_sans_bloquer(self, client, benevole):
        """Une fiche sans position reste exploitable : on sait joindre la personne, on ne sait
        pas la placer sur une carte."""
        with patch('core.imports._geocoder_adresse', return_value=(None, None, None, None)):
            reponse = client.patch(URL_FICHE, {"adresse": "quelque part"}, format='json')

        assert reponse.status_code == 200
        assert "avertissement" in reponse.data
        assert FicheBenevole.objects.get(utilisateur=benevole).adresse == "quelque part"

    def test_modifier_autre_chose_que_l_adresse_ne_regeocode_PAS(self, client, benevole):
        """Un appel réseau à chaque enregistrement serait du gaspillage — et une panne de la
        BAN empêcherait alors de corriger une faute de frappe sans rapport."""
        with patch('core.imports._geocoder_adresse') as geocodeur:
            client.patch(URL_FICHE, {"metier": "Électricien"}, format='json')
        assert geocodeur.call_count == 0

    def test_chacun_ne_voit_que_SA_fiche(self, client, create_user, asso):
        """L'URL ne porte aucun identifiant : c'est toujours celle de l'appelant."""
        autre = create_user(username="autre@essai.invalide", email="autre@essai.invalide")
        FicheBenevole.objects.create(utilisateur=autre, metier="Secret")

        assert client.get(URL_FICHE).data['metier'] != "Secret"

    def test_un_visiteur_non_connecte_n_y_accede_pas(self):
        assert APIClient().get(URL_FICHE).status_code in (401, 403)
