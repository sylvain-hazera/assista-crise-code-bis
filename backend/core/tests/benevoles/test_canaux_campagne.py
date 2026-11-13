"""Choisir le canal d'une campagne en connaissant son coût.

Demande de Sylvain du 13/11/2026 : « compte tenu des coûts, on doit avoir la possibilité de
choisir entre brevo mail / brevo sms / mobimel / Matrix avec un rappel des coûts / solde
restant ».

Ce que ces tests tiennent :

1. **Le coût est un critère de choix**, annoncé avant l'envoi : écrire à quatre cents
   bénévoles ne vaut pas la même chose par email et par SMS.
2. **Un canal qui n'atteint personne est pire qu'un canal cher** : on annonce d'abord
   combien de gens chaque canal touche, et combien il laisse de côté.
3. **Zéro n'est pas gratuit** : un tarif non renseigné rend « coût inconnu », jamais « 0 € ».
   Annoncer la gratuité à tort ferait partir des SMS sans y penser.
4. **On ne bloque pas faute de crédits, on prévient** : partir quand même est une décision de
   l'association.
5. **Email seul par défaut** : une campagne existante ne doit pas se mettre à envoyer des SMS.
"""
import pytest

from core.canaux_campagne import (
    CANAL_EMAIL, CANAL_MATRIX, CANAL_MOBIMEL, CANAL_SMS, apercu_des_canaux,
)
from core.models import (
    CampagneDisponibilite, CibleCampagne, ConfigurationEnvoiInstitution, ContactInstitution,
    Institution, InstitutionType, MotifCampagne, UserRole,
)

import datetime

from django.utils import timezone


@pytest.fixture
def aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "Association"})
    return Institution.objects.create(nom="AASC Canaux", type=itype)


@pytest.fixture
def campagne(db, aasc):
    debut = timezone.localdate() + datetime.timedelta(days=10)
    return CampagneDisponibilite.objects.create(
        institution=aasc, intitule="Renfort", motif=MotifCampagne.CRISE_A_VENIR,
        periode_debut=debut, periode_fin=debut + datetime.timedelta(days=5),
        environment="PROD")


def _cible(create_user, campagne, aasc, nom, avec_email=True, avec_tel=True):
    user = create_user(
        username=f"{nom.lower()}-canal@test.fr",
        email=f"{nom.lower()}-canal@test.fr" if avec_email else "",
        type=UserRole.ORGANIZED_RESCUE, last_name=nom,
        phone_number="0612345678" if avec_tel else None)
    ContactInstitution.objects.create(institution=aasc, utilisateur=user, actif=True)
    return CibleCampagne.objects.create(campagne=campagne, utilisateur=user,
                                        environment="PROD")


def _par_code(apercu):
    return {c["code"]: c for c in apercu}


class TestCeQueChaqueCanalAtteint:
    def test_un_canal_qui_n_atteint_personne_est_annonce_comme_tel(
            self, create_user, campagne, aasc):
        """Pire qu'un canal cher : un canal qui ne joint personne."""
        cibles = [_cible(create_user, campagne, aasc, "SANSTEL", avec_tel=False)]

        canaux = _par_code(apercu_des_canaux(campagne, cibles))

        assert canaux[CANAL_EMAIL]["destinataires"] == 1
        assert canaux[CANAL_SMS]["destinataires"] == 0
        # Et surtout : combien ce canal LAISSE DE CÔTÉ, le chiffre qui manque quand on
        # choisit « le moins cher ».
        assert canaux[CANAL_SMS]["non_joignables"] == 1

    def test_matrix_n_est_pas_presente_comme_equivalent_aux_autres(self, campagne):
        """Gratuit, mais partiel : le dire est le seul moyen que ce ne soit pas un piège."""
        matrix = _par_code(apercu_des_canaux(campagne, []))[CANAL_MATRIX]

        assert "estimation haute" in matrix["detail"]
        assert matrix["cout_unitaire_centimes"] == 0


class TestLeCout:
    def test_le_total_est_chiffre_avant_l_envoi(self, create_user, campagne, aasc):
        ConfigurationEnvoiInstitution.objects.create(
            institution=aasc, brevo_actif=True, brevo_cle_api="xkeysib-x",
            brevo_expediteur_email="a@b.invalide", fournisseur_sms="BREVO",
            cout_unitaire_email=1, cout_unitaire_sms=6, environment="PROD")
        cibles = [_cible(create_user, campagne, aasc, f"C{i}") for i in range(3)]

        canaux = _par_code(apercu_des_canaux(campagne, cibles))

        assert canaux[CANAL_EMAIL]["cout_total_centimes"] == 3
        assert canaux[CANAL_SMS]["cout_total_centimes"] == 18

    def test_un_tarif_non_renseigne_rend_cout_inconnu(self, create_user, campagne, aasc):
        """Zéro n'est pas gratuit : annoncer la gratuité à tort ferait partir quatre cents
        SMS sans y penser."""
        ConfigurationEnvoiInstitution.objects.create(
            institution=aasc, fournisseur_sms="BREVO", environment="PROD")
        cibles = [_cible(create_user, campagne, aasc, "SANSTARIF")]

        canaux = _par_code(apercu_des_canaux(campagne, cibles))

        assert canaux[CANAL_SMS]["cout_total_centimes"] is None


class TestLeSolde:
    def test_le_solde_restant_est_rappele(self, create_user, campagne, aasc):
        ConfigurationEnvoiInstitution.objects.create(
            institution=aasc, brevo_actif=True, brevo_cle_api="xkeysib-x",
            brevo_expediteur_email="a@b.invalide", brevo_credits_email=5000,
            brevo_credits_sms=40, fournisseur_sms="BREVO", environment="PROD")
        cibles = [_cible(create_user, campagne, aasc, f"S{i}") for i in range(3)]

        canaux = _par_code(apercu_des_canaux(campagne, cibles))

        assert canaux[CANAL_EMAIL]["credits_restants"] == 5000
        assert canaux[CANAL_EMAIL]["credits_suffisants"] is True
        assert canaux[CANAL_SMS]["credits_suffisants"] is True

    def test_un_solde_insuffisant_est_dit_mais_ne_bloque_pas(
            self, create_user, campagne, aasc):
        """Partir quand même sur les cent premiers est une décision de l'association."""
        ConfigurationEnvoiInstitution.objects.create(
            institution=aasc, brevo_actif=True, brevo_cle_api="xkeysib-x",
            brevo_expediteur_email="a@b.invalide", brevo_credits_sms=1,
            fournisseur_sms="BREVO", environment="PROD")
        cibles = [_cible(create_user, campagne, aasc, f"I{i}") for i in range(3)]

        sms = _par_code(apercu_des_canaux(campagne, cibles))[CANAL_SMS]

        assert sms["credits_suffisants"] is False
        assert sms["disponible"] is True   # proposé quand même

    def test_un_solde_inconnu_n_est_pas_annonce_suffisant(self, create_user, campagne, aasc):
        cibles = [_cible(create_user, campagne, aasc, "INCONNU")]

        mobimel = _par_code(apercu_des_canaux(campagne, cibles))[CANAL_MOBIMEL]

        assert mobimel["credits_restants"] is None
        assert mobimel["credits_suffisants"] is None


class TestCeQuiEstPret:
    def test_un_canal_non_configure_est_annonce_indisponible(self, campagne):
        """Sans compte d'envoi, aucun canal payant n'est prêt — et l'écran le dit plutôt que
        de laisser cliquer."""
        canaux = _par_code(apercu_des_canaux(campagne, []))

        assert canaux[CANAL_EMAIL]["disponible"] is False
        assert canaux[CANAL_SMS]["disponible"] is False

    def test_mobimel_et_brevo_ne_sont_pas_proposes_ensemble(self, campagne, aasc):
        """Une institution a UN fournisseur SMS à la fois : proposer l'autre ferait choisir
        un canal qui n'enverra rien."""
        ConfigurationEnvoiInstitution.objects.create(
            institution=aasc, fournisseur_sms="MOBIMEL", sms_cle_api="abc",
            environment="PROD")

        canaux = _par_code(apercu_des_canaux(campagne, []))

        assert canaux[CANAL_MOBIMEL]["disponible"] is True
        assert canaux[CANAL_SMS]["disponible"] is False


class TestLeDefaut:
    def test_une_campagne_sans_canal_part_par_email(self, campagne):
        """Une campagne créée avant l'ajout des canaux ne doit pas se mettre à envoyer des
        SMS."""
        assert campagne.canaux == []
        assert campagne.canaux_effectifs == [CANAL_EMAIL]

    def test_les_canaux_choisis_sont_respectes(self, campagne):
        campagne.canaux = [CANAL_EMAIL, CANAL_SMS]
        campagne.save()

        assert campagne.canaux_effectifs == [CANAL_EMAIL, CANAL_SMS]
